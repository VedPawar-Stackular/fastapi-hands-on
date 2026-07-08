import sys, os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
#from sqlalchemy import create_engine
#from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Move up one level to the project root directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# Now you can import from src
from src.my_app.config import settings  
from src.my_app.app import app, get_db

# --- Test database URL -----------------------------------------------------
# Point this at a dedicated test DB (never your dev/prod DB).
# TEST_DATABASE_URL = "postgresql+psycopg2://user:pass@localhost:5432/test_db"
# For a lightweight alternative: "sqlite:///./test.db"
# sqlite's ":memory:" db lives inside a single connection. SQLAlchemy's pool
# normally hands out a new connection per checkout -> a fresh, empty db each
# time. StaticPool forces every checkout to reuse the SAME connection so the
# schema we create actually persists for the test.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# This creates a fixture for engine, session scoped where we can make a one time connection pool for the entire testing of the endpoints. 
#we set up the database connection as a session scope so that we can use the same connection pool for the entirety of tests. If we make it for each every test function using function scope, it would be a lot of load and time taking to opening and closing it on every function.
"""@pytest.fixture(scope="session")
def engine():
    ""Create the engine + connection pool once per test session.""
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True) # I dont knwo what pool_pre_ping does: I found about it online: pool_pre_ping=True tells SQLAlchemy to check that a database connection is still alive before handing it out from the connection pool. If the database has closed an idle connection (common with PostgreSQL, MySQL, etc.), SQLAlchemy automatically discards it and opens a new one instead of letting your query fail with a "connection closed" error.
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()"""
# engine is function-scoped (recreated per test) instead of session-scoped.
# A session-scoped engine needs transaction-rollback-per-test tricks to keep
# tests isolated from each other. sqlite in-memory is cheap enough that
# "drop everything, recreate schema" per test is simpler and can't leak state
# by accident.
@pytest_asyncio.fixture
async def engine():
    """Create a fresh in-memory engine + schema for each test."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()



# this just makes a session factory that knows how to make a session, we can keep this session scoped as this would be created once by a test and then never untill all the tests are completed. In this way, we have a once time sessionmaker made, which can then later make a session for each test case when needed.
"""@pytest.fixture(scope="session")
def SessionLocal(engine):
    ""Session factory bound to the session-scoped engine.""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)"""


# This is the function scope that would run on each test endpoint, that would connect to the sesison scoped database pool, and would make a sesion which is fucntion based, hence making a new session for each endpoint test that calls it. It would then close it, rollback the trasactions that happned inside and close the connection.
"""@pytest.fixture(scope="function")
def db_session(engine, SessionLocal):
    ""
    Function-scoped session wrapped in a transaction that's rolled back
    after each test, so tests don't leak state into one another.
    ""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()"""


@pytest_asyncio.fixture
async def db_session(engine):
    async with AsyncSession(engine) as session:
        yield session


#we set up a client who will get a session assigned to it and will be used for tests in each endpoint. The session each endpoint must work in must be function scoped or else one endpoint work can be leaked into the other endpoint work if they both are tested within the same session. 
# also the below client is function scoped, which makes sense, because each endpoint will call one client which will need its one own db_session. It this was session scoped, then each endpoint would have the same clint through testing and there would be so many errors and confusions with testing.
# here when the client is called in the endpoint, we override the main databse using dependency injection and get a test database whihc is then passed into the testclient app, and the testing is carried on there.
"""@pytest.fixture(scope="function")
def client(db_session):
    ""
    TestClient with the app's get_db dependency overridden to use the
    per-test transactional session.
    ""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # session lifecycle is managed by db_session fixture
    app.dependency_overrides[get_db] = override_get_db
    TestClient(app) # <- no "with", lifespan skipped
    app.dependency_overrides.clear()"""


# Overrides the app's get_db dependency so requests through this TestClient
# use our per-test in-memory session instead of the real engine app.py
# creates at import time.
# Uses "with TestClient(app) as c:" so the lifespan runs (startup/shutdown hooks) instead of being silently skipped.
@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
