"""
Complete Unified Authentication System
Handles both Email/Password (Firebase Auth) and OAuth (Google Calendar)
"""

from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse, FileResponse
from pydantic import BaseModel, EmailStr
from google_auth_oauthlib.flow import Flow
from app.config import settings
from app.services.firebase_service import firebase_service
from app.services.firebase_auth_service import firebase_auth_service
from app.auth.middleware import require_doctor_auth
from urllib.parse import urlencode
import httpx
import os
import time
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/auth", tags=["authentication"])
CALENDAR_OAUTH_STATE_TTL_SECONDS = 600


def _oauth_state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _store_calendar_oauth_state(
    doctor_id: str,
    state: str,
    provider: str,
) -> None:
    saved = await firebase_service.save_doctor_credentials(
        doctor_id,
        {
            "calendar_oauth_state_hash": _oauth_state_hash(state),
            "calendar_oauth_state_provider": provider,
            "calendar_oauth_state_expires_at": datetime.now(timezone.utc)
            + timedelta(seconds=CALENDAR_OAUTH_STATE_TTL_SECONDS),
        },
    )
    if not saved:
        raise HTTPException(status_code=500, detail="Could not start calendar authorization")


async def _verify_calendar_oauth_state(
    doctor_id: str,
    returned_state: str | None,
    provider: str,
) -> dict:
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor account not found")

    expires_at = doctor.get("calendar_oauth_state_expires_at")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    state_is_current = (
        bool(returned_state)
        and doctor.get("calendar_oauth_state_provider") == provider
        and isinstance(expires_at, datetime)
        and expires_at >= datetime.now(timezone.utc)
        and secrets.compare_digest(
            _oauth_state_hash(returned_state),
            doctor.get("calendar_oauth_state_hash") or "",
        )
    )
    if not state_is_current:
        raise HTTPException(
            status_code=400,
            detail="Calendar authorization expired. Return to the dashboard and start linking again.",
        )

    # State is single-use. A failed provider exchange must start a fresh flow.
    await firebase_service.save_doctor_credentials(
        doctor_id,
        {
            "calendar_oauth_state_hash": None,
            "calendar_oauth_state_provider": None,
            "calendar_oauth_state_expires_at": None,
        },
    )
    return doctor


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
async def connect_google_calendar(
    request: Request,
    doctor_id: str = Depends(require_doctor_auth),
):
    """
    Start Google OAuth flow ONLY for calendar connection
    This is SEPARATE from account creation
    Used by existing doctors to link their calendar
    """
    if not settings.IS_PRODUCTION:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Verify doctor exists
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    
    flow = Flow.from_client_secrets_file(
        settings.GOOGLE_CLIENT_SECRETS_FILE,
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=settings.REDIRECT_URI
    )
    
    oauth_state = secrets.token_urlsafe(32)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=oauth_state,
    )
    await _store_calendar_oauth_state(doctor_id, state, "google")
    return RedirectResponse(authorization_url)


@router.get("/callback")
async def google_calendar_callback(
    request: Request,
    doctor_id: str = Depends(require_doctor_auth),
):
    """
    Handle OAuth callback and link calendar to existing doctor
    """
    code = request.query_params.get("code")
    returned_state = request.query_params.get("state")
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    doctor = await _verify_calendar_oauth_state(doctor_id, returned_state, "google")
    
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
        
        # Update doctor with calendar credentials
        calendar_data = {
            "calendar_provider": "google",
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
            "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
            "calendar_connected": True,
            "calendar_status": "connected",
            "calendar_connection_error": None,
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


# ==================== MICROSOFT OAUTH (Outlook Calendar Only) ====================

@router.get("/microsoft/connect")
async def connect_microsoft_calendar(
    request: Request,
    doctor_id: str = Depends(require_doctor_auth),
):
    """
    Start Microsoft OAuth flow for Outlook calendar connection.
    Used by existing doctors to link their Microsoft calendar.
    """
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if not settings.MICROSOFT_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Microsoft OAuth is not configured")

    oauth_state = secrets.token_urlsafe(32)
    await _store_calendar_oauth_state(doctor_id, oauth_state, "microsoft")
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(settings.MICROSOFT_SCOPES),
        "state": oauth_state,
        "prompt": "select_account",
    }
    tenant_id = settings.MICROSOFT_TENANT_ID
    authorization_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?"
        f"{urlencode(params)}"
    )

    return RedirectResponse(authorization_url)


@router.get("/microsoft/callback")
async def microsoft_calendar_callback(
    request: Request,
    doctor_id: str = Depends(require_doctor_auth),
):
    """Handle Microsoft OAuth callback and link Outlook calendar to an existing doctor."""
    code = request.query_params.get("code")
    returned_state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")

    await _verify_calendar_oauth_state(doctor_id, returned_state, "microsoft")

    if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Microsoft OAuth is not configured")

    try:
        tenant_id = settings.MICROSOFT_TENANT_ID
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        token_data = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "scope": " ".join(settings.MICROSOFT_SCOPES),
        }

        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(token_url, data=token_data)
            token_response.raise_for_status()
            tokens = token_response.json()

        calendar_data = {
            "calendar_provider": "microsoft",
            "token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "scopes": tokens.get("scope", "").split(),
            "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
            "calendar_connected": True,
            "calendar_status": "connected",
            "calendar_connection_error": None,
        }

        success = await firebase_service.save_doctor_credentials(doctor_id, calendar_data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save Microsoft calendar credentials")

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
        print(f"Microsoft OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={"error": "Failed to connect Microsoft calendar", "detail": str(e)},
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
