import unittest
from datetime import datetime

try:
    from app.services.scheduling.google_calendar import GoogleCalendarProvider
except ModuleNotFoundError:
    GoogleCalendarProvider = None


@unittest.skipIf(GoogleCalendarProvider is None, "calendar dependencies are not installed")
class GoogleCalendarCredentialTests(unittest.TestCase):
    def test_stored_expiry_is_loaded_as_utc_for_google_auth(self):
        provider = GoogleCalendarProvider()
        credentials = provider._build_credentials(
            {
                "token": "access-token",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "scopes": ["calendar"],
                "token_expiry": "2026-08-25T09:35:14+00:00",
            }
        )

        self.assertEqual(credentials.expiry, datetime(2026, 8, 25, 9, 35, 14))


if __name__ == "__main__":
    unittest.main()
