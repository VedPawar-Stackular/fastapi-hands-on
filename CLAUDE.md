# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Interview-prep learning project for FastAPI fundamentals (ticket-tracker API). User is preparing for interviews and using this repo as hands-on practice ground — expect heavy inline comments in `app.py` documenting their own reasoning/uncertainty as they build. Preserve that learning intent: when fixing bugs or reviewing code here, explain the underlying concept and why the fix works, don't just silently correct it — the goal is interview-readiness, not just a working app.

`main.py` is the unused default stub from `uv init` (`uv run fastapi-hands-on`) — the real app lives entirely in `app.py`.

## Commands

Package manager is **uv** (`uv.lock` present, Python 3.12 pinned via `.python-version`).

```bash
uv sync                                   # install deps
uv run uvicorn app:app --reload           # run dev server (http://127.0.0.1:8000/docs for Swagger UI)
uv run python app.py                      # alt: run directly (binds 0.0.0.0:8000, no reload)
uv add <package>                          # add a dependency
```

No test suite, linter, or formatter is configured yet.

## Architecture

Single-file FastAPI app (`app.py`) — no routers/services/models split. Everything lives here:

- **In-memory "database"**: `tickets_db: dict[int, Ticket]` module-level dict, keyed by `ticket_id`. Reset every process restart.
- **Lifespan seeding**: `lifespan()` (`@asynccontextmanager`) seeds tickets 1 and 2 on startup and deletes them on shutdown — this is why the DB never starts empty but also never accumulates state across manual restarts.
- **Dependency injection**: `get_db()` returns `tickets_db` and is injected via `Depends(get_db)` into every route — the seam that would let a real DB replace the dict later without touching route logic.
- **Two Pydantic models**: `TicketCreate` (client-facing input: `title`, `priority`, `reported_by`) vs `Ticket` (full stored/response model: adds `id` and `is_resolved`). Routes construct `Ticket` from `TicketCreate` via `Ticket(id=ticket_id, **ticket.model_dump())`.
- **`Priority`** is a `str` Enum (`LOW`/`MEDIUM`/`HIGH`) used both as a field type and as an optional query filter on `GET /tickets/`.
- **ID generation**: `len(tickets_db) + 1` in `create_ticket` — naive, will collide after deletes (known sharp edge, not yet fixed).

### Routes (all under `/tickets`)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness check |
| POST | `/tickets/` | 201, builds `Ticket` from `TicketCreate` |
| GET | `/tickets/` | list + optional `priority`/`is_resolved` query filters |
| GET | `/tickets/{ticket_id}` | 404 if missing |
| PUT | `/tickets/{ticket_id}` | full replace via `TicketCreate` body |
| PATCH | `/tickets/{ticket_id}/resolve` | sets `is_resolved = True` |
| DELETE | `/tickets/{ticket_id}` | 204, no body |

## `mistakes-explained.html`

Running personal log of mistakes made while building this + explanations, kept as an interview-prep reference by the user. When the user flags a new mistake, add an entry here in the same style rather than only fixing the code — check the existing entries for tone/format before appending.
