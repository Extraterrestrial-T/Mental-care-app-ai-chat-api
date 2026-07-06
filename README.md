# Mental Care App AI Chat API

Mental Care App AI Chat API is a FastAPI backend for a mental-health appointment and support assistant called CareCoordinator/CeCe. It serves static frontend pages, provides doctor and hospital registration flows, runs an AI chat assistant over WebSockets, and integrates with Firebase, Redis, Gemini, LangGraph, RAG, and Google Calendar.

## Features

- FastAPI app with static HTML pages for login, signup, dashboards, and chat
- WebSocket chatbot endpoint at `/ws/chat`
- LangGraph-based conversation workflow for inquiry, booking, urgent-help, and conversational intents
- Gemini-powered responses through LangChain
- RAG over Corner Health website content
- Redis-backed LangGraph checkpointer and store
- Firebase Authentication and Firestore storage for hospitals, doctors, and appointments
- Hospital registration and dashboard APIs
- Doctor registration, login, dashboard APIs, and calendar connection flow
- Google OAuth flow for connecting doctor calendars
- Google Calendar availability lookup and appointment creation
- Appointment booking from the chatbot flow

## Important Safety Note

This project provides supportive, non-clinical mental-health conversation and appointment scheduling. It is not a replacement for professional care, emergency services, diagnosis, or treatment. Production deployments should include clear crisis escalation copy, human review where appropriate, privacy controls, and local emergency-resource configuration.

## Tech Stack

- Python 3.13
- FastAPI
- WebSockets
- LangGraph
- LangChain
- Google Gemini
- Hugging Face sentence-transformers
- FAISS
- Redis
- Firebase Admin SDK and Firestore
- Firebase Auth
- Google OAuth and Google Calendar API
- Uvicorn

## Project Structure

```text
app/
  app.py                    # Main FastAPI app and WebSocket chat flow
  config.py                 # Application settings
  static/                   # Login, signup, dashboard, and chat pages
  agent/
    agent_core.py           # LangGraph agent, RAG, intent classification
    corpus.txt
  auth/
    auth_routes.py          # Login, session, logout, Google Calendar OAuth
    signup_routes.py        # Hospital and doctor registration
    middleware.py           # Doctor/hospital auth dependencies
  routers/
    doctor_dashboard.py     # Doctor dashboard APIs
    hospital_dashboard.py   # Hospital dashboard APIs
  services/
    calendar_service.py     # Google Calendar operations
    doctor_service.py       # Appointment and doctor workflows
    firebase_auth_service.py
    firebase_service.py     # Firestore operations
  models.py/
    appointment.py
    doctor.py
Dockerfile
migrate_auth.py
requirements.txt
```

## Requirements

- Python 3.13+
- Redis instance
- Firebase project with Firestore enabled
- Firebase service account credentials or Google Application Default Credentials
- Google OAuth client secrets file
- Google Calendar API enabled
- Gemini API credentials available to LangChain

## Environment Variables

Create a `.env` file in the project root:

```env
ENVIRONMENT=development
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:8000

REDIS_URL=redis://localhost:6379/0

FIREBASE_PROJECT_ID=your_firebase_project_id
FIREBASE_DATABASE_ID=auth-tokens-calendar
GOOGLE_APPLICATION_CREDENTIALS=path/to/firebase-service-account.json

GOOGLE_CLIENT_SECRETS_FILE=client_secret.json
GOOGLE_API_KEY=your_gemini_api_key
```

Notes:

- `GOOGLE_API_KEY` is used by LangChain's Google Gemini integration.
- `GOOGLE_CLIENT_SECRETS_FILE` should point to the OAuth client JSON file used for Google Calendar connection.
- `GOOGLE_APPLICATION_CREDENTIALS` is optional if the runtime already has valid Application Default Credentials.
- In production, set `ENVIRONMENT=production`, configure secure HTTPS URLs, and restrict CORS origins.

## Local Setup

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Start Redis locally or set `REDIS_URL` to a hosted Redis instance.

4. Add Firebase and Google OAuth credentials.

5. Start the app:

```powershell
uvicorn app.app:app --reload --ws-ping-interval 10 --ws-ping-timeout 60
```

The app will run at `http://127.0.0.1:8000`.

## Main Pages

| Path | Description |
| --- | --- |
| `/` | Landing/chat entry page |
| `/auth/login` | Login page |
| `/signup/hospital` | Hospital signup page |
| `/signup/doctor` | Doctor signup page |
| `/hospital/dashboard` | Hospital dashboard |
| `/doctor/dashboard` | Doctor dashboard |

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check with agent and Redis status |
| `GET` | `/api/config` | Public frontend configuration |
| `WS` | `/ws/chat` | Patient chatbot and booking workflow |
| `POST` | `/auth/login/email` | Email/password login for doctors or hospitals |
| `GET` | `/auth/calendar/connect` | Start Google Calendar OAuth for a doctor |
| `GET` | `/auth/callback` | Google OAuth callback |
| `GET` | `/auth/session` | Current auth session |
| `POST` | `/auth/logout` | Logout |
| `POST` | `/signup/hospital/register` | Register a hospital |
| `POST` | `/signup/doctor/register` | Register a doctor |
| `GET` | `/doctor/api/dashboard` | Doctor dashboard data |
| `GET` | `/doctor/api/appointments` | Doctor appointments |
| `GET` | `/doctor/api/available-slots` | Doctor availability |
| `PUT` | `/doctor/api/appointments/{appointment_id}/status` | Update appointment status |
| `GET` | `/hospital/api/dashboard` | Hospital dashboard data |
| `GET` | `/hospital/api/doctors` | Hospital doctors |
| `GET` | `/hospital/api/appointments` | Hospital appointments |

## WebSocket Chat Protocol

Connect to:

```text
ws://localhost:8000/ws/chat
```

Example text message:

```json
{
  "query": "I want to book an appointment"
}
```

The server can return:

- `session_id` with the conversation session ID
- `response` with assistant text
- `interrupt` when the agent needs a missing field such as first name, last name, phone number, or email
- `show_doctor_selection` when patient details are collected and the frontend should show available doctors
- `doctors_list` with calendar-connected doctors
- `availability_response` with available appointment slots
- `booking_result` after appointment confirmation
- `error` for failed operations

Example resume message after an interrupt:

```json
{
  "type": "resume",
  "resume_value": "Jane"
}
```

Example doctor list request:

```json
{
  "type": "get_doctors"
}
```

Example availability request:

```json
{
  "type": "get_availability",
  "doctor_id": "doctor_abc123",
  "date": "2026-07-07T00:00:00",
  "duration_minutes": 30
}
```

Example booking confirmation:

```json
{
  "type": "confirm_booking",
  "booking_data": {
    "doctor_id": "doctor_abc123",
    "patient_name": "{'user_Fname': 'Jane'} {'user_Lname': 'Doe'}",
    "patient_email": {"user_email": "jane@example.com"},
    "start_time": "2026-07-07T09:00:00-04:00",
    "end_time": "2026-07-07T09:30:00-04:00",
    "notes": "Booked through CeCe"
  }
}
```

## Google Calendar Setup

1. Enable the Google Calendar API in Google Cloud.
2. Create OAuth client credentials.
3. Save the OAuth JSON file as `client_secret.json` or set `GOOGLE_CLIENT_SECRETS_FILE`.
4. Add this redirect URI to the OAuth client:

```text
http://localhost:8000/auth/callback
```

For production, use your deployed HTTPS callback URL:

```text
https://your-domain.com/auth/callback
```

Doctors connect their calendars through:

```text
/auth/calendar/connect?doctor_id=doctor_id_here
```

## Docker

Build the image:

```powershell
docker build -t mental-care-chat-api .
```

Run the container:

```powershell
docker run --env-file .env -p 8000:8000 mental-care-chat-api
```

## Production Notes

- Replace wildcard CORS with explicit allowed origins.
- Use HTTPS for OAuth redirects and cookies.
- Store service account files and OAuth client secrets outside the repository.
- Review the hard-coded `DEFAULT_HOSPITAL_ID` in `app/app.py` before deployment.
- Configure the crisis-support line and escalation flow for the deployment country.
- Add automated tests for authentication, booking, calendar sync, and WebSocket chat behavior.
- Avoid logging sensitive patient or OAuth token data in production.

## License

No license file is currently included. Add a license before distributing or accepting external contributions.
