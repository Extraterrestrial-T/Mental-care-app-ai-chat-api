from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from typing import Optional
from app.config import settings
from app.services.firebase_service import firebase_service


async def get_current_user(request: Request) -> Optional[dict]:
    """Get current authenticated user (doctor or hospital) from session cookie"""
    user_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if not user_id:
        return None
    
    if user_id.startswith("doctor_"):
        doctor = await firebase_service.get_doctor(user_id)
        if doctor:
            return {"type": "doctor", "id": user_id, "data": doctor}
    
    if user_id.startswith("hospital_"):
        hospital = await firebase_service.get_hospital(user_id)
        if hospital:
            return {"type": "hospital", "id": user_id, "data": hospital}
    
    return None


async def get_current_doctor(request: Request) -> Optional[str]:
    """Get current authenticated doctor ID from session cookie"""
    user = await get_current_user(request)
    if user and user["type"] == "doctor":
        return user["id"]
    return None


async def require_doctor_auth(request: Request) -> str:
    """Dependency that requires doctor authentication"""
    doctor_id = await get_current_doctor(request)
    
    if not doctor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated as a doctor"
        )
    
    doctor = await firebase_service.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session"
        )
    
    return doctor_id


async def require_hospital_auth(request: Request) -> str:
    """Dependency that requires hospital admin authentication"""
    user = await get_current_user(request)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    if user["type"] == "hospital":
        return user["id"]
    
    if user["type"] == "doctor":
        doctor = user["data"]
        hospital_id = doctor.get("hospital_id")
        
        if not hospital_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No hospital associated with this account"
            )
        
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
    """Dependency that requires any authentication (doctor or hospital)"""
    user = await get_current_user(request)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    return user


async def optional_auth(request: Request) -> Optional[dict]:
    """Dependency that allows optional authentication"""
    return await get_current_user(request)
