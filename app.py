from fastapi import FastAPI, HTTPException, Depends
from typing import List
# from litellm import BaseModel
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum

#app = FastAPI()

# dictionary to store tickets, acting as a database, I didnt know how the format inside the dictionary would look like, i guess that is important before making endpoints, i feel like because it becomes easier to visualize the data structure and becomes easy to make enpoints and move and play with the data aorund and do the each endpoint logic easily. 
# I guess the format of the dictionary would be like this: {ticket_id: Ticket object}, where ticket_id is an integer and Ticket object is an instance of the Ticket class. This acts like a key-value pair, where the key is the ticket_id and the value is the Ticket object. This way, we can easily access a ticket by its id and perform operations on it.
tickets_db = {}


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    
# we did not create a ticket_id in TicketCreate response model because that is not something the user sends us, that is something that the backend logic must add into. also, is_resolved is not something the user sends us, because logically, when a ticket is created, it is not resolved yet, so the default value of is_resolved is False. hence that is why we did not include ticket_id and is_resolved in the TicketCreate response model.
class TicketCreate(BaseModel):
    title: str
    priority: Priority
    reported_by: str

class Ticket(BaseModel):
    id: int
    title: str
    priority: Priority
    reported_by: str
    is_resolved: bool = False

#How is making this dependency helping us here? 
def get_db():
    return tickets_db


# making a startup/shutdown event handler to have some tickets in the database when the server starts up. In terms of the syntax, keywords, i dont know what is happening, but in terms of the logic, I know that each time the server starts up, the thing is going to run the code inside the startup event handler, and each time the server shuts down, the thing is going to run the code inside the shutdown event handler. Hence, we can use this to add some tickets to the database when the server starts up, and remove them when the server shuts down.
@asynccontextmanager
async def lifespan(app: FastAPI):
    #STARTUP
    print("Starting up the application...")
    # Add some initial tickets to the "database"
    tickets_db[1] = Ticket(id=1, title="Sample Ticket 1", priority="HIGH", reported_by="User A")
    tickets_db[2] = Ticket(id=2, title="Sample Ticket 2", priority="MEDIUM", reported_by="User B")

    yield  # This is where the application runs

    #SHUTDOWN
    print("Shutting down the application...")
    # Clean up resources if needed (not necessary in this simple example)
    del tickets_db[1]
    del tickets_db[2]

# i dont know again what this does, but this is what the format is, so i added this
#ans: create the app once, passing the lifespan. 
app = FastAPI(lifespan=lifespan)


#health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/tickets/", response_model=Ticket, status_code=201) # i did status_code=201 because I am creating a resource, and 201 is the status code for resource creation.
async def create_ticket(ticket: TicketCreate, tickets_db: dict = Depends(get_db)):
    # Generate a simple ID (in a real app, you'd use a proper ID generation strategy)
    ticket_id = len(tickets_db) + 1
    # Create the 'full ticket' object
    full_ticket = Ticket(id=ticket_id, **ticket.model_dump())
    # Store the ticket in the "database"
    tickets_db[ticket_id] = full_ticket
    return full_ticket



@app.get("/tickets/", response_model=List[Ticket], status_code=200) #used status_code=200 because I am fetching a resource, and 200 is the status code for successful resource fetching.
async def read_tickets(
    #ticket_id: int = None,
    priority: str = None,
    is_resolved: bool = None,
    tickets_db: dict = Depends(get_db)
): # added two optional query parameters, priority and is_resolved. I had put ticket_id as optional because I want to be able to fetch all tickets if no ticket_id is provided. Although, I think even if there is not a ticket_id it should be fine as there is no need for the client to send ticket_id as we would be going through all the tickets anyway in the database to check for any filters and give the response.

    # ticket = tickets_db.get(ticket_id)
    filtered_ticket = {} # my thought process is to make a dict to store all the filtered tickets, but I am not sure if this is the best approach.

    if priority is None and is_resolved is None:
        # if no filters are provided, return the all tickets as is
        return tickets_db.values()
    
    #we must loop thorugh the entries in the tickets_db for each ticket, and then filter it based on the priority and is_resolved parameters.
    for ticket_id, ticket in tickets_db.items():

        #this condition is to check if the tickets in the database are empty. But this can be done outside the for loop as well.
        if not ticket_id:
            raise HTTPException(status_code=404, content={"detail": "Ticket not found"})
        
        # if priority is not None and ticket.priority != priority:
        #     return HTTPResponse(status_code=404, content={"detail": "Ticket not found"})
        # if is_resolved is not None and ticket.is_resolved != is_resolved:
        #     return HTTPResponse(status_code=404, content={"detail": "Ticket not found"})

        if priority is not None and is_resolved is None:
            # we only filter by priority
            if ticket.priority == priority:
                filtered_ticket[ticket_id]=ticket

        if priority is None and is_resolved is not None:
            # we only filter by is_resolved
            if ticket.is_resolved == is_resolved:
                filtered_ticket[ticket_id] = ticket

        # if both the parameters are provided, we filter by both
        if priority is not None and is_resolved is not None:
            if ticket.priority == priority and ticket.is_resolved == is_resolved:
                filtered_ticket[ticket_id] = ticket

    return list(filtered_ticket.values()) # the response model we are using is a list of tickets to be returned, and currently filtered_ticket is a dict, so we must take the values of it and convert it to a list and then return it, which is what we did.



@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def read_all_tickets(ticket_id: int = None, tickets_db: dict = Depends(get_db)):
    ticket = tickets_db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, content={"detail": "Ticket not found"})
    return ticket
    

@app.put("/tickets/{ticket_id}", response_model=Ticket)
async def update_ticket(ticket_id: int, ticket_update: TicketCreate, tickets_db: dict = Depends(get_db)):
    ticket = tickets_db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, content={"detail": "Ticket not found"})
    
    # Update the ticket fields, we update all the field because we are using PUT method, which is used to update the entire resource. If we were using PATCH method, we would only update the fields that are provided in the request body.
    ticket.title = ticket_update.title
    ticket.priority = ticket_update.priority
    ticket.reported_by = ticket_update.reported_by
    
    # Store the updated ticket back in the "database"
    tickets_db[ticket_id] = ticket #key(ticket_id) = value(ticket)
    return ticket

@app.patch("/tickets/{ticket_id}/resolve", response_model=Ticket, status_code=200)
async def resolve_ticket(ticket_id: int, tickets_db: dict = Depends(get_db)):
    ticket = tickets_db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, content={"detail": "Ticket not found"})
    ticket.is_resolved = True
    tickets_db[ticket_id] = ticket
    return ticket

@app.delete("/tickets/{ticket_id}", status_code=204) #used status_code=204 because I am deleting a resource, and 204 is the status code for successful resource deletion. as we are deleting a resouce, i have not added a response model, as there is no need to return any data when a resource is deleted successfully.
async def delete_ticket(ticket_id: int, tickets_db: dict = Depends(get_db)):
    ticket = tickets_db.get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, content={"detail": "Ticket not found"})
    del tickets_db[ticket_id]
    # return ticket - no use of return as we are deleting a resouce, and our status code is 204, which means no content, so we should not return any content in the response body.
    return

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
