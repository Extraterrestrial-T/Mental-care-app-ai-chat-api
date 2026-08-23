from typing import Optional, Dict, Any, List
from datetime import datetime
from .firebase_service import firebase_service
from .scheduling.base import CalendarAuthorizationError
from .scheduling import get_calendar_provider


class DoctorService:
    """High-level service for doctor-related operations"""

    @staticmethod
    def _calendar_token_updates(doctor: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
        fields = ("token", "refresh_token", "token_expiry")
        return {
            field: doctor[field]
            for field in fields
            if doctor.get(field) and doctor.get(field) != previous.get(field)
        }
    
    async def get_doctor_with_calendar(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        """Get doctor profile with calendar provider connection status."""
        doctor = await firebase_service.get_doctor(doctor_id)
        if not doctor:
            return None

        provider = get_calendar_provider(doctor)
        has_calendar = provider.is_connected(doctor)
        doctor["calendar_connected"] = has_calendar
        doctor["calendar_provider"] = doctor.get("calendar_provider") or provider.provider_name
        return doctor
    
    async def get_available_slots(
        self,
        doctor_id: str,
        date: datetime,
        duration_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Get available appointment slots for a doctor
        
        Returns:
            Dict with doctor info and available slots
        """
        doctor = await self.get_doctor_with_calendar(doctor_id)
        
        if not doctor:
            return {"error": "Doctor not found"}
        
        if not doctor.get("calendar_connected"):
            return {"error": "Doctor has not connected their calendar"}
        
        provider = get_calendar_provider(doctor)
        previous_tokens = {field: doctor.get(field) for field in ("token", "refresh_token", "token_expiry")}
        try:
            slots = await provider.get_available_slots(
                token_data=doctor,
                date=date,
                duration_minutes=duration_minutes
            )
        except CalendarAuthorizationError:
            await firebase_service.save_doctor_credentials(
                doctor_id,
                {
                    "calendar_connected": False,
                    "calendar_connection_error": "reauthorization_required",
                },
            )
            return {"error": "This doctor's calendar needs to be reconnected before appointments can be booked"}

        token_updates = self._calendar_token_updates(doctor, previous_tokens)
        if token_updates:
            await firebase_service.save_doctor_credentials(doctor_id, token_updates)
        
        return {
            "doctor": {
                "id": doctor_id,
                "name": doctor.get("name"),
                "email": doctor.get("email"),
                "specialty": doctor.get("specialty"),
            },
            "date": date.isoformat(),
            "available_slots": slots
        }
    
    async def book_appointment(
        self,
        doctor_id: str,
        patient_name: str,
        patient_email: str,
        start_time: datetime,
        end_time: datetime,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Book an appointment
        
        Returns:
            Dict with booking status and appointment details
        """
        doctor = await self.get_doctor_with_calendar(doctor_id)
        
        if not doctor:
            return {"success": False, "error": "Doctor not found"}
        
        if not doctor.get("calendar_connected"):
            return {"success": False, "error": "Doctor calendar not connected"}
        
        provider = get_calendar_provider(doctor)
        previous_tokens = {field: doctor.get(field) for field in ("token", "refresh_token", "token_expiry")}
        try:
            event_id = await provider.create_appointment(
                token_data=doctor,
                patient_name=patient_name,
                patient_email=patient_email,
                start_time=start_time,
                end_time=end_time,
                notes=notes
            )
        except CalendarAuthorizationError:
            await firebase_service.save_doctor_credentials(
                doctor_id,
                {
                    "calendar_connected": False,
                    "calendar_connection_error": "reauthorization_required",
                },
            )
            return {"success": False, "error": "Doctor calendar needs to be reconnected"}

        token_updates = self._calendar_token_updates(doctor, previous_tokens)
        if token_updates:
            await firebase_service.save_doctor_credentials(doctor_id, token_updates)
        
        if not event_id:
            return {"success": False, "error": "Failed to create calendar event"}
        
        # Save appointment to Firestore
        appointment_data = {
            "doctor_id": doctor_id,
            "doctor_name": doctor.get("name"),
            "patient_name": patient_name,
            "patient_email": patient_email,
            "start_time": start_time,
            "end_time": end_time,
            "notes": notes,
            "calendar_event_id": event_id,
            "calendar_provider": provider.provider_name,
            "status": "confirmed",
            "hospital_id": doctor.get("hospital_id")
        }
        
        appointment_id = await firebase_service.save_appointment(appointment_data)
        
        if not appointment_id:
            # Rollback: cancel the calendar event
            await provider.cancel_appointment(doctor, event_id)
            return {"success": False, "error": "Failed to save appointment"}
        
        return {
            "success": True,
            "appointment_id": appointment_id,
            "event_id": event_id,
            "message": f"Appointment booked with Dr. {doctor.get('name')} on {start_time.strftime('%B %d, %Y at %I:%M %p')} Please note that this appointment can be rescheduled based on doctor availability, however you will be notified in advance."
        }
    
    async def get_doctor_dashboard_data(self, doctor_id: str) -> Dict[str, Any]:
        """Get all data needed for doctor dashboard"""
        doctor = await self.get_doctor_with_calendar(doctor_id)
        
        if not doctor:
            return {"error": "Doctor not found"}
        
        # Get upcoming appointments
        upcoming = []
        if doctor.get("calendar_connected"):
            provider = get_calendar_provider(doctor)
            upcoming = await provider.get_upcoming_appointments(
                token_data=doctor,
                days=30
            )
        
        # Get appointments from Firestore
        firestore_appointments = await firebase_service.get_doctor_appointments(
            doctor_id=doctor_id
        )
        
        return {
            "doctor": {
                "id": doctor_id,
                "name": doctor.get("name"),
                "email": doctor.get("email"),
                "specialty": doctor.get("specialty"),
                "profile_pic": doctor.get("profile_pic"),
                "calendar_connected": doctor.get("calendar_connected"),
                "calendar_provider": doctor.get("calendar_provider"),
            },
            "appointments": {
                "upcoming": upcoming[:10],  # Next 10 appointments
                "total": len(firestore_appointments),
                "today": [a for a in firestore_appointments if self._is_today(a.get("start_time"))]
            },
            "stats": {
                "total_appointments": len(firestore_appointments),
                "upcoming_count": len(upcoming),
                "today_count": len([a for a in firestore_appointments if self._is_today(a.get("start_time"))])
            }
        }
    
    def _is_today(self, dt: Any) -> bool:
        """Check if datetime is today"""
        if not dt:
            return False
        
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        
        return dt.date() == datetime.now().date()


# Singleton instance
doctor_service = DoctorService()
