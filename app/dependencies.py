"""
FastAPI dependency injection functions
These are reusable dependencies that can be injected into route handlers
"""
from fastapi import Request, HTTPException, status, Header
from typing import Optional, Annotated
from app.config import settings
from app.services.firebase_service import firebase_service


async def get_current_doctor_id(request: Request) -> Optional[str]:
    """
    Get the current authenticated doctor ID from session cookie
    
    Returns:
        Doctor ID if authenticated, None otherwise
    """
    doctor_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    return doctor_id


async def require_authentication(request: Request) -> str:
    """
    Dependency that requires authentication
    Raises 401 if not authenticated
    
    Usage:
        @app.get("/protected")
        async def protected_route(doctor_id: str = Depends(require_authentication)):
            # doctor_id is guaranteed to exist here
    
    Returns:
        Authenticated doctor ID
        
    Raises:
        HTTPException: 401 if not authenticated
    """
    doctor_id = await get_current_doctor_id(request)
    
    if not doctor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify the doctor exists in Firebase
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please log in again.",
        )
    
    return doctor_id


async def require_doctor_auth(request: Request) -> str:
    """
    Alias for require_authentication (more semantic for doctor routes)
    
    Usage:
        @router.get("/dashboard")
        async def dashboard(doctor_id: str = Depends(require_doctor_auth)):
            return {"doctor_id": doctor_id}
    """
    return await require_authentication(request)


async def require_hospital_auth(request: Request) -> str:
    """
    Dependency that requires hospital authentication
    For MVP, this checks if doctor has a hospital_id
    
    In production, implement proper hospital admin roles
    
    Returns:
        Hospital ID
        
    Raises:
        HTTPException: 401 if not authenticated, 403 if no hospital
    """
    doctor_id = await require_authentication(request)
    
    # Get doctor to check hospital association
    doctor = await firebase_service.get_doctor(doctor_id)
    hospital_id = doctor.get("hospital_id")
    
    if not hospital_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No hospital associated with this account. Please contact your administrator.",
        )
    
    return hospital_id


async def get_optional_auth(request: Request) -> Optional[str]:
    """
    Optional authentication - returns doctor_id if authenticated, None otherwise
    Doesn't raise an exception if not authenticated
    
    Usage:
        @app.get("/optional-protected")
        async def route(doctor_id: Optional[str] = Depends(get_optional_auth)):
            if doctor_id:
                return {"message": "Authenticated", "doctor_id": doctor_id}
            return {"message": "Public access"}
    """
    doctor_id = await get_current_doctor_id(request)
    if doctor_id:
        # Verify it's valid
        doctor = await firebase_service.get_doctor(doctor_id)
        if doctor:
            return doctor_id
    return None


async def verify_api_key(x_api_key: Annotated[str, Header()] = None) -> bool:
    """
    Optional: Verify API key for programmatic access
    
    Usage:
        @app.get("/api/resource")
        async def api_route(authenticated: bool = Depends(verify_api_key)):
            if not authenticated:
                raise HTTPException(401, "Invalid API key")
    """
    # For MVP, this is not used
    # In production, implement proper API key verification
    # Example: check against Firebase or environment variable
    
    if not x_api_key:
        return False
    
    # TODO: Implement actual API key verification
    # For now, accept any key (insecure - fix in production)
    return True


async def get_current_doctor_full(request: Request) -> dict:
    """
    Get full doctor object (not just ID)
    
    Usage:
        @router.get("/profile")
        async def profile(doctor: dict = Depends(get_current_doctor_full)):
            return {"name": doctor["name"], "email": doctor["email"]}
    
    Returns:
        Full doctor dict from Firebase
        
    Raises:
        HTTPException: 401 if not authenticated
    """
    doctor_id = await require_authentication(request)
    doctor = await firebase_service.get_doctor(doctor_id)
    
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Doctor not found",
        )
    
    # Add the ID to the dict
    doctor["id"] = doctor_id
    
    # Remove sensitive credentials from response
    sensitive_fields = ["token", "refresh_token", "client_secret"]
    for field in sensitive_fields:
        doctor.pop(field, None)
    
    return doctor


async def validate_appointment_access(
    appointment_id: str,
    request: Request
) -> dict:
    """
    Verify that the current doctor has access to the appointment
    
    Usage:
        @router.get("/appointments/{appointment_id}")
        async def get_appointment(
            appointment: dict = Depends(validate_appointment_access)
        ):
            return appointment
    
    Returns:
        Appointment dict if authorized
        
    Raises:
        HTTPException: 401 if not authenticated, 403 if not authorized, 404 if not found
    """
    doctor_id = await require_authentication(request)
    
    # Get appointment from Firebase
    appointment = await firebase_service.get_appointment(appointment_id)
    
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    
    # Verify doctor owns this appointment
    if appointment.get("doctor_id") != doctor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this appointment",
        )
    
    return appointment


# Type aliases for cleaner route signatures
DoctorId = Annotated[str, require_doctor_auth]
HospitalId = Annotated[str, require_hospital_auth]
OptionalDoctorId = Annotated[Optional[str], get_optional_auth]
CurrentDoctor = Annotated[dict, get_current_doctor_full]