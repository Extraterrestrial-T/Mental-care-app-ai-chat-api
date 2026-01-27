from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class AppointmentStatus(str, Enum):
    """Appointment status enum"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class AppointmentBase(BaseModel):
    """Base appointment model"""
    doctor_id: str
    patient_name: str = Field(..., min_length=1, max_length=100)
    patient_email: EmailStr
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = Field(None, max_length=500)


class AppointmentCreate(AppointmentBase):
    """Model for creating an appointment"""
    pass


class AppointmentUpdate(BaseModel):
    """Model for updating an appointment"""
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = Field(None, max_length=500)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class AppointmentInDB(AppointmentBase):
    """Appointment model as stored in database"""
    id: str
    doctor_name: str
    calendar_event_id: Optional[str] = None
    status: AppointmentStatus = AppointmentStatus.CONFIRMED
    hospital_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppointmentPublic(BaseModel):
    """Appointment model for public API responses"""
    id: str
    doctor_id: str
    doctor_name: str
    patient_name: str
    patient_email: EmailStr
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = None
    status: AppointmentStatus
    created_at: datetime

    class Config:
        from_attributes = True


class TimeSlot(BaseModel):
    """Available time slot"""
    start: str  # ISO format datetime string
    end: str    # ISO format datetime string
    display: str  # Human-readable format like "2:00 PM"


class AvailabilityRequest(BaseModel):
    """Request for available time slots"""
    doctor_id: str
    date: str  # ISO format date (YYYY-MM-DD)
    duration_minutes: Optional[int] = Field(30, ge=15, le=120)


class AvailabilityResponse(BaseModel):
    """Response with available slots"""
    doctor_id: str
    doctor_name: str
    date: str
    available_slots: list[TimeSlot]


class BookingRequest(BaseModel):
    """Request to book an appointment"""
    doctor_id: str
    patient_name: str = Field(..., min_length=1, max_length=100)
    patient_email: EmailStr
    start_time: datetime
    end_time: datetime
    notes: Optional[str] = Field(None, max_length=500)


class BookingResponse(BaseModel):
    """Response after booking an appointment"""
    success: bool
    appointment_id: Optional[str] = None
    event_id: Optional[str] = None
    message: str
    error: Optional[str] = None
    appointment: Optional[AppointmentPublic] = None


class CancelAppointmentRequest(BaseModel):
    """Request to cancel an appointment"""
    appointment_id: str
    reason: Optional[str] = Field(None, max_length=200)