import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

try:
    from app.services.doctor_service import DoctorService
except (ModuleNotFoundError, RuntimeError):
    DoctorService = None


@unittest.skipIf(DoctorService is None, "application dependencies are not installed")
class DoctorDtoTests(unittest.TestCase):
    def test_safe_doctor_is_websocket_json_serializable(self):
        doctor = {
            "id": "doctor-1",
            "name": "Ada Lovelace",
            "calendar_provider": "microsoft",
            "calendar_connected": True,
            "calendar_status": "connected",
            "calendar_last_checked_at": datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc),
            "linked_at": datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
        }

        with patch("app.services.doctor_service.get_calendar_provider") as provider_factory:
            provider_factory.return_value.provider_name = "microsoft"
            payload = DoctorService._safe_doctor(doctor)

        encoded = json.dumps(payload)
        self.assertIn("2026-08-24T12:30:00+00:00", encoded)
        self.assertIn("2026-08-20T09:00:00+00:00", encoded)

    def test_safe_doctor_does_not_invent_provider_without_credentials(self):
        payload = DoctorService._safe_doctor(
            {
                "id": "doctor-2",
                "name": "No Calendar",
                "calendar_connected": False,
                "calendar_status": "reauthorization_required",
            }
        )

        self.assertIsNone(payload["calendar_provider"])

    def test_safe_doctor_identifies_legacy_google_credentials(self):
        payload = DoctorService._safe_doctor(
            {
                "id": "doctor-3",
                "name": "Legacy Doctor",
                "calendar_connected": True,
                "calendar_status": "connected",
                "token": "access-token",
                "refresh_token": "refresh-token",
            }
        )

        self.assertEqual(payload["calendar_provider"], "google")


if __name__ == "__main__":
    unittest.main()
