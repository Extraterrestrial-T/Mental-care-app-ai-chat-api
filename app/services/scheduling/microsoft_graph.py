from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from .base import CalendarAuthorizationError, CalendarProvider
from .google_calendar import _build_available_slots


class MicrosoftGraphCalendarProvider(CalendarProvider):
    """Microsoft Outlook Calendar provider using Microsoft Graph."""

    provider_name = "microsoft"
    graph_base_url = "https://graph.microsoft.com/v1.0"
    windows_timezones = {
        "America/Detroit": "Eastern Standard Time",
        "America/New_York": "Eastern Standard Time",
        "America/Chicago": "Central Standard Time",
        "America/Denver": "Mountain Standard Time",
        "America/Los_Angeles": "Pacific Standard Time",
        "UTC": "UTC",
    }
    iana_timezones = {
        windows: iana for iana, windows in windows_timezones.items()
    }

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    def _timezone_pair(self, value: str) -> tuple[str, str]:
        """Return an IANA timezone for Python and a Windows timezone for Graph."""
        iana_timezone = self.iana_timezones.get(value, value)
        graph_timezone = self.windows_timezones.get(value, value)
        return iana_timezone, graph_timezone

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

        # A missing expiry means an existing token may be used. A zero or invalid
        # expiry must never be interpreted as missing because it represents an
        # expired credential in persisted Microsoft token data.
        token_is_fresh = expires_at is None
        if expires_at is not None:
            try:
                token_is_fresh = float(expires_at) > datetime.now(timezone.utc).timestamp() + 60
            except (TypeError, ValueError):
                token_is_fresh = False

        if token and token_is_fresh:
            return token

        payload = await self.refresh_access_token(token_data.get("refresh_token"))
        token_data["token"] = payload["access_token"]
        token_data["expires_at"] = datetime.now(timezone.utc).timestamp() + int(payload.get("expires_in", 3600))
        if payload.get("refresh_token"):
            token_data["refresh_token"] = payload["refresh_token"]
        return token_data["token"]

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        if not refresh_token:
            raise CalendarAuthorizationError("Microsoft refresh token is missing")

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
            if response.status_code in {400, 401, 403}:
                raise CalendarAuthorizationError("Microsoft calendar authorization expired")
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _raise_for_calendar_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise CalendarAuthorizationError("Microsoft calendar authorization expired")
        response.raise_for_status()

    async def validate_connection(self, token_data: Dict[str, Any]) -> None:
        token = await self._access_token(token_data)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.graph_base_url}/me/calendar",
                params={"$select": "id,name"},
                headers={"Authorization": f"Bearer {token}"},
            )
            self._raise_for_calendar_status(response)

    async def get_available_slots(
        self,
        token_data: Dict[str, Any],
        date: datetime,
        duration_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        try:
            token = await self._access_token(token_data)
            timezone = token_data.get("timezone") or self.timezone
            iana_timezone, graph_timezone = self._timezone_pair(timezone)
            tz = ZoneInfo(iana_timezone)
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
                "Prefer": f'outlook.timezone="{graph_timezone}"',
            }

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/calendarView",
                    params=params,
                    headers=headers,
                )
                self._raise_for_calendar_status(response)
                events = response.json().get("value", [])

            return _build_available_slots(
                events=events,
                start_of_day=start_of_day,
                end_of_day=end_of_day,
                duration_minutes=duration_minutes,
                start_key=("start", "dateTime"),
                end_key=("end", "dateTime"),
            )
        except CalendarAuthorizationError:
            raise
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
            _, graph_timezone = self._timezone_pair(timezone)
            event = {
                "subject": f"Appointment: {patient_name}",
                "body": {"contentType": "text", "content": notes or ""},
                "start": {"dateTime": start_time.isoformat(), "timeZone": graph_timezone},
                "end": {"dateTime": end_time.isoformat(), "timeZone": graph_timezone},
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
                self._raise_for_calendar_status(response)
                return response.json().get("id")
        except CalendarAuthorizationError:
            raise
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
                self._raise_for_calendar_status(response)
            return True
        except CalendarAuthorizationError:
            raise
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
            _, graph_timezone = self._timezone_pair(timezone)
            now = datetime.utcnow()
            params = {
                "startDateTime": now.isoformat() + "Z",
                "endDateTime": (now + timedelta(days=days)).isoformat() + "Z",
                "$select": "id,subject,start,end,attendees",
                "$orderby": "start/dateTime",
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Prefer": f'outlook.timezone="{graph_timezone}"',
            }

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.graph_base_url}/me/calendarView",
                    params=params,
                    headers=headers,
                )
                self._raise_for_calendar_status(response)
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
        except CalendarAuthorizationError:
            raise
        except Exception as e:
            print(f"Error getting Microsoft Graph upcoming appointments: {e}")
            return []
