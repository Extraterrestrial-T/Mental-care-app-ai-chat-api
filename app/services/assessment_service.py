"""Deterministic mental-health screening definitions and scoring.

These functions do not diagnose, recommend treatment, or use an LLM. Clinical
owners must approve the instruments and escalation workflow before production use.
"""

import re
from typing import Any, Literal


ASSESSMENT_VERSION = "2026-08-25.1"
ANSWER_OPTIONS = (
    {"value": 0, "label": "Not at all"},
    {"value": 1, "label": "Several days"},
    {"value": 2, "label": "More than half the days"},
    {"value": 3, "label": "Nearly every day"},
)

PHQ9_QUESTIONS = (
    "Little interest or pleasure in doing things?",
    "Feeling down, depressed, or hopeless?",
    "Trouble falling or staying asleep, or sleeping too much?",
    "Feeling tired or having little energy?",
    "Poor appetite or overeating?",
    "Feeling bad about yourself, or that you are a failure or have let yourself or your family down?",
    "Trouble concentrating on things, such as reading or watching television?",
    "Moving or speaking so slowly that other people could have noticed, or being so fidgety or restless that you moved more than usual?",
    "Thoughts that you would be better off dead or of hurting yourself in some way?",
)

PHQA_QUESTIONS = (
    "Feeling down, depressed, irritable, or hopeless?",
    "Little interest or pleasure in doing things?",
    "Trouble falling asleep, staying asleep, or sleeping too much?",
    "Poor appetite, weight loss, or overeating?",
    "Feeling tired or having little energy?",
    "Feeling bad about yourself, or that you are a failure or have let yourself or your family down?",
    "Trouble concentrating on things like school work, reading, or watching television?",
    "Moving or speaking so slowly that other people could have noticed, or being so fidgety or restless that you moved more than usual?",
    "Thoughts that you would be better off dead or of hurting yourself in some way?",
)

ASQ_QUESTIONS = (
    {"id": "wished_dead", "text": "In the past few weeks, have you wished you were dead?"},
    {"id": "better_off_dead", "text": "In the past few weeks, have you felt that you or your family would be better off if you were dead?"},
    {"id": "thoughts_killing", "text": "In the past week, have you been having thoughts about killing yourself?"},
    {"id": "attempted", "text": "Have you ever tried to kill yourself?"},
)

FUNCTION_OPTIONS = (
    "Not difficult at all",
    "Somewhat difficult",
    "Very difficult",
    "Extremely difficult",
)


def instrument_for_age(age: int) -> Literal["phq-a", "phq-9"]:
    if age < 12 or age > 25:
        raise ValueError("This check-in is available to people ages 12 to 25")
    return "phq-a" if age < 18 else "phq-9"


def assessment_schema(age: int) -> dict[str, Any]:
    instrument = instrument_for_age(age)
    questions = PHQA_QUESTIONS if instrument == "phq-a" else PHQ9_QUESTIONS
    return {
        "instrument": instrument,
        "version": ASSESSMENT_VERSION,
        "timeframe": "During the past two weeks",
        "questions": [
            {"id": index + 1, "text": text, "options": ANSWER_OPTIONS}
            for index, text in enumerate(questions)
        ],
        "functional_difficulty_options": FUNCTION_OPTIONS,
        "asks_past_year_depressed": instrument == "phq-a",
        "safety_followup_questions": ASQ_QUESTIONS,
    }


def normalize_assessment_contact(payload: dict[str, Any]) -> dict[str, str]:
    full_name = " ".join(str(payload.get("full_name", "")).split())
    if len(full_name.split()) < 2:
        raise ValueError("Enter a first name and surname")

    email = str(payload.get("email", "")).strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Enter a valid email address")

    phone = re.sub(r"[^\d+]", "", str(payload.get("phone", "")))
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise ValueError("Phone number must include a country code")
    return {"full_name": full_name, "email": email, "phone": phone}


def evaluate_assessment(
    *,
    age: int,
    answers: list[int],
    functional_difficulty: str,
    safety_followup: dict[str, bool | None] | None,
    past_year_depressed: bool | None,
) -> dict[str, Any]:
    instrument = instrument_for_age(age)
    if len(answers) != 9 or any(type(answer) is not int or answer not in range(4) for answer in answers):
        raise ValueError("Exactly nine answers between 0 and 3 are required")
    if functional_difficulty not in FUNCTION_OPTIONS:
        raise ValueError("Select how difficult these concerns have made daily life")
    if instrument == "phq-a" and past_year_depressed is None:
        raise ValueError("The past-year mood question is required")

    item_9_positive = answers[8] > 0
    normalized_followup = safety_followup or {}
    primary_ids = tuple(question["id"] for question in ASQ_QUESTIONS)
    if item_9_positive and any(normalized_followup.get(key) is None for key in primary_ids):
        raise ValueError("Safety follow-up answers are required when item 9 is positive")

    primary_positive = any(normalized_followup.get(key) is True for key in primary_ids)
    if item_9_positive and primary_positive and normalized_followup.get("current_thoughts") is None:
        raise ValueError("The current-safety question is required after a positive safety answer")

    current_thoughts = normalized_followup.get("current_thoughts") is True
    if current_thoughts:
        safety_level = "immediate"
    elif item_9_positive or primary_positive:
        safety_level = "priority_review"
    else:
        safety_level = "routine"

    return {
        "instrument": instrument,
        "instrument_version": ASSESSMENT_VERSION,
        "answers": answers,
        "total_score": sum(answers),
        "functional_difficulty": functional_difficulty,
        "past_year_depressed": past_year_depressed if instrument == "phq-a" else None,
        "item_9_positive": item_9_positive,
        "safety_followup": normalized_followup if item_9_positive else None,
        "safety_level": safety_level,
        "requires_immediate_action": safety_level == "immediate",
    }
