import sys, os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

import pytest
import pytest_asyncio          # ← must import to use @pytest_asyncio.fixture
from src.my_app.app import Tool, MAINTENANCE_INTERVAL_DAYS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# @pytest_asyncio.fixture (not @pytest.fixture) because this is an async
# function. @pytest.fixture does not await coroutines — it would hand the
# test a coroutine object instead of the list of tools, causing
# "TypeError: 'coroutine' object is not subscriptable" on existing_item[0].id
@pytest_asyncio.fixture
async def existing_item(db_session):
    tools = [
        Tool(name="Sample Tool 2", type="POWER", department="Mechanical", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["POWER"]),
        Tool(name="Sample Tool 3", type="HAND", department="Carpentry", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["HAND"]),
        Tool(name="Sample Tool 4", type="MEASURING", department="Automotive", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["MEASURING"]),
    ]
    db_session.add_all(tools)
    await db_session.commit()
    for tool in tools:
        await db_session.refresh(tool)
    return tools


@pytest.fixture
def tool_payload():
    return {"name": "Sample Tool 1", "type": "POWER", "department": "Electrical"}


# ---------------------------------------------------------------------------
# POST /tools/
# ---------------------------------------------------------------------------

def test_create_tool_happy(client, tool_payload):
    response = client.post("/tools/", json=tool_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Sample Tool 1"
    assert "id" in body


@pytest.mark.parametrize(
    "payload",
    [
        # Missing fields
        {},
        {"type": "HAND", "department": "HQ"},
        {"name": "Saw", "department": "HQ"},
        {"name": "Saw", "type": "HAND"},
        # None values
        {"name": None, "type": "HAND", "department": "HQ"},
        {"name": "Saw", "type": None, "department": "HQ"},
        {"name": "Saw", "type": "HAND", "department": None},
        # Invalid enum values
        {"name": "Saw", "type": "hand", "department": "HQ"},   # lowercase
        {"name": "Saw", "type": "ENERGY", "department": "HQ"}, # unknown value
        {"name": "Saw", "type": 5, "department": "HQ"},        # int instead of str
        # Empty / whitespace strings (rejected because min_length=1 + strip)
        {"name": "", "type": "HAND", "department": "HQ"},
        {"name": "Saw", "type": "HAND", "department": "   "},  # stripped → ""
        # Wrong types for string fields
        {"name": "Saw", "type": "HAND", "department": []},
        {"name": "Saw", "type": "HAND", "department": {}},
    ],
)
def test_create_tool_invalid_input(client, payload):
    response = client.post("/tools/", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /tools/
# ---------------------------------------------------------------------------

# No @pytest.mark.anyio — this test function is synchronous (uses TestClient).
# anyio is a separate async library; that mark is for async def test functions
# running under anyio, which is not the case here.
# existing_item is listed as a parameter purely for its side effect: it inserts
# 3 tools into db_session before this test runs. pytest resolves and runs every
# requested fixture even if the test body never uses the return value.
def test_read_tools_happy(client, existing_item):
    response = client.get("/tools")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list)
    assert len(json_data) == 3
    assert json_data[0]["name"] == "Sample Tool 2"
    assert json_data[1]["type"] == "HAND"
    assert json_data[2]["department"] == "Automotive"


# Renamed from test_read_tools_404 — the endpoint returns 200 + [] for an
# empty collection, not 404. A 404 means "this route doesn't exist."
# GET /tools/ always exists; it just has no rows yet.
def test_read_tools_empty_returns_200(client):
    response = client.get("/tools")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list)
    assert len(json_data) == 0


# ---------------------------------------------------------------------------
# GET /tools/{tool_id}
# ---------------------------------------------------------------------------

def test_read_tool_happy(client, existing_item):
    response = client.get(f"/tools/{existing_item[0].id}")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == existing_item[0].id
    assert json_data["name"] == "Sample Tool 2"
    assert json_data["type"] == "POWER"
    assert json_data["department"] == "Mechanical"


def test_read_tool_404(client, existing_item):
    response = client.get("/tools/99")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "tool_id, expected_status",
    [
        # Non-integer path values: FastAPI validates path params before your
        # function runs, so these all return 422 — not 404.
        ("not_an_int", 422),
        ("' OR 1=1 --", 422),              # SQL injection attempt
        ("<script>alert(1)</script>", 422), # XSS attempt
        ("A" * 1000, 422),                  # extreme length
        # Note: empty string is NOT tested here.
        # /tools/ (no id) routes to GET /tools/ (list endpoint) → 200, not 404.
    ],
)
def test_read_tool_invalid_input(client, tool_id, expected_status):
    # tool_id goes in the URL path, not as a query parameter.
    # The original code sent requests to "http://127.0.0" which is not
    # a valid address and would fail with a connection error.
    response = client.get(f"/tools/{tool_id}")
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# PUT /tools/{tool_id}
# ---------------------------------------------------------------------------

def test_update_tool_happy(client, existing_item, tool_payload):
    tool_id = existing_item[0].id
    response = client.put(f"/tools/{tool_id}", json=tool_payload)
    assert response.status_code == 200
    updated_tool = response.json()
    assert updated_tool["name"] == tool_payload["name"]
    assert updated_tool["type"] == tool_payload["type"]
    assert updated_tool["department"] == tool_payload["department"]


def test_update_tool_404(client, tool_payload):
    response = client.put("/tools/12", json=tool_payload)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "tool_id, payload, expected_status",
    [
        ("not_an_int", {"name": "Test", "type": "HAND", "department": "X"}, 422),
        ("' OR 1=1 --", {"name": "Test", "type": "HAND", "department": "X"}, 422),
        ("A" * 1000, {"name": "Test", "type": "HAND", "department": "X"}, 422),
    ],
)
def test_update_tool_invalid_id(client, tool_id, payload, expected_status):
    response = client.put(f"/tools/{tool_id}", json=payload)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "tool_id, payload, expected_status",
    [
        # Missing required field in body
        (1, {"type": "HAND", "department": "X"}, 422),
        # Empty body
        (1, {}, 422),
        # Note: {"name": 12345, "type": "HAND", "department": "X"} was here.
        # Pydantic v2 coerces int → str in lax mode, so 12345 becomes "12345"
        # which IS valid. That case does not produce 422 — removed to avoid
        # a test that passes for the wrong reason. If strict coercion matters,
        # add model_config = ConfigDict(strict=True) to ToolCreate.
        (1, {"name": "Saw", "type": "INVALID_ENUM", "department": "X"}, 422),
    ],
)
def test_update_tool_invalid_body(client, tool_id, payload, expected_status):
    response = client.put(f"/tools/{tool_id}", json=payload)
    assert response.status_code == expected_status


# ---------------------------------------------------------------------------
# DELETE /tools/{tool_id}
# ---------------------------------------------------------------------------

def test_delete_tool_happy(client, existing_item):
    tool_id = existing_item[0].id
    response = client.delete(f"/tools/{tool_id}")
    assert response.status_code == 204
    # Confirm the row is gone — this is the second assertion that makes
    # the happy-path test meaningful. A 204 alone doesn't prove deletion.
    get_response = client.get(f"/tools/{tool_id}")
    assert get_response.status_code == 404


def test_delete_tool_404(client):
    response = client.delete("/tools/12")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "tool_id, expected_status",
    [
        ("not_an_int", 422),
        ("' OR 1=1 --", 422),
        ("A" * 1000, 422),
    ],
)
def test_delete_tool_invalid_id(client, tool_id, expected_status):
    response = client.delete(f"/tools/{tool_id}")
    assert response.status_code == expected_status