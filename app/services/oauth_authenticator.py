import os
import json
import datetime
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. FIREBASE SETUP ---
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault() 
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- 2. CONFIGURATION ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # REMOVE THIS IN PRODUCTION (Use '0')
CLIENT_SECRETS_FILE = "client_secret.json" 
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events", 
    "https://www.googleapis.com/auth/userinfo.email", 
    "https://www.googleapis.com/auth/userinfo.profile", 
    "openid",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.settings.readonly",
    "https://www.googleapis.com/auth/calendar.addons.current.event.write",
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.events.owned.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
]
# Ensure this matches your Google Console exactly
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://carecoordinator.org/auth/callback")

auth_router = APIRouter(prefix="/auth")

@auth_router.get("/login")
async def login(request: Request):
    """
    Step 1: Redirect doctor to Google.
    access_type='offline' is CRITICAL for the 6-month+ lifespan.
    """
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent' 
    )
    
    return RedirectResponse(authorization_url)


@auth_router.get("/callback")
async def callback(request: Request):
    """
    Step 2: Handle return, link calendar, and SET LONG-LIVED SESSION.
    """
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")

    try:
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Get User Profile
        from googleapiclient.discovery import build
        service = build('oauth2', 'v2', credentials=creds)
        user_info = service.userinfo().get().execute()
        
        doctor_id = user_info['id']
        doctor_email = user_info['email']
        doctor_name = user_info.get('name', 'Unknown Doctor')
        doctor_pic = user_info.get('picture', '')

        # --- 3. STORE CREDENTIALS (BACKEND LINK) ---
        doctor_data = {
            "name": doctor_name,
            "email": doctor_email,
            "profile_pic": doctor_pic,
            # We store the token data to recreate the Credentials object later
            "token": creds.token,
            "refresh_token": creds.refresh_token, 
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "linked_at": firestore.SERVER_TIMESTAMP
        }

        # Save to Firestore 'doctors' collection
        db.collection("doctors").document(doctor_id).set(doctor_data, merge=True)

        # --- 4. SET SESSION COOKIE (FRONTEND LINK) ---
        # Create a Redirect or JSON response
        # We redirect them to a dashboard or success page on your frontend
        response = RedirectResponse(url="https://carecoordinator.org/dashboard")
        
      
        MAX_AGE = 15552000
        
        # Set a secure, HttpOnly cookie containing the doctor's ID
        # In a real production app, this should be a signed JWT to prevent tampering
        #TODO Change cookie to JWT
        response.set_cookie(
            key="cece_doctor_session",
            value=doctor_id, 
            max_age=MAX_AGE,
            httponly=True,   # JavaScript cannot read this (security)
            samesite="lax",  # Allows the cookie to be sent on top-level navigations
            secure=True      # Only send over HTTPS
        )

        return response

    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)