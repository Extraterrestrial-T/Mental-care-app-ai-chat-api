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
    unsafe_phrases = ("not safe", "unsafe", "don't feel safe", "do not feel safe", "in danger")
    if normalized in {"no", "nope", "n"} or any(phrase in normalized for phrase in unsafe_phrases):
        return "unsafe"
    if normalized in {"yes", "y", "safe", "i am safe", "i'm safe", "im safe"}:
        return "safe"
    return "unknown"


def requests_booking(message: str) -> bool:
    return bool(
        re.search(
            r"\b(book|booking|appointment|schedule|see (?:a |the )?(?:doctor|therapist|counselor))\b",
            message,
            flags=re.IGNORECASE,
        )
    )


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
