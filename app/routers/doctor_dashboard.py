from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from app.auth.middleware import require_doctor_auth
from app.services.doctor_service import doctor_service
from app.services.firebase_service import firebase_service
from datetime import datetime, timedelta
import os


router = APIRouter(prefix="/doctor", tags=["doctor-dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def doctor_dashboard_page(request: Request):
    """Serve doctor dashboard HTML"""
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    dashboard_path = os.path.join(static_dir, "doctor-dashboard.html")
    
    try:
        return FileResponse(dashboard_path)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Doctor Dashboard - Coming Soon</h1>",
            status_code=404
        )


@router.get("/api/dashboard")
async def get_dashboard_data(doctor_id: str = Depends(require_doctor_auth)):
    """Get doctor dashboard data (API endpoint)"""
    data = await doctor_service.get_doctor_dashboard_data(doctor_id)
    return data


@router.get("/api/appointments")
async def get_appointments(
    doctor_id: str = Depends(require_doctor_auth),
    days: int = 30
):
    """Get doctor appointments"""
    start_date = datetime.now()
    end_date = start_date + timedelta(days=days)
    
    appointments = await firebase_service.get_doctor_appointments(
        doctor_id=doctor_id,
        start_date=start_date,
        end_date=end_date
    )
    print(appointments)
    return {"appointments": appointments}


@router.get("/api/available-slots")
async def get_available_slots(
    date: str,
    doctor_id: str = Depends(require_doctor_auth)
):
    """Get available time slots for a specific date"""
    try:
        date_obj = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO format (YYYY-MM-DD)")
    
    result = await doctor_service.get_available_slots(
        doctor_id=doctor_id,
        date=date_obj
    )
    
    return result


@router.put("/api/appointments/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    status: str,
    doctor_id: str = Depends(require_doctor_auth)
):
    """Update appointment status (cancel, confirm, etc.)"""
    # Verify appointment belongs to this doctor
    appointment = await firebase_service.get_appointment(appointment_id)
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appointment.get("doctor_id") != doctor_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    success = await firebase_service.update_appointment_status(
        appointment_id=appointment_id,
        status=status
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update appointment")
    
    return {"success": True, "message": f"Appointment {status}"}