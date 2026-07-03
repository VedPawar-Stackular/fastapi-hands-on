from typing import Optional, List
from enum import Enum
from contextlib import asynccontextmanager

from pydantic import BaseModel
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response


# --- Enum for priority ---
# Using str + Enum means the values serialize to plain strings in JSON.
# Pydantic will automatically reject anything not in this list with a 422.
class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --- In-memory store ---
# A plain dict acting as our "database" for now.
# Key = ticket_id (int), Value = Ticket object.
# This pattern mirrors what a real DB session will look like in Days 3-4.
tickets_db: dict = {}


# --- Lifespan: defined BEFORE app is created ---
# Everything above the yield runs at startup.
# Everything below the yield runs at shutdown.
# The yield itself is just the pause point — the app runs while it waits there.
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    tickets_db[1] = Ticket(id=1, title="Replace hydraulic filter", priority=Priority.HIGH, reported_by="Alice")
    tickets_db[2] = Ticket(id=2, title="Calibrate pressure gauge", priority=Priority.MEDIUM, reported_by="Bob")
    tickets_db[3] = Ticket(id=3, title="Clean conveyor belt", priority=Priority.LOW, reported_by="Carol")

    yield

    print("Shutting down...")
    tickets_db.clear()


# --- App created ONCE, with lifespan, before any routes are registered ---
# Critical: if you create app = FastAPI() first and then app = FastAPI(lifespan=...)
# later, all routes registered in between are lost — they belonged to the first instance.
app = FastAPI(lifespan=lifespan)


# --- Pydantic models ---

# TicketCreate: what the CLIENT sends us.
# No id (the backend assigns that) and no is_resolved (always False on creation).
# Sending extra fields the client shouldn't control would be a security / logic mistake.
class TicketCreate(BaseModel):
    title: str
    priority: Priority      # Pydantic validates against the enum automatically
    reported_by: str


# Ticket: what WE send back.
# Includes id and is_resolved, which only the backend controls.
class Ticket(BaseModel):
    id: int
    title: str
    priority: Priority
    reported_by: str
    is_resolved: bool = False


# --- Dependency ---
# Returns the in-memory dict right now.
# In Days 3-4, this becomes an async database session.
# The payoff: every route using Depends(get_db) automatically gets the upgrade
# when we swap this one function — no touching individual routes.
def get_db() -> dict:
    return tickets_db


# ================
# ===========================================================
# ROUTES
# ===========================================================================

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/tickets", response_model=Ticket, status_code=201)
# 201 Created — we made a new resource. 200 would also not be wrong, but 201
# is the precise code for "a resource was created as a result of this request."
async def create_ticket(ticket: TicketCreate, db: dict = Depends(get_db)):
    # max(db.keys(), default=0) + 1 is safer than len(db) + 1:
    # if we delete ticket id=2 from {1,2,3}, len is 2 but max is 3.
    # len() + 1 would generate id=3 again — a collision.
    ticket_id = max(db.keys(), default=0) + 1
    full_ticket = Ticket(id=ticket_id, **ticket.model_dump())
    db[ticket_id] = full_ticket
    return full_ticket


@app.get("/tickets", response_model=List[Ticket])
async def read_tickets(
    priority: Optional[Priority] = None,
    is_resolved: Optional[bool] = None,
    db: dict = Depends(get_db)
):
    # Start with all tickets, then apply each filter only if the param was provided.
    # This handles all four cases automatically:
    #   no params        → all tickets
    #   priority only    → filter by priority
    #   is_resolved only → filter by is_resolved
    #   both params      → filter by both (the case your original code missed)
    tickets = list(db.values())
    if priority is not None:
        tickets = [t for t in tickets if t.priority == priority]
    if is_resolved is not None:
        tickets = [t for t in tickets if t.is_resolved == is_resolved]
    return tickets


@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def read_ticket(ticket_id: int, db: dict = Depends(get_db)):
    ticket = db.get(ticket_id)
    if not ticket:
        # raise, not return — HTTPException is caught by FastAPI's exception handler
        # which formats it into {"detail": "Ticket not found"} with the right status code.
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.put("/tickets/{ticket_id}", response_model=Ticket)
# PUT replaces the full resource. All editable fields must be provided.
# If the client only wants to update one field, PATCH is the right verb.
async def update_ticket(
    ticket_id: int,
    ticket_update: TicketCreate,
    db: dict = Depends(get_db)
):
    if not db.get(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Build a fresh Ticket, preserving the original id.
    # is_resolved stays as-is because TicketCreate doesn't include it —
    # updating content shouldn't accidentally re-open a resolved ticket.
    updated = Ticket(id=ticket_id, is_resolved=db[ticket_id].is_resolved, **ticket_update.model_dump())
    db[ticket_id] = updated
    return updated


@app.patch("/tickets/{ticket_id}/resolve", response_model=Ticket)
# PATCH changes one specific thing. No request body needed here —
# the intent is entirely expressed in the URL path ("/resolve").
async def resolve_ticket(ticket_id: int, db: dict = Depends(get_db)):
    ticket = db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.is_resolved = True
    db[ticket_id] = ticket
    return ticket


@app.delete("/tickets/{ticket_id}", status_code=204)
# 204 No Content — the HTTP spec says a 204 response MUST NOT include a body.
# So we return a bare Response(status_code=204), not the deleted ticket object.
# Some HTTP clients will error if you send a body with a 204.
async def delete_ticket(ticket_id: int, db: dict = Depends(get_db)):
    if not db.get(ticket_id):
        raise HTTPException(status_code=404, detail="Ticket not found")
    del db[ticket_id]
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)