import unittest

from app.services.doctor_visibility import is_public_bookable_profile


class DoctorVisibilityTests(unittest.TestCase):
    def test_only_explicitly_published_real_profiles_are_bookable(self):
        approved = {
            "published_on_website": True,
            "accepting_online_bookings": True,
            "is_demo": False,
        }
        self.assertTrue(is_public_bookable_profile(approved))
        self.assertFalse(is_public_bookable_profile({**approved, "is_demo": True}))
        self.assertFalse(is_public_bookable_profile({**approved, "published_on_website": False}))
        self.assertFalse(is_public_bookable_profile({**approved, "accepting_online_bookings": False}))
        self.assertFalse(is_public_bookable_profile({}))


if __name__ == "__main__":
    unittest.main()
