# Note before executing this file, change the name to "conftest.py" and change the location where needed

import sys, os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi.testclient import TestClient

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from src.my_app.app import app, get_db

# SQLite in-memory: cheap, fast, no external dependency.
# StaticPool forces every SQLAlchemy checkout to reuse the SAME connection
# so the schema we create actually persists for the test. Without it,
# SQLAlchemy opens a new connection per checkout, each one seeing an empty DB.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine + schema per test. Function-scoped so tests
    can't leak state into each other — each test starts with empty tables."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """One async session per test, bound to that test's in-memory engine."""
    async with AsyncSession(engine) as session:
        yield session


@pytest.fixture
def client(db_session):
    """TestClient with get_db overridden to use the per-test in-memory session.

    We intentionally do NOT use `with TestClient(app) as c:` here.
    Using `with` runs the lifespan, which calls create_all on the REAL
    production engine — not the test engine — and would fail if the real DB
    is not running. Table creation is handled by the engine fixture above,
    so skipping the lifespan is correct for these tests.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()