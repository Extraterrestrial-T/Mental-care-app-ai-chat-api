"""
Complete Signup System
Handles registration for both hospitals and doctors
Doctors can optionally connect calendar AFTER account creation
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from httpx import request
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.services.firebase_service import firebase_service
from app.services.firebase_auth_service import firebase_auth_service
from app.config import settings
from pathlib import Path
# Static files
current_dir = Path(__file__).parent.parent
static_files_dir = current_dir / "static"

templates = Jinja2Templates(directory=static_files_dir)
router = APIRouter(prefix="/signup", tags=["signup"])

#templates = Jinja2Templates(directory=static_files_dir)
# ==================== MODELS ====================

class HospitalSignup(BaseModel):
    """Hospital registration"""
    name: str
    password: str
    phone: Optional[str] = None
    address: Optional[str] = None
    admin_name: str
    admin_email: EmailStr


class DoctorSignup(BaseModel):
    """Doctor registration"""
    name: str
    email: EmailStr
    password: str
    specialty: Optional[str] = None
    hospital_id: str


# ==================== HOSPITAL SIGNUP ====================

@router.get("/hospital", response_class=FileResponse)
async def hospital_signup_page():
    """Hospital registration page"""
    return FileResponse(static_files_dir/"hospital-signup.html")


@router.post("/hospital/register")
async def register_hospital(hospital: HospitalSignup):
    """Create hospital account with email/password"""
    print(hospital)
    try:
        # Create hospital user in Firebase Auth
        result = await firebase_auth_service.create_hospital_user(
            email=hospital.admin_email,
            password=hospital.password,
            hospital_name=hospital.name,
            address=hospital.address
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Update with additional fields
        extra_data = {
            "phone": hospital.phone,
            "admin_name": hospital.admin_name,
            "admin_email": hospital.admin_email,
            "status": "active"
        }
        await firebase_service.save_hospital(result["hospital_id"], extra_data)
        
        return {
            "success": True,
            "message": "Hospital registered successfully!",
            "hospital_id": result["hospital_id"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Hospital registration error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== DOCTOR SIGNUP ====================

@router.get("/doctor", response_class=HTMLResponse)
async def doctor_signup_page(request:Request,hospital_id: Optional[str] = None):
    """Doctor registration page"""
    hospital_id_value = hospital_id or ""
    return templates.TemplateResponse(
        "doctor-signup.html",
        {
            "request": request,
            "hospital_id": hospital_id
        }
    )



@router.post("/doctor/register")
async def register_doctor(doctor: DoctorSignup):
    """Create doctor account with email/password"""
    try:
        # Verify hospital exists
        hospital = await firebase_service.get_hospital(doctor.hospital_id)
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found. Please check your Hospital ID.")
        
        # Check if email already exists
        existing = await firebase_service.get_doctor_by_email(doctor.email)
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Create doctor account in Firebase Auth
        result = await firebase_auth_service.create_doctor_user(
            email=doctor.email,
            password=doctor.password,
            name=doctor.name,
            specialty=doctor.specialty,
            hospital_id=doctor.hospital_id
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return {
            "success": True,
            "message": "Account created successfully!",
            "doctor_id": result["doctor_id"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Doctor registration error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))