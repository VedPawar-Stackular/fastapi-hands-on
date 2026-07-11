import sys, os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

import pytest
from src.my_app.app import Tool, MAINTENANCE_INTERVAL_DAYS


# initial one time initialization call to set up the database connection pool and set up the session factory to create the sessions when the endpoints will call them. these are session based, hence they will stay the entire way until the connections are not closed.
# Also i am adding these into the test databases right, if i am not wrong, so i must add all possible values at first? to test it later, or i can add manually one by one and test for each, for eg: POST endpoint, i would have to post a data row and then check whether the values there are correct or not, so i guess i will do it manually and check.
@pytest.fixture
async def existing_item(db_session):
    # 1. Define all your tool instances in a list
    # maintenance_interval_days is required (NOT NULL in DB) — passed explicitly
    # here since we're constructing Tool() directly, bypassing create_tool's logic.
    tools = [
        Tool(name="Sample Tool 2", type="POWER", department="Mechanical", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["POWER"]),
        Tool(name="Sample Tool 3", type="HAND", department="Carpentry", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["HAND"]),
        Tool(name="Sample Tool 4", type="MEASURING", department="Automotive", maintenance_interval_days=MAINTENANCE_INTERVAL_DAYS["MEASURING"]),
    ]
    
    # 2. Add the list of instances in bulk
    db_session.add_all(tools)
    await db_session.commit()
    
    # 3. Refresh items if you need updated auto-incremented IDs or DB-generated values
    for tool in tools:
        await db_session.refresh(tool)
        
    return tools

# Define the payload as a fixture
@pytest.fixture
def tool_payload():
    return {"name": "Sample Tool 1", "type": "POWER", "department": "Electrical"}

# Post Endpoint
# 1. Happy path
def test_create_tool_happy(client, tool_payload):
    response = client.post("/tools/", json=tool_payload)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Sample Tool 1"
    assert "id" in body

# 2. 404 error check - not possible for out POST endpoint, unless we were hitting a specific parent URL that doesnt exist, like POST/tools/98/item

# 3. Invalid path (will use parametrized) - The point of test is to give wrong values to test all possible wrong values that could be given from user and see if the code detects it or not.
@pytest.mark.parametrize(
    "payload",
    [
        # --- Missing Fields ---
        {},  # All fields missing
        {"type": "HAND", "department": "HQ"},  # Missing name
        {"name": "Saw", "department": "HQ"},  # Missing type
        {"name": "Saw", "type": "HAND"},  # Missing department
        
        # --- None / Null Values ---
        {"name": None, "type": "HAND", "department": "HQ"},
        {"name": "Saw", "type": None, "department": "HQ"},
        {"name": "Saw", "type": "HAND", "department": None},
        
        # --- Enum Boundary Testing ---
        {"name": "Saw", "type": "hand", "department": "HQ"},  # Lowercase (Enums are case-sensitive)
        {"name": "Saw", "type": "ENERGY", "department": "HQ"},  # Completely invalid enum string
        {"name": "Saw", "type": 5, "department": "HQ"},  # Integer instead of enum string
        
        # --- Empty Strings (Only works if min_length=1 is set on the model) ---
        {"name": "", "type": "HAND", "department": "HQ"},
        {"name": "Saw", "type": "HAND", "department": "   "},  # Whitespace only
        
        # --- Extreme Input / Type Abuse ---
        {"name": "Saw", "type": "HAND", "department": []},  # Passing a list into a string field
        {"name": "Saw", "type": "HAND", "department": {}},  # Passing a dict into a string field
    ],
)
def test_create_tool_invalid_input(client, payload):
    response = client.post("/tools/", json=payload)
    assert response.status_code == 422


# Get endpoint - To get tool information
# 1. Happy path
# so here the client makes the session for the database, and we pass existing_item to add the sample data into this test database, on which we can now test the get endpoint.
@pytest.mark.anyio  # Required to resolve the async 'existing_item' fixture
def test_read_tools_happy(client, existing_item): # the existing_item is not being used inside, how is it getting the sample test database data to be added into the database and be used for the testing here below
    # how do i know that the test i have written below takes in all the edge cases, there has to be a tool or a trick to do that right.
    response = client.get("/tools")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list)
    assert len(json_data) == 3

    assert json_data[0]["name"] == "Sample Tool 2"
    assert json_data[1]["type"] == "HAND"
    assert json_data[2]["department"] == "Automotive"


# 2. 404 - There can be a resource does not exist error in this api endpoint as we are requesting for all resources, there could be one situation when the URL is not valid, hence it is giving a no resource exist error, or when the database is empty, in that case it could also be showing an empty array as output, with a 200 response.
def test_read_tools_404(client):
    response = client.get("/tools")
    assert response.status_code == 200
    json_data = response.json()
    assert isinstance(json_data, list) # does this mean that we expect the final output from the get endpoint to be a list, here even if there is nothing in the database, the list should be given as a empty list.
    assert len(json_data) == 0


# 3. Invalid input
# As client is not sending any input, there is no chance of this error happening, unless the URL that they send is malformed.

# GET endpoint - to get a specific tool information
# 1. Happy path
@pytest.mark.anyio
def test_read_tool_happy(client, existing_item):
    response = client.get(f"/tools/{existing_item[0].id}")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["id"] == existing_item[0].id
    assert json_data["name"] == "Sample Tool 2"
    assert json_data["type"] == "POWER"
    assert json_data["department"] == "Mechanical"

# 2. 404
@pytest.mark.anyio
def test_read_tool_404(client, existing_item):
    response = client.get("/tools/99")
    assert response.status_code == 404

# 3. invalid input
# Define the base URL of your API
#BASE_URL = "http://127.0.0"
@pytest.mark.parametrize(
    "query_params, expected_status",
    [
        # Missing required parameter
        ({"tool_id": ""}, 404),
        # Invalid data type (string instead of expected integer)
        ({"tool_id": "not_an_int"}, 404),
        # SQL Injection attempts
        ({"tool_id": "' OR 1=1 --"}, 404),
        # Cross-Site Scripting (XSS) inputs
        ({"tool_id": "<script>alert(1)</script>"}, 404),
        # Extreme/Boundary lengths
        ({"tool_id": "A" * 10000}, 404),
    ]
)
def test_read_tool_invalid_input(client, query_params, expected_status):
    """
    Test the GET endpoint against various invalid client inputs.
    """
    # Make the actual GET request to your application
    response = client.get("http://127.0.0", params=query_params)
    
    # Assert that the endpoint returns the expected client-error status (e.g., 400, 414)
    assert response.status_code == expected_status




# PUT endpoint 
# 1. Happy path
# we have the tool_payload fixture, we can use that to see if the updated content that we add from here reflects in the output or not.
def test_update_tool_happy(client, existing_item, tool_payload):
    tool_id = existing_item[0].id
    response = client.put(f"/tools/{tool_id}", json=tool_payload)

    assert response.status_code == 200

    updated_tool = response.json()
    assert updated_tool["name"] == tool_payload["name"]
    assert updated_tool["type"] == tool_payload["type"]
    assert updated_tool["department"] == tool_payload["department"]

# 2. 404
def test_update_tool_404(client, tool_payload):
    response = client.put(f"/tools/12", json=tool_payload)
    assert response.status_code == 404


# 3. invalid input
# Test cases for INVALID PATH PARAMETERS (tool_id)
@pytest.mark.parametrize(
    "tool_id, payload, expected_status",
    [
        # Invalid data type (string instead of expected integer)
        ("not_an_int", {"name": "Test", "type": "HAND", "department": "X"}, 422), # FastAPI handles type validation
        # SQL Injection attempts (if malicious strings reach DB)
        ("' OR 1=1 --", {"name": "Test", "type": "HAND", "department": "X"}, 422), # ID must be an int
        # Extreme/Boundary lengths (excessive string for integer validation)
        ("A" * 10000, {"name": "Test", "type": "HAND", "department": "X"}, 422),
    ]
)
def test_update_tool_invalid_id(client, tool_id, payload, expected_status):
    """Test the PUT endpoint with invalid tool_id formats in the path."""
    response = client.put(f"/tools/{tool_id}", json=payload)
    assert response.status_code == expected_status

# Test cases for INVALID REQUEST BODY (ToolCreate input validation)
@pytest.mark.parametrize(
    "tool_id, payload, expected_status",
    [
        # Missing required parameter in body
        (1, {"type": "A", "department": "X"}, 422), # Assuming Pydantic requires 'name'
        # Sending empty data
        (1, {}, 422), 
        # Invalid data types in the body (e.g., passing a number where a string is expected)
        (1, {"name": 12345, "type": "A", "department": "X"}, 422),
    ]
)
def test_update_tool_invalid_body(client, tool_id, payload, expected_status):
    """Test the PUT endpoint with invalid data payloads inside the request body."""
    response = client.put(f"/tools/{tool_id}", json=payload)
    assert response.status_code == expected_status



# DELETE Endpoint
# 1. Happy path
def test_delete_tool_happy(client, existing_item):
    tool_id = existing_item[0].id
    response = client.delete(f"/tools/{tool_id}")
    assert response.status_code == 204

    get_response = client.get(f"/tools/{tool_id}")
    assert get_response.status_code == 404


# 2. 404
def test_delete_tool_404(client):
    response = client.delete(f"/tools/12")
    assert response.status_code == 404


# 3. Invalid input
@pytest.mark.parametrize(
    "tool_id, expected_status",
    [
        # Invalid data type (string instead of expected integer)
        ("not_an_int", 422), 
        # SQL Injection attempt in the URL path
        ("' OR 1=1 --", 422), 
        # Extreme/Boundary path lengths
        ("A" * 10000, 422),
    ]
)
def test_delete_tool_invalid_id(client, tool_id, expected_status):
    """Test the DELETE endpoint with invalid tool_id formats in the path."""
    response = client.delete(f"/tools/{tool_id}")
    assert response.status_code == expected_status