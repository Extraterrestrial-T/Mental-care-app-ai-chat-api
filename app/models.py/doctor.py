from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class DoctorBase(BaseModel):
    """Base doctor model"""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    specialty: Optional[str] = Field(None, max_length=100)
    profile_pic: Optional[str] = None
    hospital_id: Optional[str] = None


class DoctorCreate(DoctorBase):
    """Model for creating a doctor"""
    pass


class DoctorUpdate(BaseModel):
    """Model for updating a doctor"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    specialty: Optional[str] = Field(None, max_length=100)
    profile_pic: Optional[str] = None


class DoctorInDB(DoctorBase):
    """Doctor model with OAuth credentials (for internal use only)"""
    token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_uri: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scopes: Optional[List[str]] = None
    linked_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DoctorPublic(DoctorBase):
    """Doctor model for public API responses (no credentials)"""
    id: str
    calendar_connected: bool = False

    class Config:
        from_attributes = True


class HospitalBase(BaseModel):
    """Base hospital model"""
    name: str = Field(..., min_length=1, max_length=200)
    address: Optional[str] = Field(None, max_length=500)


class HospitalCreate(HospitalBase):
    """Model for creating a hospital"""
    pass


class HospitalUpdate(BaseModel):
    """Model for updating a hospital"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = Field(None, max_length=500)


class HospitalInDB(HospitalBase):
    """Hospital model in database"""
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HospitalPublic(HospitalBase):
    """Hospital model for public API"""
    id: str
    total_doctors: int = 0
    
    class Config:
        from_attributes = True