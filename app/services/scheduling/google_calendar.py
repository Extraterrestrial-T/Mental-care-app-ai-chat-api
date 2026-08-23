from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .base import CalendarAuthorizationError, CalendarProvider


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar provider implementation."""

    provider_name = "google"

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    def is_connected(self, token_data: Dict[str, Any]) -> bool:
        provider = token_data.get("calendar_provider") or "google"
        return all(
            [
                token_data.get("calendar_connected") is not False,
                provider == self.provider_name,
                token_data.get("token"),
                token_data.get("refresh_token"),
                token_data.get("token_uri"),
            ]
        )

    def _build_credentials(self, token_data: Dict[str, Any]) -> Credentials:
        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

    @staticmethod
    def _copy_credentials_to_token_data(
        token_data: Dict[str, Any], creds: Credentials
    ) -> None:
        """Retain refreshed credentials so the service can persist them after a call."""
        if creds.token:
            token_data["token"] = creds.token
        if creds.refresh_token:
            token_data["refresh_token"] = creds.refresh_token
        if creds.expiry:
            token_data["token_expiry"] = creds.expiry.isoformat()

    async def get_available_slots(
        self,
        token_data: Dict[str, Any],
        date: datetime,
        duration_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        try:
            creds = self._build_credentials(token_data)
            service = build("calendar", "v3", credentials=creds)

            tz = ZoneInfo(token_data.get("timezone") or self.timezone)
            start_of_day = datetime.combine(date, datetime.min.time().replace(hour=9), tzinfo=tz)
            end_of_day = datetime.combine(date, datetime.min.time().replace(hour=17), tzinfo=tz)

            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_of_day.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            self._copy_credentials_to_token_data(token_data, creds)

            return _build_available_slots(
                events=events_result.get("items", []),
                start_of_day=start_of_day,
                end_of_day=end_of_day,
                duration_minutes=duration_minutes,
                start_key=("start", "dateTime"),
                end_key=("end", "dateTime"),
            )
        except RefreshError as e:
            print(f"Google Calendar authorization refresh failed: {e}")
            raise CalendarAuthorizationError("Google Calendar authorization expired") from e
        except Exception as e:
            print(f"Error getting Google Calendar slots: {e}")
            raise RuntimeError("Google Calendar availability lookup failed") from e

    async def create_appointment(
        self,
        token_data: Dict[str, Any],
        patient_name: str,
        patient_email: str,
        start_time: datetime,
        end_time: datetime,
        notes: Optional[str] = None,
    ) -> Optional[str]:
        try:
            if not patient_email or "@" not in patient_email:
                raise ValueError("Valid patient email is required for calendar event")

            creds = self._build_credentials(token_data)
            service = build("calendar", "v3", credentials=creds)
            timezone = token_data.get("timezone") or self.timezone

            event = {
                "summary": f"Appointment: {patient_name}",
                "description": notes or "",
                "start": {"dateTime": start_time.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end_time.isoformat(), "timeZone": timezone},
                "attendees": [{"email": patient_email.strip()}],
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 24 * 60},
                        {"method": "popup", "minutes": 30},
                    ],
                },
            }

            created_event = (
                service.events()
                .insert(calendarId="primary", body=event, sendUpdates="all")
                .execute()
            )
            self._copy_credentials_to_token_data(token_data, creds)
            return created_event.get("id")
        except RefreshError as e:
            print(f"Google Calendar authorization refresh failed: {e}")
            raise CalendarAuthorizationError("Google Calendar authorization expired") from e
        except Exception as e:
            print(f"Error creating Google Calendar appointment: {e}")
            return None

    async def cancel_appointment(self, token_data: Dict[str, Any], event_id: str) -> bool:
        try:
            creds = self._build_credentials(token_data)
            service = build("calendar", "v3", credentials=creds)
            service.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()
            return True
        except Exception as e:
            print(f"Error canceling Google Calendar appointment: {e}")
            return False

    async def get_upcoming_appointments(
        self,
        token_data: Dict[str, Any],
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        try:
            creds = self._build_credentials(token_data)
            service = build("calendar", "v3", credentials=creds)

            now = datetime.utcnow().isoformat() + "Z"
            end_date = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    timeMax=end_date,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            appointments = []
            for event in events_result.get("items", []):
                appointments.append(
                    {
                        "id": event.get("id"),
                        "summary": event.get("summary"),
                        "start": event["start"].get("dateTime"),
                        "end": event["end"].get("dateTime"),
                        "attendees": event.get("attendees", []),
                        "provider": self.provider_name,
                    }
                )

            return appointments
        except Exception as e:
            print(f"Error getting Google Calendar upcoming appointments: {e}")
            return []


def _build_available_slots(
    events: List[Dict[str, Any]],
    start_of_day: datetime,
    end_of_day: datetime,
    duration_minutes: int,
    start_key: tuple[str, str],
    end_key: tuple[str, str],
) -> List[Dict[str, Any]]:
    available_slots = []
    current_time = start_of_day

    while current_time < end_of_day:
        slot_end = current_time + timedelta(minutes=duration_minutes)
        is_available = True

        for event in events:
            start_container, start_field = start_key
            end_container, end_field = end_key
            event_start_raw = event.get(start_container, {}).get(start_field)
            event_end_raw = event.get(end_container, {}).get(end_field)

            if not event_start_raw or not event_end_raw:
                continue

            event_start = datetime.fromisoformat(event_start_raw.replace("Z", "+00:00"))
            event_end = datetime.fromisoformat(event_end_raw.replace("Z", "+00:00"))

            if current_time < event_end and slot_end > event_start:
                is_available = False
                break

        if is_available and slot_end <= end_of_day:
            available_slots.append(
                {
                    "start": current_time.isoformat(),
                    "end": slot_end.isoformat(),
                    "display": current_time.strftime("%I:%M %p"),
                }
            )

        current_time += timedelta(minutes=duration_minutes)

    return available_slots
