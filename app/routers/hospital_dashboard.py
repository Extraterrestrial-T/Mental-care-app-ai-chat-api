from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from app.auth.middleware import require_hospital_auth
from app.services.firebase_service import firebase_service
from datetime import datetime, timedelta
import os


router = APIRouter(prefix="/hospital", tags=["hospital-dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def hospital_dashboard_page(request: Request):
    """Serve hospital dashboard HTML"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    dashboard_path = os.path.join(static_dir, "hospital-dashboard.html")
    
    try:
        return FileResponse(dashboard_path)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Hospital Dashboard - Coming Soon</h1>",
            status_code=404
        )


@router.get("/api/dashboard")
async def get_hospital_dashboard(hospital_id: str = Depends(require_hospital_auth)):
    """Get hospital dashboard overview"""
    # Get hospital info
    hospital = await firebase_service.get_hospital(hospital_id)
    
    if not hospital:
        # Create default hospital entry
        hospital = {
            "name": "Hospital",
            "id": hospital_id
        }
        await firebase_service.save_hospital(hospital_id, hospital)
    
    # Get all doctors in this hospital
    doctors = await firebase_service.get_doctors_by_hospital(hospital_id)
    
    
    # Get stats
    total_doctors = len(doctors)
    connected_doctors = len([d for d in doctors if d.get("refresh_token")])
    for doctor in doctors:
        doctor.pop("token", None)
        doctor.pop("refresh_token", None)   
        doctor.pop("token_uri", None)

    start_date = datetime.now()
    end_date = start_date + timedelta(days=30)
    
    

    # Get recent appointments across all doctors
    all_appointments = []
    for doctor in doctors:
        #print(f"DEBUG: Fetching appointments for doctor ID: {doctor}")  # Debug log
        doctor_appointments = await firebase_service.get_doctor_appointments(
            doctor_id=doctor["id"],
            start_date=start_date,
            end_date=end_date
        )
        #print(f"DEBUG: Appointments for doctor {doctor['id']}: {len(doctor_appointments)}")  # Debug log
        all_appointments.extend(doctor_appointments)
    #print(f"DEBUG: Total appointments found: {len(all_appointments)}")  # Debug log
    return {
        "hospital": hospital,
        "stats": {
            "total_doctors": total_doctors,
            "connected_doctors": connected_doctors,
            "total_appointments": len(all_appointments),
            "upcoming_appointments": len([a for a in all_appointments if a.get("status") == "confirmed"])
        },
        "doctors": doctors,
        "recent_appointments": sorted(
            all_appointments,
            key=lambda x: x.get("start_time", datetime.min),
            reverse=True
        )[:20]
    }


@router.get("/api/doctors")
async def get_hospital_doctors(hospital_id: str = Depends(require_hospital_auth)):
    """Get all doctors in hospital"""
    doctors = await firebase_service.get_doctors_by_hospital(hospital_id)
    
    # Don't expose sensitive credentials
    safe_doctors = []
    for doctor in doctors:
        has_calendar = all([
                doctor.get("token"),
                doctor.get("refresh_token"), 
                doctor.get("token_uri")
            ])
        safe_doctors.append({
            "id": doctor.get("id"),
            "name": doctor.get("name"),
            "email": doctor.get("email"),
            "specialty": doctor.get("specialty"),
            "profile_pic": doctor.get("profile_pic"),
            "calendar_connected": bool(has_calendar),
            "linked_at": doctor.get("linked_at")
        })
    
    return {"doctors": safe_doctors}




@router.get("/api/appointments")
async def get_hospital_appointments(
    hospital_id: str = Depends(require_hospital_auth),
    days: int = 30
):
    """Get all appointments across hospital"""
    doctors = await firebase_service.get_doctors_by_hospital(hospital_id)
    
    all_appointments = []
    for doctor in doctors:
        doctor_appointments = await firebase_service.get_doctor_appointments(
            doctor_id=doctor["id"],
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=days)
        )
        all_appointments.extend(doctor_appointments)
    
    return {
        "appointments": sorted(
            all_appointments,
            key=lambda x: x.get("start_time", datetime.min)
        )
    }