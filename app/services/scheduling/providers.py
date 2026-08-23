from typing import Any, Dict

from .base import CalendarProvider
from .google_calendar import GoogleCalendarProvider
from .microsoft_graph import MicrosoftGraphCalendarProvider


_PROVIDERS: dict[str, CalendarProvider] = {
    "google": GoogleCalendarProvider(),
    "microsoft": MicrosoftGraphCalendarProvider(),
}


def get_calendar_provider(token_data: Dict[str, Any]) -> CalendarProvider:
    """Resolve the correct calendar provider for a doctor record."""
    provider_name = token_data.get("calendar_provider") or "google"
    provider = _PROVIDERS.get(provider_name)

    if not provider:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Unsupported calendar provider '{provider_name}'. Supported: {supported}")

    return provider
