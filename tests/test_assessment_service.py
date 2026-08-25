import unittest

from app.services.assessment_service import (
    ASSESSMENT_VERSION,
    assessment_schema,
    evaluate_assessment,
    instrument_for_age,
    normalize_assessment_contact,
)


class AssessmentServiceTests(unittest.TestCase):
    def test_age_selects_adolescent_and_adult_instruments(self):
        self.assertEqual(instrument_for_age(12), "phq-a")
        self.assertEqual(instrument_for_age(17), "phq-a")
        self.assertEqual(instrument_for_age(18), "phq-9")
        self.assertEqual(assessment_schema(18)["version"], ASSESSMENT_VERSION)

    def test_routine_assessment_scores_deterministically(self):
        result = evaluate_assessment(
            age=18,
            answers=[0, 1, 2, 3, 0, 1, 2, 3, 0],
            functional_difficulty="Somewhat difficult",
            past_year_depressed=None,
            safety_followup=None,
        )
        self.assertEqual(result["total_score"], 12)
        self.assertEqual(result["safety_level"], "routine")

    def test_positive_item_nine_requires_complete_safety_followup(self):
        with self.assertRaises(ValueError):
            evaluate_assessment(
                age=18,
                answers=[0] * 8 + [1],
                functional_difficulty="Somewhat difficult",
                past_year_depressed=None,
                safety_followup=None,
            )

    def test_current_suicidal_thoughts_require_immediate_action(self):
        result = evaluate_assessment(
            age=16,
            answers=[0] * 8 + [1],
            functional_difficulty="Very difficult",
            past_year_depressed=True,
            safety_followup={
                "wished_dead": True,
                "better_off_dead": False,
                "thoughts_killing": False,
                "attempted": False,
                "current_thoughts": True,
            },
        )
        self.assertTrue(result["requires_immediate_action"])
        self.assertEqual(result["safety_level"], "immediate")

    def test_contact_is_normalized(self):
        self.assertEqual(
            normalize_assessment_contact(
                {"full_name": " Ada  Lovelace ", "email": "ADA@example.com", "phone": "+1 (734) 555-0123"}
            ),
            {"full_name": "Ada Lovelace", "email": "ada@example.com", "phone": "+17345550123"},
        )


if __name__ == "__main__":
    unittest.main()
