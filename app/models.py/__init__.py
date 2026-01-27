"""
Data models for the application
All Pydantic models for request/response validation
"""

from .doctor import (
    DoctorBase,
    DoctorCreate,
    DoctorInDB,
    DoctorPublic,
)

from .appointment import (
    AppointmentStatus,
    AppointmentBase,
    AppointmentCreate,
    AppointmentUpdate,
    AppointmentInDB,
    AppointmentPublic,
    TimeSlot,
    AvailabilityRequest,
    AvailabilityResponse,
    BookingRequest,
    BookingResponse,
    CancelAppointmentRequest,
)


__all__ = [
    # Doctor models
    "DoctorBase",
    "DoctorCreate",
    "DoctorInDB",
    "DoctorPublic",
    
    # Appointment models
    "AppointmentStatus",
    "AppointmentBase",
    "AppointmentCreate",
    "AppointmentUpdate",
    "AppointmentInDB",
    "AppointmentPublic",
    "TimeSlot",
    "AvailabilityRequest",
    "AvailabilityResponse",
    "BookingRequest",
    "BookingResponse",
    "CancelAppointmentRequest",
]