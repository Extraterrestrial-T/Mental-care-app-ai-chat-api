import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from .firebase_service import firebase_service
from .scheduling.base import CalendarAuthorizationError
from .scheduling import get_calendar_provider
from app.config import settings


class DoctorService:
    """High-level service for doctor-related operations"""

    @staticmethod
    def _calendar_token_updates(doctor: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
        fields = ("token", "refresh_token", "token_expiry", "expires_at")
        return {
            field: doctor[field]
            for field in fields
            if doctor.get(field) and doctor.get(field) != previous.get(field)
        }

    @staticmethod
    def _safe_doctor(doctor: Dict[str, Any]) -> Dict[str, Any]:
        provider = get_calendar_provider(doctor)
        status = doctor.get("calendar_status", "unknown")
        last_checked = doctor.get("calendar_last_checked_at")
        if isinstance(last_checked, datetime):
            last_checked = last_checked.isoformat()
        linked_at = doctor.get("linked_at")
        if isinstance(linked_at, datetime):
            linked_at = linked_at.isoformat()
        connected = doctor.get("calendar_connected") is True and status not in {
            "reauthorization_required",
            "temporarily_unavailable",
        }
        return {
            "id": doctor.get("id"),
            "name": doctor.get("name"),
            "email": doctor.get("email"),
            "specialty": doctor.get("specialty") or "Mental Health Professional",
            "profile_pic": doctor.get("profile_pic"),
            "calendar_connected": connected,
            "calendar_status": status,
            "calendar_provider": doctor.get("calendar_provider") or provider.provider_name,
            "calendar_last_checked_at": last_checked,
            "linked_at": linked_at,
        }

    @staticmethod
    def _recently_checked(doctor: Dict[str, Any]) -> bool:
        checked = doctor.get("calendar_last_checked_at")
        if not isinstance(checked, datetime):
            return False
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        ttl_minutes = settings.CALENDAR_HEALTH_TTL_MINUTES
        return checked >= datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)

    async def verify_calendar_connection(
        self, doctor: Dict[str, Any], *, force: bool = False
    ) -> bool:
        """Verify one provider connection and persist a dashboard-safe status."""
        doctor_id = doctor.get("id")
        if not doctor_id:
            return False

        provider = get_calendar_provider(doctor)
        if not provider.is_connected(doctor):
            await firebase_service.save_doctor_credentials(
                doctor_id,
                {
                    "calendar_connected": False,
                    "calendar_status": "reauthorization_required",
                    "calendar_connection_error": "missing_or_expired_credentials",
                    "calendar_last_checked_at": datetime.now(timezone.utc),
                },
            )
            doctor.update({"calendar_connected": False, "calendar_status": "reauthorization_required"})
            return False

        if (
            not force
            and doctor.get("calendar_connected") is True
            and doctor.get("calendar_status") == "connected"
            and self._recently_checked(doctor)
        ):
            return True
        if (
            not force
            and doctor.get("calendar_status") == "temporarily_unavailable"
            and self._recently_checked(doctor)
        ):
            return False

        previous = {
            field: doctor.get(field)
            for field in ("token", "refresh_token", "token_expiry", "expires_at")
        }
        now = datetime.now(timezone.utc)
        try:
            await provider.validate_connection(doctor)
            updates = self._calendar_token_updates(doctor, previous)
            updates.update(
                {
                    "calendar_connected": True,
                    "calendar_status": "connected",
                    "calendar_connection_error": None,
                    "calendar_last_checked_at": now,
                }
            )
            await firebase_service.save_doctor_credentials(doctor_id, updates)
            doctor.update(updates)
            return True
        except CalendarAuthorizationError:
            updates = {
                "calendar_connected": False,
                "calendar_status": "reauthorization_required",
                "calendar_connection_error": "reauthorization_required",
                "calendar_last_checked_at": now,
            }
            await firebase_service.save_doctor_credentials(doctor_id, updates)
            doctor.update(updates)
            return False
        except Exception as exc:
            updates = {
                "calendar_status": "temporarily_unavailable",
                "calendar_connection_error": type(exc).__name__,
                "calendar_last_checked_at": now,
            }
            await firebase_service.save_doctor_credentials(doctor_id, updates)
            doctor.update(updates)
            return False

    async def list_bookable_doctors(self, hospital_id: str) -> List[Dict[str, Any]]:
        doctors = await firebase_service.get_doctors_by_hospital(hospital_id)

        semaphore = asyncio.Semaphore(5)

        async def check(doctor: Dict[str, Any]) -> bool:
            async with semaphore:
                return await self.verify_calendar_connection(doctor)

        results = await asyncio.gather(
            *(check(doctor) for doctor in doctors)
        )
        return [
            self._safe_doctor(doctor)
            for doctor, connected in zip(doctors, results)
            if connected
        ]

    async def list_hospital_doctors(self, hospital_id: str) -> List[Dict[str, Any]]:
        doctors = await firebase_service.get_doctors_by_hospital(hospital_id)
        return [self._safe_doctor(doctor) for doctor in doctors]
    
    async def get_doctor_with_calendar(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        """Get doctor profile with calendar provider connection status."""
        doctor = await firebase_service.get_doctor(doctor_id)
        if not doctor:
            return None

        provider = get_calendar_provider(doctor)
        has_calendar = provider.is_connected(doctor) and doctor.get("calendar_connected") is not False
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
        previous_tokens = {field: doctor.get(field) for field in ("token", "refresh_token", "token_expiry", "expires_at")}
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
                    "calendar_status": "reauthorization_required",
                    "calendar_connection_error": "reauthorization_required",
                },
            )
            return {"error": "This doctor's calendar needs to be reconnected before appointments can be booked"}
        except Exception as exc:
            await firebase_service.save_doctor_credentials(
                doctor_id,
                {
                    "calendar_status": "temporarily_unavailable",
                    "calendar_connection_error": type(exc).__name__,
                    "calendar_last_checked_at": datetime.now(timezone.utc),
                },
            )
            return {"error": "This calendar is temporarily unavailable. Please select another doctor or try again shortly."}

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
        patient_phone: Optional[str],
        start_time: datetime,
        end_time: datetime,
        notes: Optional[str] = None,
        hospital_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Book an appointment
        
        Returns:
            Dict with booking status and appointment details
        """
        doctor = await self.get_doctor_with_calendar(doctor_id)
        
        if not doctor:
            return {"success": False, "error": "Doctor not found"}

        if hospital_id and doctor.get("hospital_id") != hospital_id:
            return {"success": False, "error": "Doctor is not available for this hospital"}
        
        if not doctor.get("calendar_connected"):
            return {"success": False, "error": "Doctor calendar not connected"}
        
        provider = get_calendar_provider(doctor)
        previous_tokens = {field: doctor.get(field) for field in ("token", "refresh_token", "token_expiry", "expires_at")}
        try:
            event_id = await provider.create_appointment(
                token_data=doctor,
                patient_name=patient_name,
                patient_email=patient_email,
                start_time=start_time,
                end_time=end_time,
                notes="Booked via Care Coordinator. Intake details are available in the clinic dashboard."
            )
        except CalendarAuthorizationError:
            await firebase_service.save_doctor_credentials(
                doctor_id,
                {
                    "calendar_connected": False,
                    "calendar_status": "reauthorization_required",
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
            "patient_phone": patient_phone,
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
        
        # Get appointments from Firestore
        firestore_appointments = await firebase_service.get_doctor_appointments(
            doctor_id=doctor_id
        )
        now = datetime.now(timezone.utc)
        upcoming = []
        for appointment in firestore_appointments:
            start = appointment.get("start_time")
            if isinstance(start, str):
                start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if isinstance(start, datetime):
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if start >= now and appointment.get("status") != "cancelled":
                    upcoming.append(appointment)
        
        return {
            "doctor": {
                "id": doctor_id,
                "name": doctor.get("name"),
                "email": doctor.get("email"),
                "specialty": doctor.get("specialty"),
                "profile_pic": doctor.get("profile_pic"),
                "calendar_connected": doctor.get("calendar_connected"),
                "calendar_status": doctor.get("calendar_status", "unknown"),
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
