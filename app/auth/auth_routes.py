"""
Complete Unified Authentication System
Handles both Email/Password (Firebase Auth) and OAuth (Google Calendar)
"""

from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel, EmailStr
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from app.config import settings
from app.services.firebase_service import firebase_service
from app.services.firebase_auth_service import firebase_auth_service
from typing import Optional
import os

router = APIRouter(prefix="/auth", tags=["authentication"])


# ==================== MODELS ====================

class EmailPasswordLogin(BaseModel):
    """Email/password login"""
    email: EmailStr
    password: str
    account_type: str  # "doctor" or "hospital"


# ==================== EMAIL/PASSWORD LOGIN ====================

@router.post("/login/email")
async def login_with_email_password(credentials: EmailPasswordLogin, response: Response):
    """
    Login with email/password - Works for both doctors and hospitals
    Does NOT require OAuth - purely email/password based
    """
    try:
        # Get user from Firebase Auth by email
        user_auth = await firebase_auth_service.get_user_by_email(credentials.email)
        
        if not user_auth:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Construct the expected ID format
        if credentials.account_type == "hospital":
            user_id = f"hospital_{user_auth['uid']}"
            data = await firebase_service.get_hospital(user_id)
            
            if not data:
                raise HTTPException(status_code=401, detail="Hospital account not found")
            
            redirect_url = "/hospital/dashboard"
            user_info = {
                "id": user_id,
                "name": data.get("name"),
                "email": data.get("email"),
                "type": "hospital"
            }
            
        elif credentials.account_type == "doctor":
            user_id = f"doctor_{user_auth['uid']}"
            data = await firebase_service.get_doctor(user_id)
            
            if not data:
                raise HTTPException(status_code=401, detail="Doctor account not found")
            
            redirect_url = "/doctor/dashboard"
            user_info = {
                "id": user_id,
                "name": data.get("name"),
                "email": data.get("email"),
                "type": "doctor"
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid account type")
        
        # Set session cookie
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=user_id,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.IS_PRODUCTION
        )
        
        return {
            "success": True,
            "user_type": credentials.account_type,
            "redirect_url": redirect_url,
            "user": user_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== GOOGLE OAUTH (Calendar Only) ====================

@router.get("/calendar/connect")
async def connect_google_calendar(request: Request):
    """
    Start Google OAuth flow ONLY for calendar connection
    This is SEPARATE from account creation
    Used by existing doctors to link their calendar
    """
    if not settings.IS_PRODUCTION:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Get doctor_id from query params (must be an existing doctor)
    doctor_id = request.query_params.get("doctor_id")
    
    if not doctor_id:
        raise HTTPException(
            status_code=400, 
            detail="doctor_id is required to connect calendar"
        )
    
    # Verify doctor exists
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    flow = Flow.from_client_secrets_file(
        settings.GOOGLE_CLIENT_SECRETS_FILE,
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=settings.REDIRECT_URI
    )
    
    # Pass doctor_id in state
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=doctor_id  # Simple - just the doctor_id
    )
    
    return RedirectResponse(authorization_url)


@router.get("/callback")
async def google_calendar_callback(request: Request):
    """
    Handle OAuth callback and link calendar to existing doctor
    """
    code = request.query_params.get("code")
    doctor_id = request.query_params.get("state")  # This is the doctor_id we passed
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    if not doctor_id:
        raise HTTPException(
            status_code=400, 
            detail="Missing doctor identification for account linking"
        )
    
    try:
        if not settings.IS_PRODUCTION:
            os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
        
        flow = Flow.from_client_secrets_file(
            settings.GOOGLE_CLIENT_SECRETS_FILE,
            scopes=settings.GOOGLE_SCOPES,
            redirect_uri=settings.REDIRECT_URI
        )
        
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Verify doctor still exists
        doctor = await firebase_service.get_doctor(doctor_id)
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor account not found")
        
        # Update doctor with calendar credentials
        calendar_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "calendar_connected": True
        }
        
        success = await firebase_service.save_doctor_credentials(doctor_id, calendar_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save calendar credentials")
        
        # Redirect to dashboard with success message
        response = RedirectResponse(url=f"{settings.FRONTEND_URL}/doctor/dashboard?calendar=connected")
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=doctor_id,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.IS_PRODUCTION
        )
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={"error": "Failed to connect calendar", "detail": str(e)},
            status_code=500
        )


# ==================== SESSION & LOGOUT ====================

@router.get("/session")
async def get_session(request: Request):
    """Check if user is authenticated"""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if not session_id:
        return {"authenticated": False}
    
    # Check doctor
    if session_id.startswith("doctor_"):
        doctor = await firebase_service.get_doctor(session_id)
        if doctor:
            return {
                "authenticated": True,
                "user_type": "doctor",
                "user": {
                    "id": session_id,
                    "name": doctor.get("name"),
                    "email": doctor.get("email"),
                    "calendar_connected": doctor.get("calendar_connected", False)
                }
            }
    
    # Check hospital
    if session_id.startswith("hospital_"):
        hospital = await firebase_service.get_hospital(session_id)
        if hospital:
            return {
                "authenticated": True,
                "user_type": "hospital",
                "user": {
                    "id": session_id,
                    "name": hospital.get("name"),
                    "email": hospital.get("email")
                }
            }
    
    return {"authenticated": False}


@router.post("/logout")
async def logout(response: Response):
    """Logout user"""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.IS_PRODUCTION
    )
    return {"success": True, "message": "Logged out successfully"}


@router.get("/logout")
async def logout_get(response: Response):
    """Logout via GET"""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.IS_PRODUCTION
    )
    return RedirectResponse(url="/")


# ==================== LOGIN PAGE ====================

@router.get("/login", response_class=HTMLResponse)
async def login_page():

    """Unified login page for both doctors and hospitals"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    login_path = os.path.join(static_dir, "login.html")
    return FileResponse(login_path)