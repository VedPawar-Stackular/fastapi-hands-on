from fastapi import FastAPI, HTTPException, Depends
from typing import Annotated, List
# from litellm import BaseModel
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from enum import Enum
from sqlmodel import SQLModel, Field, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from config import settings
from datetime import datetime, timezone

# This is where we are creating an database connection pool. Once the pool is created, we can use it to create sessions/connections to the database from a AsyncSession session that gets created via any route endpoint. The connection pool is created using the create_async_engine function from SQLAlchemy, which takes the database URL from the settings object that we created in config.py. The echo=True parameter is used to log all the SQL statements that are executed, which is useful for debugging purposes.
engine = create_async_engine(settings.database_url, echo=True)


# This is where we are going to create a dependency. When any node tells that the endpoint is getting accessed, that particular endpoint, if it needs access to the database, we declare the dependency in the path parameter, which then calls this particular function here. When this function is hit, the async session part is hit, and it creates and goes to the engine. The engine creates the database connection pool. Once the connection pool is created, from within that connection pool, a session is created, and that session is ended within that endpoint. Now anything happening within that endpoint, a particular piece of database commit, database add, everything gets stored within that session itself, and atomicity is maintained. Once the session is ended, the session is closed, and the connection is returned back to the connection pool. This is how we are maintaining atomicity and isolation in our database operations.
async def get_db():
    async with AsyncSession(engine) as session:
        yield session # The reason this is yield is because once the endpoint, any endpoint that calls this particular database connection gets this connection and is within that session in that particular route it stays there, it yields there until the entire endpoint is completed. Once the entire endpoint is completed all the database operations are hit. Then eventually when that entire endpoint is finished the session or the connection comes back to this function and it's stored and until then this yield session keeps maintaining the connection. If it was a return here, it would have returned the connection and the whole operation would have been finished instantly but at this point everything is maintained within this yield session until and unless the whole endpoint is completely finished executing. 


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

## 1. 4-Class patter for Tickets

# Shared field definition - all the shared fields are defined here, which get inherited by the other classes. This is done to avoid code duplication, and to have a single source of truth for the shared fields.
class TicketBase(SQLModel):
    title: str
    priority: str
    reported_by: str

# This is the input that i get from the client when creating a ticket. It inherits the shared fields from TicketBase, and does not have any additional fields.
class TicketCreate(TicketBase):
    pass

# This is hte output that i send to the client when reading a ticket. It inherits the shared fields from TicketBase, and has an additional field id, which is the unique identifier for the ticket, and is_resolved, which is a boolean indicating whether the ticket is resolved or not.
class TicketRead(TicketBase):
    id: int
    is_resolved: bool

# This is going to be our "database" for the tickets. We inherit the other properties from TicketBase.
class Ticket(TicketBase, table=True):
    id: int = Field(default=None, primary_key=True)
    is_resolved: bool = False

## 2. 4-Class Pattern for Comments

# The shared model for comments, which has the shared fields for comments. This is going to be inherited by the other classes.
class CommentBase(SQLModel):
    content: str

# The comment table, which links to the ticket table via foreign key, hence this is representing a one to many relationship between tickets and comments. Each ticket can have multiple comments, but each comment belongs to a single ticket. The foreign key is defined using the Field function, which specifies the foreign key relationship between the comment and the ticket.
class Comment(CommentBase, table=True):
    id: int = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")
    created_at: str = Field(default=None)  # Assuming you want to include a timestamp for when the comment was created

# Input model for creating a comment. It inherits the shared fields from CommentBase, and does not have any additional fields.
class CommentCreate(CommentBase):
    pass

# Output model for reading a comment. It inherits the shared fields from CommentBase, and has additional fields id, ticket_id, and created_at, which are the unique identifier for the comment, the foreign key to the ticket, and the timestamp for when the comment was created, respectively.
class CommentRead(CommentBase):
    id: int
    ticket_id: int
    created_at: str = Field(default=None)


# We are creating the tables at lifespan. At the start of the application, the lifepsan fn is called, which then goes and calls the engine fn, which makes a connection pool. Eg: here "async with engine.begin() as conn:", this creates a connection pool, no session created yet. Once we call, "await conn.run_sync(SQLModel.metadata.create_all)", this creates all the tables in the database, but i dont know if this is creating a session here first before that? I am confused about this part, but i think it is creating a session here, and then creating the tables in the database. Once the tables are created, the connection is returned back to the connection pool, and the lifespan fn is completed. Now the application is ready to accept requests (is this because the tables are created?, it should be this only right, because the connected pool connectinoi is closed and the session is also closed, so how else will the application be ready to accept requests?), and any endpoint that needs access to the database will call the get_db fn, which will create a session from the connection pool, and once the endpoint is completed, the session is closed and returned back to the connection pool.
@asynccontextmanager
async def lifespan(app: FastAPI):
    #creating the database table.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all) # create_all checks what tables exist and creates any that are missing. It won't drop and recreate — it only adds new tables. This is useful for ensuring that your database schema is up to date without losing existing data.
    yield

# i dont know again what this does, but this is what the format is, so i added this
#ans: create the app once, passing the lifespan. 
app = FastAPI(lifespan=lifespan)

# For every route, when a database connectio is needed for that route session, we add this sessiondep into the path parameter of that route, which then gets called here via dependency injection, and then the session is created from the connection pool, and once the endpoint is completed, the session is closed and returned back to the connection pool. This is how we are maintaining atomicity and isolation in our database operations.
SessionDep = Annotated[AsyncSession, Depends(get_db)] # this is a type hint for the session dependency. It tells FastAPI that the session parameter is of type AsyncSession, and that it should be provided by the get_db dependency. This is useful for type checking and for generating OpenAPI documentation.

#health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# in the post route below, where is the SQL connection begin made exactly, is what i am not understanding. Is it when db.add(ticket) is called, or when db.commit() is called? I think it is when db.commit() is called, because that is when the changes are actually sent to the database? But then what is happening when i do db.add(ticket)? is it just keeping it in python memeory? if yes, why? i need that to be understood exactly. 
@app.post("/tickets/", response_model=TicketRead, status_code=201)
async def create_ticket(ticket_in: TicketCreate, db: SessionDep): # I was getting confused on how to use the Depends fn. I am confused with the syntax. I researched and found that the Depends fn is used to declare a dependency for a path operation function. The syntax is Depends(dependency), where dependency is a callable that returns the value to be injected. In this case, we are using the get_db fn as the dependency, which returns an AsyncSession object. The SessionDep type hint is used to specify that the db parameter is of type AsyncSession, and that it should be provided by the get_db dependency. This allows us to use the db parameter in the create_ticket fn to interact with the database.
    ticket=Ticket(
        title=ticket_in.title,
        priority=ticket_in.priority,
        reported_by=ticket_in.reported_by
    ) # I assume we are creating a new ticket object here, and add the clinet input values into this object.
    db.add(ticket) # We are adding the ticket object to the database session. The database has not yet seen any changes nor any addition. This is still in the python memory.
    await db.commit() # This is where the data from ticket object is sent to the database, which includes all the database additons at once, and if any one fails here or before this, the entire session db changes would have been rolled back, and had not been sent.
    await db.refresh(ticket) # This does the opposite of above code, it gets the fresh database info back to the python memory, i think, on whihc we can perform more database operattion later in antoher session when made. 
    return ticket


# based on the the logic for this endpoint, we dotn have to make any changes to the database, we make a session, if both priority and is_resolved are None, we return all the tickets as is from the database, if either of them is not None, we filter the tickets based on the input values, and return the filtered tickets as a response. We dont have to make any changes to the database, we just have to filter the data and return it as a response. So we can create a new list of ticket objects that have the priority and/or is_resolved given in the input, and then return that list as a response. We can do this by creating a new list of ticket objects, and then appending the ticket objects that have the priority and/or is_resolved given in the input to that list. Then we can return that list as a response. so there is no use of using any DB queries here? Then what happens to the session that we created, does that automatically get closed when this endpoint is completed, or do we have to close it manually? I think it automatically gets closed when this endpoint is completed, because we are using the Depends fn to create the session, and the Depends fn automatically closes the session when the endpoint is completed.
@app.get("/tickets/", response_model=List[TicketRead], status_code=200) 
async def read_tickets(
    db: SessionDep,
    priority: str = None,
    is_resolved: bool = None,
):
    
    if priority is None and is_resolved is None:
        # if no filters are provided, return the all tickets as is
        result = await db.exec(select(Ticket))
        if not result:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket = result.all()
        #this is the query to get all the tickets from the database, and then we return it as a list of TicketRead objects. The select(Ticket) is the SQL query being performed by SQL Model on the PostgreSQL database. the .exec() method is used to execute the query, which returns a list of tuples of all the rows of the database,and the .all() method is used to convert that tuple into TicketRead objects. Then we return that list of TicketRead objects as the response to the client.
        return ticket 
    
    ticket = await db.get(select(Ticket))
    result = ticket.all()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if priority is not None and is_resolved is None:
        # we only filter by priority, so we need to get all those rows in the database that have priority given in theinput, and then somehow store them. We dont have to make any changes to the database, we just need to filter the data and return it as a response. 
        res = await db.exec(select(Ticket).where(Ticket.priority == priority)) # I am confused in this endpoint. This is my current understanding. So, for this particular endpoint, for the first condition above that I showed you, if there is no priority nor is resolved given, we can just directly select all the rows in the database and return them. In these conditions below, where either priority or is resolved is given and the other is not given, we will have to filter it within the database. Now, the command to filter it within the database is given here, but I am getting confused in this intention. Also, how are we going to filter it in one go? I assumed there is not going to be any for loops attached here, because we can directly use the SQL to do the whole looping for us. There is no external for loop attached in this Python code, but I am getting confused with how to just intact something in the SQL state right now. Maybe my brain is just clogged, but I am assuming I am getting confused with how to use this ticket not property thing, because there is no ticket object that we have here. Please let me explain this. My brain is just not training here. Similarly, for the other ones, once I get this particular logic, I can implement it in the other two if statements as well. 
    if priority is None and is_resolved is not None:
        # we only filter by is_resolved
        if t.is_resolved == is_resolved:
            filtered_ticket.append(t)
    # if both the parameters are provided, we filter by both
    if priority is not None and is_resolved is not None:
        if t.priority == priority and t.is_resolved == is_resolved:
            filtered_ticket.append(t)
        

    return list(filtered_ticket)


# In this particular endpoint, the GET path is just getting all the ticket-related information from a particular ticket ID. I just connected to the dependency to the database. I get the database connection pool set up for this particular session, and once this session is started in this particular endpoint, I create a ticket object which asynchronously gets the ticket information via the ticket ID from the database. I have a condition where the ticket object exists or not. If it doesn't, it shows me an error, and if it does exist, it returns that particular ticket. 
@app.get("/tickets/{ticket_id}", response_model=Ticket)
async def read_all_tickets(ticket_id: int, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket
    

@app.put("/tickets/{ticket_id}", response_model=Ticket)
async def update_ticket(ticket_id: int, ticket_update: TicketCreate, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.title = ticket_update.title
    ticket.priority = ticket_update.priority
    ticket.reported_by = ticket_update.reported_by
    
    # Store the updated ticket back in the "database". Because we are now updating something in the database by putting it into the database from this endpoint in this session, after all the properties for that particular ticket object are updated, we now commit it to the database. Once it's committed, all the DB operations that happened, all the DB-related operations that happened within the session, get committed all together at once. If either one failed, the whole commit would not work and it would roll back. Once it has been committed, then we go to `db.refresh`, which eventually fetches the updated data from the database to get a fresh database into this particular session, and then at the end we return that ticket value. 
    await db.commit()
    await db.refresh(ticket)
    return ticket

@app.patch("/tickets/{ticket_id}/resolve", response_model=Ticket, status_code=200)
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


## Comment endpoints
@app.post("/tickets/{ticket_id}/comments/", response_model=CommentRead, status_code=201)
async def create_comment(ticket_id: int, comment_in: CommentCreate, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    comment = Comment(
        content=comment_in.content,
        ticket_id=ticket_id,
        created_at=datetime.now(timezone.utc).isoformat() #Field is typed str in your Comment model, so .isoformat() converts datetime → string ("2026-07-03T18:26:00+00:00"). I read that it is better to set this created_at at field level: created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)), so that every insert gets stamped automatically without remembering to set it manually each time.
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@app.get("/tickets/{ticket_id}/comments/", response_model=List[CommentRead], status_code=200)
async def read_comments(ticket_id: int, db: SessionDep):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    result = await db.exec(select(Comment).where(Comment.ticket_id == ticket_id)) #So, here, as the comments table has a foreign key of the ticket's ID in its table, we can end this relationship as a one-to-many relationship, where one ticket can have multiple comments, whereas one comment can only have one ticket. To get all the comments from a particular ticket, we can use this SQL statement as shown, where we use that particular ticket ID within the comments table to eventually filter out all the particular comments that were part of the same ticket and eventually return all the comments. 
    comments = result.all()
    return comments


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# Some questions answered that i might have not asnswerd above, that you asked:
# 1. table=True — what does this keyword actually do, and what happens to a SQLModel class that doesn't have it?
# As far as I know, `table = True` is set for those models which need to be converted to a SQL table within the PostgreSQL database. Once that is set, it converts that to a real database with proper columns, rows, and everything. The SQL model class that does not have it will be eventually treated as a pydantic model and not as a table. 

# 2. yield in get_db — you used return in the dict version. Why does the DB version use yield? What happens after the yield?
# So yield is basically a piece of code where, once you reach there, the entire application is running on that particular piece of code until the application stops. The yield execution is done, and then the code goes to the next line, which is whatever the shutdown part of the code is there, or any other part of the code is there. Yield is that part of the core that the application runs, and we put that in the getdb function because once we assign a session into any endpoint, until and unless the entire endpoint is working, all the database connections are happening and the entire endpoint is being executed. The yield within the database is still running. Once the endpoint is computed and the database connection is gone from the connection pool, the thing comes back to the yield and then goes to the next step below yield. yield is that sort of hook that keeps the entire thing running until the application is shut down. 

# 3. session.refresh(ticket) — why call this after commit()? What state is the object in before refresh?
# Once we commit the changes that we made in that particular session, all the changes together go to the database. If either one of the changes fails, the entire session database changes fail and it's rolled back, but because they are in the same session, they eventually go together and hit the database. Once the database operations are done, the database is updated externally. Now, to get that updated database back into the current Python memory, we use `session.refresh`, which eventually gets that updated part. Now, after the session is completed, we have the updated database as well. 

# 4. echo=True on the engine — what is it printing and why is it useful?
# Echo is equal to true, which is basically storing all the SQL commands that we are executing. It stores it and keeps it in memory so that we can use it for debugging any time that we need. We can know what errors we have made because we have an entire list of the previous SQL commands. 

# 5. select(Ticket).where(...) vs session.get(Ticket, ticket_id) — these both fetch from the DB, but they're different tools.When would you use one vs the other?
# Yes, they both fetch from the database, and they both can't fetch the same thing. It depends on the `var` condition, but what `var` provides is additional filtering of the rows from the database. We can filter it based on whatever we want. The `session.get` gets us all the rows of the database through the primary key of that particular database, but we cannot filter in this particular part. We use one to filter, and the other to get all those based on the primary key. 



