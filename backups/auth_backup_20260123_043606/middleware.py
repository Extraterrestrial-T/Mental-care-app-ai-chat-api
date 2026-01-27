from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from typing import Optional
from app.config import settings
from app.services.firebase_service import firebase_service


async def get_current_user(request: Request) -> Optional[dict]:
    """
    Get current authenticated user (doctor or hospital) from session cookie
    
    Returns:
        Dict with user info if authenticated, None otherwise
    """
    user_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if not user_id:
        return None
    
    # Check if it's a doctor
    if user_id.startswith("doctor_"):
        doctor = await firebase_service.get_doctor(user_id)
        if doctor:
            return {
                "type": "doctor",
                "id": user_id,
                "data": doctor
            }
    
    # Check if it's a hospital
    if user_id.startswith("hospital_"):
        hospital = await firebase_service.get_hospital(user_id)
        if hospital:
            return {
                "type": "hospital",
                "id": user_id,
                "data": hospital
            }
    
    return None


async def get_current_doctor(request: Request) -> Optional[str]:
    """
    Get current authenticated doctor ID from session cookie
    
    Returns:
        Doctor ID if authenticated, None otherwise
    """
    user = await get_current_user(request)
    
    if user and user["type"] == "doctor":
        return user["id"]
    
    return None


async def require_doctor_auth(request: Request) -> str:
    """
    Dependency that requires doctor authentication
    
    Raises:
        HTTPException: If not authenticated or not a doctor
        
    Returns:
        Doctor ID
    """
    doctor_id = await get_current_doctor(request)
    
    if not doctor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated as a doctor"
        )
    
    # Verify doctor exists in Firestore
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session"
        )
    
    return doctor_id


async def require_hospital_auth(request: Request) -> str:
    """
    Dependency that requires hospital admin authentication
    
    Raises:
        HTTPException: If not authenticated or not a hospital admin
        
    Returns:
        Hospital ID
    """
    user = await get_current_user(request)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # If user is a hospital admin, return hospital ID
    if user["type"] == "hospital":
        return user["id"]
    
    # If user is a doctor, check if they have hospital_id (for now)
    # TODO: In production, implement proper RBAC with admin roles
    if user["type"] == "doctor":
        doctor = user["data"]
        hospital_id = doctor.get("hospital_id")
        
        if not hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No hospital associated with this account"
            )
        
        # Verify hospital exists
        hospital = await firebase_service.get_hospital(hospital_id)
        if not hospital:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hospital not found"
            )
        
        return hospital_id
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access hospital data"
    )


async def require_auth(request: Request) -> dict:
    """
    Dependency that requires any authentication (doctor or hospital)
    
    Raises:
        HTTPException: If not authenticated
        
    Returns:
        User dict with type and id
    """
    user = await get_current_user(request)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    return user


async def optional_auth(request: Request) -> Optional[dict]:
    """
    Dependency that allows optional authentication
    Returns user info if authenticated, None otherwise
    
    Returns:
        User dict or None
    """
    return await get_current_user(request)


# Middleware for protecting routes
async def auth_middleware(request: Request, call_next):
    """
    Global authentication middleware
    Can be used to protect all routes or specific path patterns
    """
    path = request.url.path
    
    # Public paths that don't require authentication
    public_paths = [
        "/",
        "/auth/login",
        "/auth/login/page",
        "/auth/login/email",
        "/auth/oauth/callback",
        "/signup",
        "/health",
        "/docs",
        "/openapi.json",
        "/static",
        "/ws/chat"  # WebSocket chat is public
    ]
    
    # Check if path starts with any public path
    is_public = any(path.startswith(public_path) for public_path in public_paths)
    
    if not is_public:
        # Check if user is authenticated
        user = await get_current_user(request)
        
        if not user:
            # Redirect to login for dashboard routes
            if path.startswith("/doctor/") or path.startswith("/hospital/"):
                return RedirectResponse(url="/auth/login/page")
    
    # Continue to the route
    response = await call_next(request)
    return response