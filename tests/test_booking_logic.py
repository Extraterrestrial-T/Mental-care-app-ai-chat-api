import unittest

from app.agent.booking_logic import (
    apply_message_corrections,
    closing_response,
    extract_age_from_message,
    is_gratitude,
    normalize_contact_details,
    requests_booking,
    safety_status,
)


class BookingLogicTests(unittest.TestCase):
    def test_extracts_age_from_natural_booking_message(self):
        self.assertEqual(extract_age_from_message("I'm 18 years old and need support"), 18)

    def test_age_correction_reopens_completed_booking_state(self):
        updates = apply_message_corrections(
            {
                "user_age": 28,
                "eligibility_status": "ineligible",
                "booking_initiated": False,
                "booking_completed": True,
            },
            "Sorry, I meant that I am 18 years old",
        )
        self.assertEqual(updates["user_age"], 18)
        self.assertIsNone(updates["eligibility_status"])
        self.assertTrue(updates["correction_detected"])
        self.assertFalse(updates["booking_completed"])

    def test_unrelated_message_does_not_reopen_booking(self):
        self.assertEqual(
            apply_message_corrections({"user_age": 18}, "Thank you"),
            {"correction_detected": False},
        )

    def test_short_gratitude_is_a_terminal_acknowledgement(self):
        self.assertTrue(is_gratitude("Thank you"))
        self.assertTrue(is_gratitude("Okay, thanks!"))
        self.assertFalse(is_gratitude("Thank you, I also need to book an appointment"))
        self.assertEqual(closing_response("Thank you"), "You're welcome.")
        self.assertEqual(
            closing_response("Thanks", booking_completed=True),
            "You're welcome. Your appointment is confirmed.",
        )
        self.assertIsNone(closing_response("I need another appointment"))

    def test_unsafe_language_is_detected(self):
        self.assertEqual(safety_status("No, I do not feel safe"), "unsafe")
        self.assertEqual(safety_status("I am safe"), "safe")

    def test_combined_unsafe_booking_message_retains_booking_intent(self):
        self.assertTrue(requests_booking("I do not feel safe and need to book an appointment"))
        self.assertFalse(requests_booking("I do not feel safe right now"))

    def test_contact_form_is_normalized(self):
        details = normalize_contact_details(
            {
                "full_name": " Ada   Lovelace ",
                "email": "ADA@Example.com",
                "phone": "+1 (734) 555-0123",
                "sms_call_consent": True,
            }
        )
        self.assertEqual(details["user_Fname"], "Ada")
        self.assertEqual(details["user_Lname"], "Lovelace")
        self.assertEqual(details["user_email"], "ada@example.com")
        self.assertEqual(details["user_phonenumber"], "+17345550123")
        self.assertEqual(details["sms_call_consent"], "yes")

    def test_contact_form_rejects_incomplete_name_and_local_phone(self):
        with self.assertRaises(ValueError):
            normalize_contact_details(
                {
                    "full_name": "Ada",
                    "email": "ada@example.com",
                    "phone": "7345550123",
                }
            )


if __name__ == "__main__":
    unittest.main()
