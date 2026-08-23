from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from .base import CalendarProvider
from .google_calendar import _build_available_slots


class MicrosoftGraphCalendarProvider(CalendarProvider):
    """Microsoft Outlook Calendar provider using Microsoft Graph."""

    provider_name = "microsoft"
    graph_base_url = "https://graph.microsoft.com/v1.0"

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    def is_connected(self, token_data: Dict[str, Any]) -> bool:
        return all(
            [
                token_data.get("calendar_connected") is not False,
                token_data.get("calendar_provider") == self.provider_name,
                token_data.get("token"),
                token_data.get("refresh_token"),
            ]
        )

    async def _access_token(self, token_data: Dict[str, Any]) -> str:
        token = token_data.get("token")
        expires_at = token_data.get("expires_at")

        if token and (not expires_at or expires_at > datetime.utcnow().timestamp() + 60):
            return token

        return await self.refresh_access_token(token_data.get("refresh_token"))

    async def refresh_access_token(self, refresh_token: str) -> str:
        if not refresh_token:
            raise ValueError("Microsoft refresh token is missing")

        token_url = (
            f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}"
            "/oauth2/v2.0/token"
        )
        data = {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(settings.MICROSOFT_SCOPES),
        }

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            payload = response.json()
            return payload["access_token"]

    async def get_available_slots(
        self,
        token_data: Dict[str, Any],
        date: datetime,
        duration_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        try:
            token = await self._access_token(token_data)
            timezone = token_data.get("timezone") or self.timezone
            tz = ZoneInfo(timezone)
            start_of_day = datetime.combine(date, datetime.min.time().replace(hour=9), tzinfo=tz)
            end_of_day = datetime.combine(date, datetime.min.time().replace(hour=17), tzinfo=tz)

            params = {
                "startDateTime": start_of_day.isoformat(),
                "endDateTime": end_of_day.isoformat(),
                "$select": "subject,start,end",
                "$orderby": "start/dateTime",
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Prefer": f'outlook.timezone="{timezone}"',
            }

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/calendarView",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                events = response.json().get("value", [])

            return _build_available_slots(
                events=events,
                start_of_day=start_of_day,
                end_of_day=end_of_day,
                duration_minutes=duration_minutes,
                start_key=("start", "dateTime"),
                end_key=("end", "dateTime"),
            )
        except Exception as e:
            print(f"Error getting Microsoft Graph slots: {e}")
            raise RuntimeError("Microsoft calendar availability lookup failed") from e

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

            token = await self._access_token(token_data)
            timezone = token_data.get("timezone") or self.timezone
            event = {
                "subject": f"Appointment: {patient_name}",
                "body": {"contentType": "text", "content": notes or ""},
                "start": {"dateTime": start_time.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end_time.isoformat(), "timeZone": timezone},
                "attendees": [
                    {
                        "emailAddress": {
                            "address": patient_email.strip(),
                            "name": patient_name,
                        },
                        "type": "required",
                    }
                ],
                "isReminderOn": True,
                "reminderMinutesBeforeStart": 30,
            }

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.graph_base_url}/me/events",
                    headers={"Authorization": f"Bearer {token}"},
                    json=event,
                )
                response.raise_for_status()
                return response.json().get("id")
        except Exception as e:
            print(f"Error creating Microsoft Graph appointment: {e}")
            return None

    async def cancel_appointment(self, token_data: Dict[str, Any], event_id: str) -> bool:
        try:
            token = await self._access_token(token_data)
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.delete(
                    f"{self.graph_base_url}/me/events/{event_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
            return True
        except Exception as e:
            print(f"Error canceling Microsoft Graph appointment: {e}")
            return False

    async def get_upcoming_appointments(
        self,
        token_data: Dict[str, Any],
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        try:
            token = await self._access_token(token_data)
            timezone = token_data.get("timezone") or self.timezone
            now = datetime.utcnow()
            params = {
                "startDateTime": now.isoformat() + "Z",
                "endDateTime": (now + timedelta(days=days)).isoformat() + "Z",
                "$select": "id,subject,start,end,attendees",
                "$orderby": "start/dateTime",
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Prefer": f'outlook.timezone="{timezone}"',
            }

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/calendarView",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                events = response.json().get("value", [])

            return [
                {
                    "id": event.get("id"),
                    "summary": event.get("subject"),
                    "start": event.get("start", {}).get("dateTime"),
                    "end": event.get("end", {}).get("dateTime"),
                    "attendees": event.get("attendees", []),
                    "provider": self.provider_name,
                }
                for event in events
            ]
        except Exception as e:
            print(f"Error getting Microsoft Graph upcoming appointments: {e}")
            return []
