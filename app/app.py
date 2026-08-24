import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from uuid import uuid4
import json
import ast
from datetime import datetime

# Import configuration
from app.config import settings

# Import routers
from app.auth.auth_routes import router as auth_router  # Migrated to unified auth
from app.auth.signup_routes import router as signup_router
from app.routers.doctor_dashboard import router as doctor_router
from app.routers.hospital_dashboard import router as hospital_router

# Import agent
from app.agent.agent_core import get_agent_app

# Import services
from app.services.firebase_service import firebase_service
from app.services.doctor_service import doctor_service

# Global variables
agent_instance = None
agent_resources = None

DEFAULT_HOSPITAL_ID = settings.DEFAULT_HOSPITAL_ID


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global agent_instance, agent_resources
    
    # Startup
    print("🚀 Starting application...")
    agent_instance, agent_resources = await get_agent_app()
    redis_status = "connected" if agent_resources and agent_resources.redis_connected else "not configured"
    print(f"✅ LangGraph Agent compiled; Redis {redis_status}")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")
    if agent_resources:
        await agent_resources.close()
    del agent_instance, agent_resources


app = FastAPI(
    title="CareCoordinator API",
    description="Healthcare appointment scheduling with AI chatbot",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
current_dir = Path(__file__).parent
static_files_dir = current_dir / "static"

if static_files_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_files_dir)), name="static")
    print(f"📁 Static files served from: {static_files_dir}")
else:
    print(f"⚠️ Static directory not found: {static_files_dir}")

# Include routers
app.include_router(auth_router)
app.include_router(signup_router)
app.include_router(doctor_router)
app.include_router(hospital_router)


#==================UTILITY FUCTIONS ===================
def clean_appointment_data(input_dict):
    """Normalize legacy and current booking payload shapes from the static frontend."""
    output = input_dict.copy()

    patient_name = input_dict.get("patient_name")
    if isinstance(patient_name, str) and patient_name.strip().startswith("{"):
        raw_name = patient_name.replace('} {', '}, {')
        name_list = ast.literal_eval(f"[{raw_name}]")
        patient_info = {}
        for d in name_list:
            patient_info.update(d)
        output["patient_name"] = (
            f"{patient_info.get('user_Fname', '')} {patient_info.get('user_Lname', '')}".strip()
        )

    patient_email = input_dict.get("patient_email")
    if isinstance(patient_email, dict):
        output["patient_email"] = patient_email.get("user_email", "")

    return output
# ==================== MAIN ROUTES ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve landing page"""
    try:
        index_path = static_files_dir / "index.html"
        return FileResponse(index_path)
    except FileNotFoundError:
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>CareCoordinator</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            margin: 0;
                            padding: 20px;
                        }
                        .container {
                            background: white;
                            padding: 60px 40px;
                            border-radius: 12px;
                            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                            text-align: center;
                            max-width: 500px;
                        }
                        h1 { color: #333; margin-bottom: 10px; font-size: 32px; }
                        p { color: #666; margin-bottom: 40px; font-size: 16px; }
                        .button-group { display: flex; flex-direction: column; gap: 15px; }
                        a {
                            padding: 16px 32px;
                            border-radius: 8px;
                            text-decoration: none;
                            font-weight: 600;
                            font-size: 16px;
                            transition: all 0.3s;
                            display: block;
                        }
                        .btn-primary { background: #667eea; color: white; }
                        .btn-primary:hover { background: #5568d3; }
                        .btn-secondary { background: white; color: #667eea; border: 2px solid #667eea; }
                        .btn-secondary:hover { background: #f7fafc; }
                        .divider { margin: 30px 0; color: #999; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>🏥 CareCoordinator</h1>
                        <p>Healthcare appointment scheduling made simple</p>
                        <div class="button-group">
                            <a href="/signup/hospital" class="btn-primary">🏥 Register Hospital</a>
                            <a href="/signup/doctor" class="btn-primary">👨‍⚕️ Register as Doctor</a>
                            <div class="divider">— OR —</div>
                            <a href="/auth/login" class="btn-secondary">🔑 Sign In (Existing Users)</a>
                        </div>
                    </div>
                </body>
            </html>
            """,
            status_code=200
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "agent_ready": agent_instance is not None,
        "redis_connected": bool(agent_resources and agent_resources.redis_connected)
    }

# ==================== WEBSOCKET CHAT ====================

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for patient chatbot with booking integration"""
    
    if not agent_instance:
        await websocket.accept()
        await websocket.send_text("Server not ready. Agent compilation failed.")
        await websocket.close()
        return
    
    await websocket.accept()
    
    # Create session
    session_id = str(uuid4())
    config = {"configurable": {"thread_id": session_id}}
    
    # Send session ID to client
    await websocket.send_json({"type": "session_id", "id": session_id})
    
    is_conversation_started = False
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            client_message = json.loads(data)
            
            # ==================== HANDLE BOOKING CONFIRMATION ====================
            if client_message.get("type") == "confirm_booking":
                booking_data = client_message.get("booking_data")
                booking_data = clean_appointment_data(booking_data)
                try:
                    # Get the conversation state to extract full chat history
                    state_snapshot = await agent_instance.aget_state(config)
                    state_values = state_snapshot.values
                    booking_data["patient_name"] = (
                        f"{state_values.get('user_Fname', '')} {state_values.get('user_Lname', '')}"
                    ).strip()
                    booking_data["patient_email"] = state_values.get("user_email", "")
                    booking_data["patient_phone"] = state_values.get("user_phonenumber", "")
                    # Keep sensitive intake details in the application datastore.
                    # Calendar events receive only a minimal scheduling description.
                    conversation_notes = "=== BOOKING INTAKE SUMMARY ===\n"
                    conversation_notes += f"Booked via CeCe chatbot on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n"
                    conversation_notes += f"Age: {state_values.get('user_age', 'Not provided')}\n"
                    conversation_notes += f"Feeling recently: {state_values.get('intake_feeling', 'Not provided')}\n"
                    conversation_notes += f"Support requested: {state_values.get('intake_support_needed', 'Not provided')}\n"
                    conversation_notes += f"Safety check: {state_values.get('intake_safety_check', 'Not provided')}\n"
                    conversation_notes += f"Staff notes: {state_values.get('intake_staff_notes', 'Not provided')}\n"
                    conversation_notes += f"SMS/call consent: {state_values.get('sms_call_consent', 'Not provided')}\n"
                    if booking_data.get("notes"):
                        conversation_notes += f"Additional notes: {booking_data['notes']}\n"
                    
                    # Parse datetime strings
                    start_time = datetime.fromisoformat(booking_data["start_time"].replace('Z', '+00:00'))
                    end_time = datetime.fromisoformat(booking_data["end_time"].replace('Z', '+00:00'))
                    #print(booking_data)
                    # Book the appointment
                    result = await doctor_service.book_appointment(
                        doctor_id=booking_data["doctor_id"],
                        patient_name=booking_data["patient_name"],
                        patient_email=booking_data["patient_email"],
                        patient_phone=booking_data.get("patient_phone"),
                        start_time=start_time,
                        end_time=end_time,
                        notes=conversation_notes,
                        hospital_id=state_values.get("hospital_id"),
                    )

                    if result.get("success"):
                        await agent_instance.aupdate_state(
                            config,
                            {
                                "booking_initiated": False,
                                "booking_completed": True,
                            },
                        )
                    
                    # Send result back to frontend
                    await websocket.send_json({
                        "type": "booking_result",
                        "success": result.get("success", False),
                        "message": result.get("message") if result.get("success") else result.get("error"),
                        "appointment_id": result.get("appointment_id"),
                        "event_id": result.get("event_id")
                    })
                    
                except Exception as e:
                    print(f"Error confirming booking: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "booking_result",
                        "success": False,
                        "message": f"Failed to book appointment: {str(e)}"
                    })
                
                continue
            
            # ==================== HANDLE DOCTOR LIST REQUEST ====================
            if client_message.get("type") == "get_doctors":
                hospital_id = client_message.get("hospital_id") or DEFAULT_HOSPITAL_ID
                print(f"DEBUG: Fetching doctors for hospital: {hospital_id}")  # Debug log
                
                try:
                    available_doctors = await doctor_service.list_bookable_doctors(hospital_id)
                    
                    print(f"DEBUG: Sending {len(available_doctors)} available doctors")  # Debug log
                    
                    await websocket.send_json({
                        "type": "doctors_list",
                        "doctors": available_doctors,
                        "message": f"Found {len(available_doctors)} available doctors"
                    })
                    
                except Exception as e:
                    print(f"Error getting doctors: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Failed to retrieve doctors: {str(e)}"
                    })
                
                continue
            
            # ==================== HANDLE AVAILABILITY REQUEST ====================
            if client_message.get("type") == "get_availability":
                doctor_id = client_message["doctor_id"]
                date_str = client_message["date"]
                duration = client_message.get("duration_minutes", 30)
                
                try:
                    # Parse the date
                    date = datetime.fromisoformat(date_str)
                    
                    # Get available slots
                    availability = await doctor_service.get_available_slots(
                        doctor_id=doctor_id,
                        date=date,
                        duration_minutes=duration
                    )
                    
                    if "error" in availability:
                        await websocket.send_json({
                            "type": "availability_error",
                            "message": availability["error"]
                        })
                    else:
                        await websocket.send_json({
                            "type": "availability_response",
                            "doctor": availability["doctor"],
                            "date": availability["date"],
                            "slots": availability["available_slots"]
                        })
                        
                except Exception as e:
                    print(f"Error getting availability: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send_json({
                        "type": "availability_error",
                        "message": "This calendar is temporarily unavailable. Please select another doctor or try again shortly."
                    })
                
                continue
            
            # ==================== HANDLE AGENT CONVERSATION ====================
            graph_input = {}
            
            if not is_conversation_started:
                # First message
                hospital_id = client_message.get("hospital_id") or DEFAULT_HOSPITAL_ID
                graph_input = {
                    "user_message": client_message["query"],
                    "hospital_id": hospital_id
                }
                is_conversation_started = True
                
            elif client_message.get("type") == "resume":
                # Resuming from interrupt
                from langgraph.types import Command
                resume_value = client_message["resume_value"]
                graph_input = Command(resume=resume_value)
                
            else:
                # Subsequent messages
                graph_input = {"user_message": client_message["query"]}
            
            # Stream agent responses
            async for event in agent_instance.astream(graph_input, config):
                node_name = list(event.keys())[0]
                
                if node_name == "__interrupt__":
                    # Handle interruptions (asking for patient details)
                    interrupt_payload = event[node_name][0].value
                    
                    await websocket.send_json({
                        "type": "interrupt",
                        "request": interrupt_payload["request"],
                        "field": interrupt_payload.get("type"),
                        "metadata": {
                            key: value
                            for key, value in interrupt_payload.items()
                            if key not in {"type", "request", "message"}
                        },
                    })
                    break
                
                elif node_name == "respond":
                    response_data = event['respond']
                    
                    print(f"DEBUG: Respond node data: {response_data}")  # Debug log
                    
                    # Check if booking was initiated
                    if response_data.get('booking_initiated'):
                        print("DEBUG: Booking initiated, triggering doctor selection")  # Debug log
                        
                        # Get patient info from state
                        state_snapshot = await agent_instance.aget_state(config)
                        state_values = state_snapshot.values
                        
                        patient_name = f"{state_values.get('user_Fname', '')} {state_values.get('user_Lname', '')}".strip()
                        patient_email = state_values.get('user_email', '')
                        patient_phone = state_values.get('user_phonenumber', '')
                        
                        # Send response first
                        await websocket.send_json({
                            "type": "response",
                            "text": response_data.get('response', '')
                        })
                        
                        # Then trigger doctor selection UI on frontend with patient info
                        await websocket.send_json({
                            "type": "show_doctor_selection",
                            "message": "Please select a doctor to continue with your booking",
                            "patient_info": {
                                "name": patient_name,
                                "email": patient_email,
                                "phone": patient_phone
                            }
                        })
                        # booking_initiated is an event, not a permanent state. Once
                        # emitted, a later "thanks" must not reopen the doctor picker.
                        await agent_instance.aupdate_state(
                            config,
                            {"booking_initiated": False},
                        )
                    else:
                        # Normal response
                        await websocket.send_json({
                            "type": "response",
                            "text": response_data.get('response', '')
                        })
                
                if node_name == "__end__":
                    await websocket.send_json({"type": "end"})
    
    except WebSocketDisconnect:
        print(f"Client {session_id} disconnected")
    except Exception as e:
        print(f"Error for client {session_id}: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
        await websocket.close()

# ==================== UTILITY ROUTES ====================

@app.get("/api/config")
async def get_config():
    """Get public configuration for frontend"""
    return {
        "environment": settings.ENVIRONMENT,
        "base_url": settings.BASE_URL,
        "default_hospital_id": DEFAULT_HOSPITAL_ID,
        "features": {
            "oauth_enabled": True,
            "chat_enabled": agent_instance is not None,
        }
    }
