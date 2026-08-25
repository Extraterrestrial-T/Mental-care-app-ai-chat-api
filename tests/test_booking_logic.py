import unittest

from app.agent.booking_logic import (
    apply_message_corrections,
    asks_about_therapy_process,
    closing_response,
    contains_crisis_signal,
    declines_booking,
    extract_age_from_message,
    expresses_low_mood,
    invites_supportive_conversation,
    is_gratitude,
    normalize_contact_details,
    requests_assessment,
    requests_booking,
    requests_stress_relief,
    reset_booking_state,
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
        self.assertEqual(safety_status("I have thoughts of hurting myself"), "unsafe")
        self.assertEqual(safety_status("I want to die"), "unsafe")
        self.assertEqual(safety_status("I am safe"), "safe")
        self.assertTrue(contains_crisis_signal("I have thoughts of hurting myself"))
        self.assertFalse(contains_crisis_signal("No"))

    def test_combined_unsafe_booking_message_retains_booking_intent(self):
        self.assertTrue(requests_booking("I do not feel safe and need to book an appointment"))
        self.assertFalse(requests_booking("I do not feel safe right now"))

    def test_booking_decline_is_explicit_and_does_not_match_information_questions(self):
        self.assertTrue(declines_booking("I don't want to book"))
        self.assertTrue(declines_booking("Please cancel the booking"))
        self.assertTrue(declines_booking("not booking"))
        self.assertTrue(declines_booking("I'm not booking"))
        self.assertTrue(declines_booking("I'm not interested in seeing a doctor"))
        self.assertTrue(declines_booking("I don't need an appointment"))
        self.assertFalse(declines_booking("How do I book?"))

    def test_booking_requires_affirmative_action(self):
        self.assertTrue(requests_booking("I want to book an appointment"))
        self.assertTrue(requests_booking("Can you help me schedule a session?"))
        self.assertTrue(requests_booking("I need to see a therapist"))
        self.assertFalse(requests_booking("not booking"))
        self.assertFalse(requests_booking("I'm not interested in seeing a doctor"))
        self.assertFalse(requests_booking("I don't need an appointment"))
        self.assertFalse(requests_booking("What appointments are available?"))

    def test_assessment_requests_are_detected_without_treating_support_as_assessment(self):
        self.assertTrue(requests_assessment("Can I complete the PHQ-9?"))
        self.assertTrue(requests_assessment("I want a mental health check-in"))
        self.assertFalse(requests_assessment("I have been feeling low"))

    def test_therapy_process_question_is_not_automatically_a_booking(self):
        message = "If I wanted to get therapy, how does that work?"
        self.assertTrue(asks_about_therapy_process(message))
        self.assertTrue(asks_about_therapy_process("If I wanted theraoth, how does that work?"))
        self.assertFalse(requests_booking(message))

    def test_supportive_conversation_requests_are_detected(self):
        self.assertTrue(expresses_low_mood("im sad what do i do"))
        self.assertTrue(invites_supportive_conversation("can i talk to u instead"))
        self.assertTrue(invites_supportive_conversation("so you cant cheer me up"))
        self.assertTrue(requests_stress_relief("give me stress releif tips"))

    def test_booking_reset_clears_selection_and_sensitive_intake(self):
        updates = reset_booking_state()
        self.assertIsNone(updates["selected_doctor_id"])
        self.assertIsNone(updates["user_email"])
        self.assertFalse(updates["booking_initiated"])
        self.assertFalse(updates["booking_ready_for_calendar"])

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
