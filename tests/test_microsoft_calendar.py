import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

try:
    from app.services.scheduling.base import CalendarAuthorizationError
    from app.services.scheduling.google_calendar import _build_available_slots
    from app.services.scheduling.microsoft_graph import MicrosoftGraphCalendarProvider
except ModuleNotFoundError:
    CalendarAuthorizationError = None
    _build_available_slots = None
    MicrosoftGraphCalendarProvider = None


class _Response:
    status_code = 200

    def json(self):
        return {
            "access_token": "new-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_in": 3600,
        }

    def raise_for_status(self):
        return None


class _Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        return _Response()


class _UnauthorizedResponse:
    status_code = 401


class _UnauthorizedClient(_Client):
    async def get(self, *_args, **_kwargs):
        return _UnauthorizedResponse()


@unittest.skipIf(MicrosoftGraphCalendarProvider is None, "calendar dependencies are not installed")
class MicrosoftCalendarTests(unittest.IsolatedAsyncioTestCase):
    def test_graph_timezone_and_naive_event_times_are_normalized(self):
        provider = MicrosoftGraphCalendarProvider()
        self.assertEqual(
            provider._timezone_pair("America/Detroit"),
            ("America/Detroit", "Eastern Standard Time"),
        )

        timezone = ZoneInfo("America/Detroit")
        start = datetime(2026, 8, 27, 9, 0, tzinfo=timezone)
        end = datetime(2026, 8, 27, 11, 0, tzinfo=timezone)
        slots = _build_available_slots(
            events=[
                {
                    "start": {"dateTime": "2026-08-27T09:30:00"},
                    "end": {"dateTime": "2026-08-27T10:00:00"},
                }
            ],
            start_of_day=start,
            end_of_day=end,
            duration_minutes=30,
            start_key=("start", "dateTime"),
            end_key=("end", "dateTime"),
        )
        self.assertEqual(
            [slot["display"] for slot in slots],
            ["09:00 AM", "10:00 AM", "10:30 AM"],
        )

    async def test_refresh_updates_rotated_credentials_in_doctor_state(self):
        provider = MicrosoftGraphCalendarProvider()
        doctor = {
            "token": "expired-token",
            "refresh_token": "old-refresh-token",
            "expires_at": 0,
        }

        with patch(
            "app.services.scheduling.microsoft_graph.httpx.AsyncClient",
            return_value=_Client(),
        ):
            token = await provider._access_token(doctor)

        self.assertEqual(token, "new-access-token")
        self.assertEqual(doctor["refresh_token"], "rotated-refresh-token")
        self.assertGreater(doctor["expires_at"], 0)

    async def test_missing_expiry_refreshes_legacy_token(self):
        provider = MicrosoftGraphCalendarProvider()
        doctor = {
            "token": "unverified-access-token",
            "refresh_token": "legacy-refresh-token",
        }

        with patch(
            "app.services.scheduling.microsoft_graph.httpx.AsyncClient",
            return_value=_Client(),
        ):
            token = await provider._access_token(doctor)

        self.assertEqual(token, "new-access-token")
        self.assertEqual(doctor["refresh_token"], "rotated-refresh-token")

    async def test_validation_converts_graph_401_to_reauthorization_error(self):
        provider = MicrosoftGraphCalendarProvider()
        doctor = {
            "token": "access-token",
            "refresh_token": "refresh-token",
            "expires_at": 9999999999,
        }
        with patch(
            "app.services.scheduling.microsoft_graph.httpx.AsyncClient",
            return_value=_UnauthorizedClient(),
        ):
            with self.assertRaises(CalendarAuthorizationError):
                await provider.validate_connection(doctor)


if __name__ == "__main__":
    unittest.main()
