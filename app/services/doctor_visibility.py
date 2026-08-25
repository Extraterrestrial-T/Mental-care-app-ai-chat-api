"""Pure public-listing rules for clinician profiles."""

from typing import Any


def is_public_bookable_profile(doctor: dict[str, Any]) -> bool:
    """Return true only for real clinicians approved for the public widget."""
    return (
        doctor.get("published_on_website") is True
        and doctor.get("accepting_online_bookings") is True
        and doctor.get("is_demo") is not True
    )
