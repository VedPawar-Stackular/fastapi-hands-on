from fastapi import FastAPI, HTTPException, Depends
from typing import Annotated, List, Optional
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum
from sqlmodel import SQLModel, Field, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from config import settings
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from pydantic import ConfigDict
from groq import AsyncGroq


engine = create_async_engine(settings.database_url, echo=True)
groq_client = AsyncGroq(api_key=settings.groq_api_key)

async def get_db():
    async with AsyncSession(engine) as session:
        yield session


class Type(str, Enum):
    HAND = "HAND"
    POWER = "POWER"
    MEASURING = "MEASURING"

# Mirrors changelog.xml changeset 4's backfill rule. Single source of truth
# so every new row gets the right default instead of relying on a one-off SQL UPDATE.
MAINTENANCE_INTERVAL_DAYS: dict[Type, int] = {
    Type.HAND: 90,
    Type.POWER: 30,
    Type.MEASURING: 14,
}

class ToolShared(SQLModel):
    # This strips whitespace globally for all string fields in this model
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1)
    type: Type
    department: str = Field(min_length=1)

class Tool(ToolShared, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    is_active: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    last_maintained_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # NOT NULL at the DB level (changelog changeset 5) — every Tool() construction
    # must set this, which is why create_tool computes it instead of leaving it to default.
    maintenance_interval_days: int


class ToolCreate(ToolShared):
    pass

class ToolRead(ToolShared):
    id: int
    is_active: bool
    created_at: datetime
    last_maintained_at: Optional[datetime]
    maintenance_interval_days: int


# request and response model for Groq / LLM for RAG
class AskRequest(BaseModel):
    question: str = Field(min_length=1)

class AskResponse(BaseModel):
    answer: str



# Disabling the ORM's auto-create
# create_all and Liquibase are two competing schema owners. create_all checks "does this table exist? no → create it" from your Python models — it has no concept of versioned, tracked, incremental changes. Liquibase checks its own DATABASECHANGELOG table for "have I run changeSet X before?" — independent of what the DB actually looks like. Run both, and create_all will silently recreate your table on next app startup (from the model, ignoring your changelog), masking whether Liquibase actually worked. In real projects you pick one schema owner — almost always Liquibase/Flyway once a project ships, since only migrations give you rollback, audit history, and safe production rollout. create_all is a prototyping-only shortcut.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # I want to implement a RAG Service here. Because the RAG serice depends on the data in the database that is stored, and as data keeps chaning in the database after each endpoint session, the RAG knowledge must also update based on that, session wise. My point is that, for any change, that involves change in the database via the endpoint, will eventually have to retrigger the RAG to get information from there. (This was my thinking process, which was wrong)
    # Now: RAG here queries Tool table live on every /tools/ask call — no
    # separate cached index, so no reindex-on-write step needed at this scale.

    # Schema now owned by Liquibase — see db/changelog/changelog.xml
    # async with engine.begin() as conn:
    #     await conn.run_sync(SQLModel.metadata.create_all)
    yield

app = FastAPI(lifespan=lifespan)

SessionDep = Annotated[AsyncSession, Depends(get_db)] 

#health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/tools/", response_model=ToolRead, status_code=201)
async def create_tool(tool_in: ToolCreate, db: SessionDep):
    tool=Tool(
        name=tool_in.name,
        type=tool_in.type,
        department=tool_in.department,
        maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS[tool_in.type],
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool

@app.get("/tools/", response_model=List[ToolRead], status_code=200) 
async def read_tools(
    db: SessionDep,
    department: str = None,
):
    if not department:
        result = await db.exec(select(Tool))
        return result.all()
    
    result = await db.exec(select(Tool).where(Tool.department==department))
    return result.all()


@app.get("/tools/{tool_id}", response_model=ToolRead)
async def read_all_tools(tool_id: int, db: SessionDep):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool
    

@app.put("/tools/{tool_id}", response_model=ToolRead)
async def update_tool(tool_id: int, tool_update: ToolCreate, db: SessionDep):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    tool.name = tool_update.name
    tool.type = tool_update.type
    tool.department = tool_update.department
    # Recompute so interval stays correct if type changed (e.g. HAND -> POWER
    # shouldn't leave the old 90-day interval sitting on a now-POWER tool)
    tool.maintenance_interval_days = MAINTENANCE_INTERVAL_DAYS[tool_update.type]

    await db.commit()
    await db.refresh(tool)
    return tool


@app.delete("/tools/{tool_id}", status_code=204) 
async def delete_tool(tool_id: int, db: SessionDep):
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    await db.delete(tool)
    await db.commit()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# RAG endpoint
@app.post("/tools/ask", response_model=AskResponse, status_code=200)
async def ask_ai(ask: AskRequest, db: SessionDep):
    result = await db.exec(select(Tool))
    tools = result.all()

    # Basic retrieval: keyword match against question text, fall back to
    # full inventory if nothing matches. No vector DB, no embeddings —
    # dataset is small enough that "grab everything relevant" is a valid
    # baseline retrieval strategy, not a cut corner.
    question_lower = ask.question.lower()
    matched = [
        t for t in tools
        if t.department.lower() in question_lower
        or t.type.value.lower() in question_lower
        or t.name.lower() in question_lower
    ]
    relevant_tools = matched or tools

    if not relevant_tools:
        return AskResponse(answer="No tools in the registry yet.")

    context = "\n".join(
        f"- {t.name} ({t.type.value}, dept: {t.department}, active: {t.is_active}, "
        f"maintenance every {t.maintenance_interval_days} days, "
        f"last maintained: {t.last_maintained_at or 'never'})"
        for t in relevant_tools
    )

    completion = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a tool registry assistant. Answer using only the "
                    "tool data given. If the data doesn't answer the question, "
                    "say you don't have that information."
                ),
            },
            {"role": "user", "content": f"Tool data:\n{context}\n\nQuestion: {ask.question}"},
        ],
    )

    return AskResponse(answer=completion.choices[0].message.content)

    