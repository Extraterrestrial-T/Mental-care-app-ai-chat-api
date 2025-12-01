import os
from pathlib import Path
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from langgraph.types import Command
from uuid import uuid4
from langgraph.types import Command
import json
import asyncio

# Assuming 'agent.py' is in the same directory/package and contains get_agent_app
from app.agent.agent_core import get_agent_app



agent_instance = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Compiles the agent and connects to Redis ONCE."""
    global agent_instance, redis_client
    agent_instance, redis_client = await get_agent_app()
    print("LangGraph Agent compiled and Redis connection established.")
    yield
    del(agent_instance, redis_client)

app = FastAPI(lifespan=lifespan)

# CORS Middleware Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
#
# --- Static File Serving ---
# Mount the static directory to serve index.html, JS, CSS, etc.
# Note: Render often needs this folder to be relative to the deployment root.

BASE_DIR = Path(__file__).parent.parent  # Goes up to /app
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Serve the index.html content at the root URL (/)
@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serves the chat client HTML page."""
    try:
        with open(os.path.join("static", "index.html"), "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Chat Client HTML Not Found!</h1>", status_code=404)


# --- 2. THE CORRECTED ASYNC WEBSOCKET HANDLER ---

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    # Check if the agent is ready before accepting connections
    if not agent_instance:
        await websocket.accept()
        await websocket.send_text("Server not ready. Agent compilation failed.")
        await websocket.close()
        return

    await websocket.accept()
    
    # 1. Session Setup: UUID is the key to LangGraph memory
    # Using the thread_id as the unique session ID
    session_id = str(uuid4())
    config = {"configurable": {"thread_id": session_id}}
    
    # Send the session ID to the client for reconnection/debugging
    await websocket.send_json({"type": "session_id", "id": session_id})

    # State tracking for the current conversation
    is_conversation_started = False

    try:
        while True:
            # Await the next message from the client (Text or JSON for resume)
            data = await websocket.receive_text()
            client_message = json.loads(data)
            
            # This will hold the input for astream
            graph_input = {} 
            
            # --- Input Handling Logic ---
            if not is_conversation_started:
                # 2. First Message: Initial state is merged with the first query
                # IMPORTANT: We only pass 'user_message' and let the 'read_request' node
                # add it to the 'messages' history list.
                graph_input = {"user_message": client_message["query"]} 
                is_conversation_started = True
                
            elif client_message.get("type") == "resume":
                # 3. Resuming from Interrupt
                resume_value = client_message["resume_value"]
                # We wrap the resume value in the LangGraph Command structure
                graph_input = Command(resume=resume_value)
                
            else:
                # 4. Subsequent Message: Normal turn update
                graph_input = {"user_message": client_message["query"]}
            
            # --- Graph Execution and Streaming ---
            # KEY CHANGE: Use the global agent_instance and the .astream method
            async for event in agent_instance.astream(graph_input, config): 
                
                # LangGraph streams events as single-key dictionaries
                node_name = list(event.keys())[0]
                
                if node_name == "__interrupt__":
                    # The value contains the interruption details requested by the book_appointment node
                    interrupt_payload = event[node_name][0].value
                    
                    await websocket.send_json({
                        "type": "interrupt",
                        "request": interrupt_payload["request"],
                        "field": interrupt_payload.get("type") # Use "type" from your interrupt payload
                    })
                    # Exit the streaming loop and wait for client to send a "resume" message
                    break 
                
                # Check for the final output from the respond node
                if node_name == "respond" and 'response' in event['respond']:
                    # Send the final AI response for this turn
                    await websocket.send_json({
                        "type": "response",
                        "text": event['respond']['response']
                    })
                
                if node_name == "__end__":
                    # The conversation reached END (e.g., after a successful booking)
                    await websocket.send_json({"type": "end"})
                    # If you want the session to terminate after END, uncomment the next line:
                    # break 
                    
    except WebSocketDisconnect:
        # Client disconnected, state is saved in Redis automatically via AsyncRedisSaver
        print(f"Client {session_id} disconnected.")
    except Exception as e:
        print(f"Error for client {session_id}: {e}")
        await websocket.send_text(f"An unexpected error occurred: {e}")
        # Close the connection upon a major error
        await websocket.close()