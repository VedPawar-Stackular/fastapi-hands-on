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
from fastapi.responses import Response

engine = create_async_engine(settings.database_url, echo=True)

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
    name: str
    type: Type
    department: str
    # Problem: https://share.google/aimode/OkQeFQWiNjzv78MMW
    # Python won't crash on this, but the type hint is lying. The correct form is: FastAPI uses the type hint to generate the OpenAPI docs. With str = None, it may show the parameter as required in Swagger even though it has a default.

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    #creating the database table.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
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
    # But the habit to build is the chainable query approach — because the moment a second filter gets added, this becomes four branches instead of two
    # Same outcome today, much better when it grows. Also: if not department has a subtle trap — an empty string "" is falsy, so ?department= (blank value) would skip the filter silently. if department is not None is the precise check.
    query = select(Tool)
    if department is not None:
        query = query.where(Tool.department == department)
    result = await db.exec(query)
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

    # FastAPI does handle this correctly in practice — if you return nothing from a status_code=204 endpoint, it sends an empty body. But we established the explicit pattern in the last session for a reason: it makes the intent unambiguous, and some HTTP clients behave unpredictably when they encounter a 204 with an accidentally-included body later. Keep the habit:
    return Response(status_code=204)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

