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
    email: EmailStr
    password: str
    account_type: str  # "doctor" or "hospital"

class TokenVerification(BaseModel):
    id_token: str
    account_type: str

# ==================== EMAIL/PASSWORD AUTHENTICATION ====================

@router.post("/login/email")
async def login_with_email_password(credentials: EmailPasswordLogin, response: Response):
    """
    Login with email and password (Firebase Auth)
    This is separate from OAuth - used for hospital admins primarily
    """
    try:
        # In a real implementation, you would verify the password with Firebase
        # For now, we'll just check if the user exists
        
        if credentials.account_type == "hospital":
            hospital = await firebase_service.get_hospital_by_email(credentials.email)
            if not hospital:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            
            # Set session cookie
            response.set_cookie(
                key=settings.SESSION_COOKIE_NAME,
                value=hospital["id"],
                max_age=settings.SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=settings.IS_PRODUCTION
            )
            
            return {
                "success": True,
                "user_type": "hospital",
                "redirect_url": "/hospital/dashboard",
                "user": {
                    "id": hospital["id"],
                    "name": hospital["name"],
                    "email": hospital["email"]
                }
            }
            
        elif credentials.account_type == "doctor":
            doctor = await firebase_service.get_doctor_by_email(credentials.email)
            if not doctor:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            
            # Set session cookie
            response.set_cookie(
                key=settings.SESSION_COOKIE_NAME,
                value=doctor["id"],
                max_age=settings.SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=settings.IS_PRODUCTION
            )
            
            return {
                "success": True,
                "user_type": "doctor",
                "redirect_url": "/doctor/dashboard",
                "user": {
                    "id": doctor.get("id"),
                    "name": doctor["name"],
                    "email": doctor["email"]
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid account type")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify-token")
async def verify_firebase_token(token_data: TokenVerification, response: Response):
    """
    Verify Firebase ID token from client-side Firebase Auth
    Used when frontend uses Firebase SDK for authentication
    """
    try:
        user_data = await firebase_auth_service.verify_custom_token(token_data.id_token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Verify account type matches
        if user_data["type"] != token_data.account_type:
            raise HTTPException(
                status_code=403, 
                detail=f"Account type mismatch. This is a {user_data['type']} account."
            )
        
        # Set session cookie
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=user_data["id"],
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.IS_PRODUCTION
        )
        
        return {
            "success": True,
            "user": user_data,
            "redirect_url": f"/{user_data['type']}/dashboard"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

# ==================== GOOGLE OAUTH (for Calendar) ====================

@router.get("/login")
async def oauth_login(request: Request):
    """
    Initiate Google OAuth flow for calendar access
    Used by doctors to connect their Google Calendar
    """
    if not settings.IS_PRODUCTION:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    flow = Flow.from_client_secrets_file(
        settings.GOOGLE_CLIENT_SECRETS_FILE,
        scopes=settings.GOOGLE_SCOPES,
        redirect_uri=settings.REDIRECT_URI
    )
    
    # Extract params from signup flow
    hospital_id = request.query_params.get("hospital_id")
    temp_id = request.query_params.get("temp_id")
    
    # Pass data through state parameter
    custom_state = f"{hospital_id or 'none'}|{temp_id or 'none'}"

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=custom_state
    )
    
    return RedirectResponse(authorization_url)

@router.get("/oauth/callback")
async def oauth_callback(request: Request):
    """
    Handle Google OAuth callback
    Complete doctor registration with calendar access
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")
    
    # Parse custom state
    hospital_id = None
    temp_id = None
    if state and "|" in state:
        h_id, t_id = state.split("|")
        hospital_id = h_id if h_id != 'none' else None
        temp_id = t_id if t_id != 'none' else None

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
        
        # Get user info from Google
        oauth_service = build('oauth2', 'v2', credentials=creds)
        user_info = oauth_service.userinfo().get().execute()
        
        # Generate doctor ID from Google ID
        doctor_id = f"doctor_{user_info['id']}"
        
        # Prepare doctor data
        doctor_data = {
            "name": user_info.get('name', 'Unknown'),
            "email": user_info['email'],
            "profile_pic": user_info.get('picture', ''),
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
        
        # If coming from signup, merge with temp data
        if temp_id:
            temp_data = await firebase_service.get_doctor(temp_id)
            if temp_data:
                doctor_data.update({
                    "specialty": temp_data.get("specialty"),
                    "hospital_id": temp_data.get("hospital_id"),
                })
                # Delete temp record
                # Note: You'd need to implement delete_doctor in firebase_service
        
        # Use hospital_id from state if available
        if hospital_id:
            doctor_data["hospital_id"] = hospital_id
        
        # Save doctor credentials
        success = await firebase_service.save_doctor_credentials(doctor_id, doctor_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save credentials")
        
        # Create response with redirect
        response = RedirectResponse(url=f"{settings.FRONTEND_URL}/doctor/dashboard")
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value=doctor_id,
            max_age=settings.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.IS_PRODUCTION
        )
        return response
        
    except Exception as e:
        print(f"OAuth callback error: {e}")
        return JSONResponse(
            content={"error": "Authentication failed", "detail": str(e)},
            status_code=500
        )

# ==================== LOGOUT ====================

@router.post("/logout")
async def logout(response: Response):
    """Logout user by clearing session cookie"""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.IS_PRODUCTION
    )
    return {"success": True, "message": "Logged out successfully"}

@router.get("/logout")
async def logout_get(response: Response):
    """Logout via GET (for direct links)"""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.IS_PRODUCTION
    )
    return RedirectResponse(url="/")

# ==================== SESSION MANAGEMENT ====================

@router.get("/session")
async def get_session(request: Request):
    """Get current session info"""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if not session_id:
        return {"authenticated": False}
    
    # Check if it's a doctor
    doctor = await firebase_service.get_doctor(session_id)
    if doctor:
        return {
            "authenticated": True,
            "user_type": "doctor",
            "user": {
                "id": session_id,
                "name": doctor.get("name"),
                "email": doctor.get("email"),
                "calendar_connected": bool(doctor.get("refresh_token"))
            }
        }
    
    # Check if it's a hospital
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
    
    # Invalid session
    return {"authenticated": False}

# ==================== LOGIN PAGE ====================

@router.get("/login/page", response_class=HTMLResponse)
async def login_page():
    """Serve login page"""
    try:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        login_path = os.path.join(static_dir, "login.html")
        
        if os.path.exists(login_path):
            return FileResponse(login_path)
        else:
            # Return inline login page if file doesn't exist
            return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login - CareCoordinator</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            max-width: 400px;
            width: 100%;
        }
        h1 { color: #333; margin-bottom: 30px; text-align: center; }
        input, select {
            width: 100%;
            padding: 12px;
            margin-bottom: 15px;
            border: 1px solid #ddd;
            border-radius: 8px;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
        }
        button:hover { background: #5568d3; }
        .error {
            background: #fed7d7;
            color: #742a2a;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏥 Sign In</h1>
        <div id="error" class="error"></div>
        <form id="loginForm">
            <select name="account_type" required>
                <option value="doctor">Doctor</option>
                <option value="hospital">Hospital Admin</option>
            </select>
            <input type="email" name="email" placeholder="Email" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Sign In</button>
        </form>
        <p style="text-align: center; margin-top: 20px;">
            <a href="/signup/hospital" style="color: #667eea;">Register Hospital</a> | 
            <a href="/signup/doctor" style="color: #667eea;">Register Doctor</a>
        </p>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                const response = await fetch('/auth/login/email', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    window.location.href = result.redirect_url;
                } else {
                    document.getElementById('error').textContent = result.detail || 'Login failed';
                    document.getElementById('error').style.display = 'block';
                }
            } catch (error) {
                document.getElementById('error').textContent = 'Network error';
                document.getElementById('error').style.display = 'block';
            }
        });
    </script>
</body>
</html>
            """)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading login page: {e}</h1>", status_code=500)