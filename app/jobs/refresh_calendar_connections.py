"""Refresh persisted Google and Microsoft calendar connection status."""

import asyncio

from app.services.doctor_service import doctor_service
from app.services.doctor_visibility import is_public_bookable_profile
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
    publicly_approved = [is_public_bookable_profile(doctor) for doctor in doctors]
    public_connected = sum(
        approved and connection_ok
        for approved, connection_ok in zip(publicly_approved, results)
    )
    demo_hidden = sum(doctor.get("is_demo") is True for doctor in doctors)
    pending_publication = sum(
        doctor.get("is_demo") is not True and not approved
        for doctor, approved in zip(doctors, publicly_approved)
    )
    print(
        "Calendar health refresh complete: "
        f"{connected}/{len(doctors)} connected; "
        f"{public_connected}/{sum(publicly_approved)} public clinicians bookable; "
        f"{demo_hidden} demo hidden; {pending_publication} awaiting publication settings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(refresh_all_connections()))
