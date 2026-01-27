import os
import firebase_admin
from firebase_admin import credentials, firestore
from typing import Optional, Dict, Any, List
from google.cloud.firestore_v1 import FieldFilter
from datetime import datetime

class FirebaseService:
    """Service layer for Firebase Firestore operations"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Firebase Admin SDK (only once)"""
        if not self._initialized:
            if not firebase_admin._apps:
                # 1. Get Project ID and Database ID from Env
                project_id = os.getenv("FIREBASE_PROJECT_ID", "mental-479910")
                # Specific named database as requested: auth-tokens-calendar
                database_id = os.getenv("FIREBASE_DATABASE_ID", "auth-tokens-calendar")
                
                # 2. Get Credential Path from Env
                cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                
                try:
                    if cred_path and os.path.exists(cred_path):
                        print(f"--- Firebase Init: Using Service Account File: {cred_path} ---")
                        cred = credentials.Certificate(cred_path)
                        firebase_admin.initialize_app(cred, {
                            'projectId': project_id,
                        })
                    else:
                        print("--- Firebase Init: Using Application Default Credentials ---")
                        cred = credentials.ApplicationDefault()
                        firebase_admin.initialize_app(cred, {
                            'projectId': project_id,
                        })
                    
                    # CRITICAL FIX: Explicitly specify the named database ID
                    self.db = firestore.client(database_id=database_id)
                    print(f"✅ Successfully connected to Firestore Project: {self.db.project}")
                    print(f"✅ Using Database Instance: {database_id}")
                    
                    self._initialized = True
                    
                except Exception as e:
                    print(f"❌ Failed to initialize Firebase: {str(e)}")
                    raise e

    async def save_doctor_credentials(
        self, 
        doctor_id: str, 
        doctor_data: Dict[str, Any]
    ) -> bool:
        """Save or update doctor credentials and profile"""
        try:
            doctor_data["updated_at"] = firestore.SERVER_TIMESTAMP
            self.db.collection("doctors").document(doctor_id).set(
                doctor_data, 
                merge=True
            )
            return True
        except Exception as e:
            print(f"Error saving doctor credentials: {e}")
            return False
    
    async def get_doctor(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        """Get doctor profile and credentials"""
        try:
            doc = self.db.collection("doctors").document(doctor_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            print(f"Error getting doctor: {e}")
            return None
    
    async def get_doctor_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get doctor by email"""
        try:
            docs = self.db.collection("doctors").where(
                filter=FieldFilter("email", "==", email)
            ).limit(1).stream()
            
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
            return None
        except Exception as e:
            print(f"Error getting doctor by email: {e}")
            return None
    
    async def get_doctors_by_hospital(self, hospital_id: str) -> List[Dict[str, Any]]:
        """Get all doctors belonging to a hospital"""
        try:
            docs = self.db.collection("doctors").where(
                filter=FieldFilter("hospital_id", "==", hospital_id)
            ).stream()
            
            doctors = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                doctors.append(data)
            return doctors
        except Exception as e:
            print(f"Error getting doctors by hospital: {e}")
            return []
    
    # ==================== HOSPITAL OPERATIONS ====================
    
    async def save_hospital(
        self, 
        hospital_id: str, 
        hospital_data: Dict[str, Any]
    ) -> bool:
        """Save or update hospital data"""
        try:
            hospital_data["updated_at"] = firestore.SERVER_TIMESTAMP
            self.db.collection("hospitals").document(hospital_id).set(
                hospital_data, 
                merge=True
            )
            return True
        except Exception as e:
            print(f"Error saving hospital: {e}")
            return False
    
    async def get_hospital(self, hospital_id: str) -> Optional[Dict[str, Any]]:
        """Get hospital data"""
        try:
            doc = self.db.collection("hospitals").document(hospital_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = hospital_id
                return data
            return None
        except Exception as e:
            print(f"Error getting hospital: {e}")
            return None
    
    async def get_hospital_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get hospital by email"""
        try:
            docs = self.db.collection("hospitals").where(
                filter=FieldFilter("email", "==", email)
            ).limit(1).stream()
            
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
            return None
        except Exception as e:
            print(f"Error getting hospital by email: {e}")
            return None
    
    async def get_all_hospitals(self) -> List[Dict[str, Any]]:
        """Get all hospitals"""
        try:
            docs = self.db.collection("hospitals").stream()
            
            hospitals = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                hospitals.append(data)
            return hospitals
        except Exception as e:
            print(f"Error getting all hospitals: {e}")
            return []
    
    # ==================== APPOINTMENT OPERATIONS ====================
    
    async def save_appointment(
        self, 
        appointment_data: Dict[str, Any]
    ) -> Optional[str]:
        """Save appointment to Firestore, return appointment ID"""
        try:
            appointment_data["created_at"] = firestore.SERVER_TIMESTAMP
            appointment_data["updated_at"] = firestore.SERVER_TIMESTAMP
            
            doc_ref = self.db.collection("appointments").document()
            doc_ref.set(appointment_data)
            return doc_ref.id
        except Exception as e:
            print(f"Error saving appointment: {e}")
            return None
    
    async def get_appointment(self, appointment_id: str) -> Optional[Dict[str, Any]]:
        """Get appointment by ID"""
        try:
            doc = self.db.collection("appointments").document(appointment_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
            return None
        except Exception as e:
            print(f"Error getting appointment: {e}")
            return None
    
    async def get_doctor_appointments(
        self, 
        doctor_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get all appointments for a doctor"""
        try:
            query = self.db.collection("appointments").where(
                filter=FieldFilter("doctor_id", "==", doctor_id)
            )
            
            if start_date:
                query = query.where(
                    filter=FieldFilter("start_time", ">=", start_date)
                )
            
            if end_date:
                query = query.where(
                    filter=FieldFilter("start_time", "<=", end_date)
                )
            
            docs = query.order_by("start_time").stream()
            
            appointments = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                appointments.append(data)
            return appointments
        except Exception as e:
            print(f"Error getting doctor appointments: {e}")
            return []
    
    async def update_appointment_status(
        self, 
        appointment_id: str, 
        status: str
    ) -> bool:
        """Update appointment status"""
        try:
            self.db.collection("appointments").document(appointment_id).update({
                "status": status,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            print(f"Error updating appointment: {e}")
            return False


# Singleton instance
firebase_service = FirebaseService()