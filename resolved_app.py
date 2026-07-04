from fastapi import FastAPI, HTTPException, Depends
from typing import Annotated, List, Optional
from fastapi.responses import Response
from contextlib import asynccontextmanager
from enum import Enum
from sqlmodel import SQLModel, Field, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from config import settings
from datetime import datetime, timezone

# Creates the async connection pool. echo=True prints every SQL statement
# to the terminal the moment it executes — useful for watching exactly
# what INSERT/SELECT/UPDATE fires on each endpoint hit.
engine = create_async_engine(settings.database_url, echo=True)


async def get_db():
    # yield (not return) because the session must stay open for the entire
    # duration of the request. yield hands the session to the route function,
    # pauses here, and only resumes (to close the session) after the route
    # has finished executing. A return would close the session immediately.
    async with AsyncSession(engine) as session:
        yield session


# --- Enums ---

class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- Ticket: 4-class pattern ---

class TicketBase(SQLModel):
    title: str
    priority: Priority      # ← wired to enum: "URGENT" now gives a 422 automatically
    reported_by: str

class TicketCreate(TicketBase):
    # Inherits only the client-controlled fields. id and is_resolved are
    # assigned by the backend, so they must not appear here.
    pass

class TicketRead(TicketBase):
    # What we send back. Separate from Ticket (the table model) so that
    # adding internal-only columns to Ticket doesn't accidentally leak them
    # through the API response.
    id: int
    is_resolved: bool

class Ticket(TicketBase, table=True):
    # table=True registers this as a real PostgreSQL table.
    # Without it, SQLModel treats the class as a plain Pydantic schema.
    id: Optional[int] = Field(default=None, primary_key=True)
    is_resolved: bool = False


# --- Comment: 4-class pattern ---

class CommentBase(SQLModel):
    content: str

class CommentCreate(CommentBase):
    pass

class CommentRead(CommentBase):
    id: int
    ticket_id: int
    created_at: datetime       # datetime, not str

class Comment(CommentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")
    # default_factory stamps the timestamp automatically on every insert.
    # No need to set it manually in the route — the model handles it.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # engine.begin() is a raw connection (not a session) used for DDL.
    # create_all checks which tables already exist and only creates missing ones.
    # It will not drop or recreate existing tables, so data is safe on restart.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    # shutdown — nothing to clean up for now


# --- App created once, with lifespan, before any routes ---

app = FastAPI(lifespan=lifespan)

# Annotated shorthand so every route can write `db: SessionDep` instead of
# the full `db: AsyncSession = Depends(get_db)` each time.
SessionDep = Annotated[AsyncSession, Depends(get_db)]


# ===========================================================================
# ROUTES
# ===========================================================================

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/tickets/", response_model=TicketRead, status_code=201)
async def create_ticket(ticket_in: TicketCreate, db: SessionDep):
    ticket = Ticket(**ticket_in.model_dump())
    db.add(ticket)          # Python-side only — no SQL yet
    await db.commit()       # INSERT fires here; Postgres assigns id
    await db.refresh(ticket)  # SELECT fires here; Python object now has real id
    return ticket


@app.get("/tickets/", response_model=List[TicketRead])
async def read_tickets(
    db: SessionDep,
    priority: Optional[Priority] = None,
    is_resolved: Optional[bool] = None,
):
    # Build the query object first, then execute it once.
    # select(Ticket) returns a query object — no SQL sent yet.
    # Each .where() appends an AND condition to that query.
    # This handles all four combinations: no params, either param, both params.
    query = select(Ticket)
    if priority is not None:
        query = query.where(Ticket.priority == priority)
    if is_resolved is not None:
        query = query.where(Ticket.is_resolved == is_resolved)
    result = await db.exec(query)
    return result.all()


@app.get("/tickets/{ticket_id}", response_model=TicketRead)
async def read_ticket(ticket_id: int, db: SessionDep):
    # session.get() is for primary-key lookups only — the fastest path
    # when you know the exact id. No filtering possible, just a direct fetch.
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.put("/tickets/{ticket_id}", response_model=TicketRead)
async def update_ticket(ticket_id: int, ticket_update: TicketCreate, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Mutate the fields that belong to the client.
    # is_resolved is intentionally untouched — a content update should not
    # silently re-open a resolved ticket.
    ticket.title = ticket_update.title
    ticket.priority = ticket_update.priority
    ticket.reported_by = ticket_update.reported_by
    await db.commit()
    await db.refresh(ticket)
    return ticket


@app.patch("/tickets/{ticket_id}/resolve", response_model=TicketRead)
async def resolve_ticket(ticket_id: int, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.is_resolved = True
    await db.commit()
    await db.refresh(ticket)
    return ticket


@app.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: int, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await db.delete(ticket)
    await db.commit()
    return Response(status_code=204)    # 204 must have no body


# --- Comment endpoints ---

@app.post("/tickets/{ticket_id}/comments/", response_model=CommentRead, status_code=201)
async def create_comment(ticket_id: int, comment_in: CommentCreate, db: SessionDep):
    # Always verify the parent ticket exists before inserting a child row.
    # Without this check, a comment on a non-existent ticket would either
    # fail with a FK constraint error (ugly 500) or silently orphan the row.
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # created_at is set automatically by the field's default_factory.
    comment = Comment(content=comment_in.content, ticket_id=ticket_id)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@app.get("/tickets/{ticket_id}/comments/", response_model=List[CommentRead])
async def read_comments(ticket_id: int, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # select + where is the right tool here because we're filtering by a
    # non-primary-key column (ticket_id). session.get() only works with PK.
    result = await db.exec(select(Comment).where(Comment.ticket_id == ticket_id))
    return result.all()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)