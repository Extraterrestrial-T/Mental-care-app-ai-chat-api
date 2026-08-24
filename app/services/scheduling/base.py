from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional


class CalendarAuthorizationError(RuntimeError):
    """A stored provider authorization can no longer be refreshed."""


class CalendarProvider(ABC):
    """Calendar provider interface used by booking services."""

    provider_name: str

    def is_connected(self, token_data: Dict[str, Any]) -> bool:
        return all(
            [
                token_data.get("calendar_provider") == self.provider_name,
                token_data.get("token"),
                token_data.get("refresh_token"),
            ]
        )

    @abstractmethod
    async def validate_connection(self, token_data: Dict[str, Any]) -> None:
        """Refresh credentials if needed and verify that the calendar is reachable."""

    @abstractmethod
    async def get_available_slots(
        self,
        token_data: Dict[str, Any],
        date: datetime,
        duration_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        """Return available appointment slots for one provider on one day."""

    @abstractmethod
    async def create_appointment(
        self,
        token_data: Dict[str, Any],
        patient_name: str,
        patient_email: str,
        start_time: datetime,
        end_time: datetime,
        notes: Optional[str] = None,
    ) -> Optional[str]:
        """Create an appointment and return the provider event ID."""

    @abstractmethod
    async def cancel_appointment(
        self,
        token_data: Dict[str, Any],
        event_id: str,
    ) -> bool:
        """Cancel an appointment by provider event ID."""

    @abstractmethod
    async def get_upcoming_appointments(
        self,
        token_data: Dict[str, Any],
        days: int = 7,
    ) -> List[Dict[str, Any]]:
        """Return upcoming provider calendar events."""
