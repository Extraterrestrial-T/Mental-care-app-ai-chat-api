"""Refresh persisted Google and Microsoft calendar connection status."""

import asyncio

from app.services.doctor_service import doctor_service
from app.services.firebase_service import firebase_service


async def refresh_all_connections() -> int:
    doctors = await firebase_service.get_all_doctors()
    if not doctors:
        print("No doctors found")
        return 0

    semaphore = asyncio.Semaphore(5)

    async def refresh(doctor):
        async with semaphore:
            return await doctor_service.verify_calendar_connection(doctor, force=True)

    results = await asyncio.gather(
        *(refresh(doctor) for doctor in doctors)
    )
    connected = sum(results)
    print(f"Calendar health refresh complete: {connected}/{len(doctors)} connected")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(refresh_all_connections()))
