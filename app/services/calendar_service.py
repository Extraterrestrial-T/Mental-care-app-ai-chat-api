from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pytz


class CalendarService:
    """Service for Google Calendar operations"""
    
    def __init__(self):
        self.timezone = "America/New_York"  # Configure based on hospital/doctor
    
    def _build_credentials(self, token_data: Dict[str, Any]) -> Credentials:
        """Rebuild Google Credentials from stored token data"""
        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes")
        )
    
    async def get_available_slots(
        self,
        token_data: Dict[str, Any],
        date: datetime,
        duration_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get available time slots for a given date
        
        Args:
            token_data: Doctor's OAuth token data
            date: Date to check availability
            duration_minutes: Appointment duration
            
        Returns:
            List of available slots with start/end times
        """
        try:
            creds = self._build_credentials(token_data)
            service = build('calendar', 'v3', credentials=creds)
            
            # Define working hours (9 AM - 5 PM)
            tz = pytz.timezone(self.timezone)
            start_of_day = tz.localize(datetime.combine(date, datetime.min.time().replace(hour=9)))
            end_of_day = tz.localize(datetime.combine(date, datetime.min.time().replace(hour=17)))
            
            # Get existing events
            events_result = service.events().list(
                calendarId='primary',
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Generate all possible slots
            available_slots = []
            current_time = start_of_day
            
            while current_time < end_of_day:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                
                # Check if slot overlaps with any existing event
                is_available = True
                for event in events:
                    event_start = datetime.fromisoformat(event['start'].get('dateTime'))
                    event_end = datetime.fromisoformat(event['end'].get('dateTime'))
                    
                    if (current_time < event_end and slot_end > event_start):
                        is_available = False
                        break
                
                if is_available and slot_end <= end_of_day:
                    available_slots.append({
                        "start": current_time.isoformat(),
                        "end": slot_end.isoformat(),
                        "display": current_time.strftime("%I:%M %p")
                    })
                
                current_time += timedelta(minutes=duration_minutes)
            
            return available_slots
            
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return []
    
    async def create_appointment(
        self,
        token_data: Dict[str, Any],
        patient_name: str,
        patient_email: str,
        start_time: datetime,
        end_time: datetime,
        notes: Optional[str] = None
    ) -> Optional[str]:
        """
        Create an appointment in Google Calendar
        
        Returns:
            Google Calendar event ID if successful
        """
        try:
            creds = self._build_credentials(token_data)
            service = build('calendar', 'v3', credentials=creds)
            
            # Validate patient email
            if not patient_email or '@' not in patient_email:
                print(f"Invalid patient email: {patient_email}")
                raise ValueError("Valid patient email is required for calendar event")
            
            event = {
                'summary': f'Appointment: {patient_name}',
                'description': notes or '',
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': self.timezone,
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': self.timezone,
                },
                'attendees': [
                    {'email': patient_email.strip()}  # Ensure email is trimmed
                ],
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 30},
                    ],
                },
            }
            
            print(f"Creating calendar event for: {patient_name} ({patient_email})")
            print(f"Event details: {event}")
            
            created_event = service.events().insert(
                calendarId='primary',
                body=event,
                sendUpdates='all'  # Send email notifications
            ).execute()
            
            print(f"Successfully created event: {created_event.get('id')}")
            return created_event.get('id')
            
        except Exception as e:
            print(f"Error creating appointment: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def cancel_appointment(
        self,
        token_data: Dict[str, Any],
        event_id: str
    ) -> bool:
        """Cancel an appointment in Google Calendar"""
        try:
            creds = self._build_credentials(token_data)
            service = build('calendar', 'v3', credentials=creds)
            
            service.events().delete(
                calendarId='primary',
                eventId=event_id,
                sendUpdates='all'
            ).execute()
            
            return True
            
        except Exception as e:
            print(f"Error canceling appointment: {e}")
            return False
    
    async def get_upcoming_appointments(
        self,
        token_data: Dict[str, Any],
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """Get upcoming appointments from Google Calendar"""
        try:
            creds = self._build_credentials(token_data)
            service = build('calendar', 'v3', credentials=creds)
            
            now = datetime.utcnow().isoformat() + 'Z'
            end_date = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'
            
            events_result = service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=end_date,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            appointments = []
            for event in events:
                appointments.append({
                    "id": event.get('id'),
                    "summary": event.get('summary'),
                    "start": event['start'].get('dateTime'),
                    "end": event['end'].get('dateTime'),
                    "attendees": event.get('attendees', [])
                })
            
            return appointments
            
        except Exception as e:
            print(f"Error getting upcoming appointments: {e}")
            return []


# Singleton instance
calendar_service = CalendarService()