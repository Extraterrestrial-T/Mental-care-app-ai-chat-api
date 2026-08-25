"""Deterministic booking rules shared by the LangGraph agent and unit tests."""

import re
from typing import Any, Literal


def parse_age(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def extract_age_from_message(message: str) -> int | None:
    patterns = (
        r"\b(?:i am|i'm|im|aged|age)\s+(\d{1,3})(?:\s*(?:years? old|yo|y/o))?\b",
        r"\b(\d{1,3})\s*(?:years? old|yo|y/o)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return parse_age(match.group(1))
    return None


def safety_status(value: Any) -> Literal["safe", "unsafe", "unknown"]:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip().lower()
    unsafe_phrases = (
        "not safe", "unsafe", "don't feel safe", "do not feel safe", "in danger",
        "kill myself", "hurt myself", "hurting myself", "harm myself", "harming myself",
        "end my life", "want to die",
        "wish i were dead", "suicidal", "suicide", "can't go on", "cannot go on",
    )
    if normalized in {"no", "nope", "n"} or any(phrase in normalized for phrase in unsafe_phrases):
        return "unsafe"
    if normalized in {"yes", "y", "safe", "i am safe", "i'm safe", "im safe"}:
        return "safe"
    return "unknown"


def contains_crisis_signal(message: str) -> bool:
    """Detect explicit danger/self-harm language without treating a bare 'no' as crisis."""
    if not isinstance(message, str):
        return False
    return bool(
        re.search(
            r"\b(?:not safe|unsafe|in danger|suicidal|suicide|want to die|wish i were dead|"
            r"(?:kill|hurt|harm|hurting|harming) myself|end my life|can(?:not|'t) go on)\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def requests_booking(message: str) -> bool:
    """Require affirmative scheduling intent rather than a booking keyword."""
    if declines_booking(message):
        return False
    return bool(
        re.search(
            r"\b(?:"
            r"(?:i\s+)?(?:want|would like|need|wish|hope|ready|trying)\s+(?:you\s+)?(?:to\s+)?"
            r"(?:book|schedule|arrange|make)\s+(?:me\s+)?(?:an?\s+)?(?:appointment|session)|"
            r"(?:can|could|would|will|may)\s+(?:i|you)\s+(?:please\s+)?(?:help\s+me\s+)?"
            r"(?:book|schedule|arrange|make)\s+(?:me\s+)?(?:an?\s+)?(?:appointment|session)|"
            r"(?:book|schedule|arrange|make)\s+(?:me\s+)?(?:an?\s+)?(?:appointment|session)|"
            r"(?:i\s+)?(?:want|would like|need)\s+to\s+see\s+(?:a|the)\s+"
            r"(?:doctor|therapist|counselor|clinician)|"
            r"(?:i\s+)?need\s+(?:an?\s+)?(?:appointment|therapy appointment|counseling appointment)"
            r")\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def declines_booking(message: str) -> bool:
    """Detect negative booking intent even when no booking is in progress."""
    return bool(
        re.search(
            r"\b(?:"
            r"(?:i(?:'m| am)?\s+)?not\s+(?:interested\s+in\s+)?(?:booking|scheduling)|"
            r"(?:i\s+)?(?:do not|don't|dont|no longer|never)\s+"
            r"(?:(?:want|need|plan|intend)\s+to\s+)?(?:book|schedule|continue(?:\s+booking)?)|"
            r"(?:i(?:'m| am)?\s+)?not\s+(?:interested\s+in\s+)?"
            r"(?:seeing|meeting|talking\s+to)\s+(?:a|the)\s+(?:doctor|therapist|counselor|clinician)|"
            r"(?:i\s+)?(?:do not|don't|dont)\s+(?:want|need)\s+(?:an?\s+)?(?:appointment|session)|"
            r"(?:no|not)\s+(?:appointment|booking)|"
            r"(?:stop|cancel)\s+(?:the\s+)?booking"
            r")\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def requests_assessment(message: str) -> bool:
    return bool(
        re.search(
            r"\b(?:phq(?:-?9|\s*a)?|mental health (?:check[ -]?in|assessment|screening)|risk assessment|screening questionnaire|assessment form)\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def asks_about_therapy_process(message: str) -> bool:
    """Detect questions about starting or experiencing therapy, not booking itself."""
    return bool(
        re.search(r"\b(?:thera[a-z]*|counsel(?:ing|ling)|mental health care)\b", message, re.IGNORECASE)
        and re.search(
            r"\b(?:how (?:does|do|would)|what (?:happens|is|should|can)|what to expect|"
            r"get started|start|first session|want(?:ed)? to get)\b",
            message,
            re.IGNORECASE,
        )
    )


def invites_supportive_conversation(message: str) -> bool:
    return bool(
        re.search(
            r"\b(?:can i (?:talk|chat) (?:to|with) (?:you|u)|will you listen|listen to me|"
            r"keep me company|cheer me up|someone to talk to|i want to talk about it)\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def requests_stress_relief(message: str) -> bool:
    return bool(
        re.search(
            r"\b(?:stress rel(?:ief|eif)|calm down|quick reset|grounding exercise|breathing exercise|"
            r"help me relax|feel less stressed|cope with stress)\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def expresses_low_mood(message: str) -> bool:
    """Detect simple low-mood disclosures after explicit crisis language is excluded."""
    return bool(
        re.search(
            r"\b(?:(?:i'm|im|i am) (?:sad|down|upset|lonely)|feeling (?:sad|down|upset|lonely)|"
            r"feel (?:sad|down|upset|lonely))\b",
            message,
            flags=re.IGNORECASE,
        )
    )


def reset_booking_state() -> dict[str, Any]:
    return {
        "user_age": None,
        "user_Fname": None,
        "user_Lname": None,
        "user_email": None,
        "user_phonenumber": None,
        "sms_call_consent": None,
        "intake_feeling": None,
        "intake_support_needed": None,
        "intake_safety_check": None,
        "intake_staff_notes": None,
        "eligibility_status": None,
        "booking_intake_extracted": False,
        "safety_guidance_acknowledged": False,
        "selected_doctor_id": None,
        "selected_doctor_name": None,
        "booking_initiated": False,
        "booking_ready_for_calendar": False,
        "booking_completed": False,
    }


def is_gratitude(message: str) -> bool:
    """Detect a short closing acknowledgement without reopening booking."""
    normalized = re.sub(r"[^a-z\s']", " ", message.lower())
    normalized = " ".join(normalized.split())
    return bool(
        re.fullmatch(
            r"(?:thank you|thanks|thank you so much|thanks so much|many thanks|okay thanks|ok thanks)",
            normalized,
        )
    )


def closing_response(message: str, *, booking_completed: bool = False) -> str | None:
    if not is_gratitude(message):
        return None
    if booking_completed:
        return "You're welcome. Your appointment is confirmed."
    return "You're welcome."


def apply_message_corrections(state: dict[str, Any], message: str) -> dict[str, Any]:
    """Return state updates for facts the user explicitly corrected."""
    extracted_age = extract_age_from_message(message)
    if extracted_age is None or state.get("user_age") is None:
        return {"correction_detected": False}
    return {
        "user_age": extracted_age,
        "eligibility_status": None,
        "booking_initiated": False,
        "booking_completed": False,
        "correction_detected": True,
    }


def normalize_contact_details(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Contact details must be submitted together")

    full_name = " ".join(str(payload.get("full_name", "")).split())
    name_parts = full_name.split()
    if len(name_parts) < 2:
        raise ValueError("Please enter a first and last name")

    email = str(payload.get("email", "")).strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Please enter a valid email address")

    phone = re.sub(r"[^\d+]", "", str(payload.get("phone", "")))
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise ValueError("Phone number must include a country code, for example +1 734 555 0123")

    return {
        "user_Fname": name_parts[0],
        "user_Lname": " ".join(name_parts[1:]),
        "user_email": email,
        "user_phonenumber": phone,
        "sms_call_consent": "yes" if bool(payload.get("sms_call_consent")) else "no",
    }
