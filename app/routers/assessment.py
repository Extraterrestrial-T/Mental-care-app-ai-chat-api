"""Public assessment endpoints with deterministic validation and no LLM usage."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.services.assessment_service import (
    assessment_schema,
    evaluate_assessment,
    normalize_assessment_contact,
)
from app.services.firebase_service import firebase_service


router = APIRouter(prefix="/api/assessments", tags=["assessments"])


class AssessmentContact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=3, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    phone: str = Field(min_length=8, max_length=30)


class SafetyFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wished_dead: bool | None = None
    better_off_dead: bool | None = None
    thoughts_killing: bool | None = None
    attempted: bool | None = None
    current_thoughts: bool | None = None


class AssessmentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    age: int = Field(ge=12, le=25)
    instrument: Literal["phq-a", "phq-9"]
    instrument_version: str
    answers: list[int] = Field(min_length=9, max_length=9)
    functional_difficulty: str
    past_year_depressed: bool | None = None
    safety_followup: SafetyFollowup | None = None
    contact: AssessmentContact
    consent_to_submit: bool
    emergency_notice_acknowledged: bool
    hospital_id: str | None = None


@router.get("/schema")
async def get_assessment_schema(response: Response, age: int = Query(ge=12, le=25)):
    response.headers["Cache-Control"] = "no-store"
    return assessment_schema(age)


@router.post("/submit", status_code=status.HTTP_201_CREATED)
async def submit_assessment(payload: AssessmentSubmission, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not payload.consent_to_submit or not payload.emergency_notice_acknowledged:
        raise HTTPException(status_code=422, detail="Consent and the emergency-service notice are required")

    expected = assessment_schema(payload.age)
    if payload.instrument != expected["instrument"] or payload.instrument_version != expected["version"]:
        raise HTTPException(status_code=409, detail="The assessment form changed. Reload it before submitting")

    try:
        result = evaluate_assessment(
            age=payload.age,
            answers=payload.answers,
            functional_difficulty=payload.functional_difficulty,
            past_year_depressed=payload.past_year_depressed,
            safety_followup=payload.safety_followup.model_dump() if payload.safety_followup else None,
        )
        contact = normalize_assessment_contact(payload.contact.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    assessment_id = str(uuid4())
    review_status = {
        "immediate": "requires_immediate_action",
        "priority_review": "priority_clinical_review",
        "routine": "pending_clinical_review",
    }[result["safety_level"]]
    record = {
        "id": assessment_id,
        "hospital_id": payload.hospital_id or settings.DEFAULT_HOSPITAL_ID,
        "age": payload.age,
        "contact": contact,
        **result,
        "consent_to_submit": True,
        "emergency_notice_acknowledged": True,
        "status": review_status,
        "source": "web_assessment",
        "created_at": datetime.now(timezone.utc),
    }
    if not await firebase_service.save_mental_health_assessment(assessment_id, record):
        raise HTTPException(status_code=503, detail="The check-in could not be saved. Please try again")

    return {
        "assessment_id": assessment_id,
        "submitted": True,
        "requires_immediate_action": result["requires_immediate_action"],
        "safety_level": result["safety_level"],
        "message": (
            f"Call {settings.EMERGENCY_PHONE} now or go to the nearest emergency department. "
            f"Call or text {settings.CRISIS_LIFELINE_PHONE}, or call Corner Health's after-hours "
            f"psychiatric number at {settings.PSYCHIATRIC_EMERGENCY_PHONE}. Stay with a trusted "
            "person. This form is not monitored as an emergency service."
            if result["requires_immediate_action"]
            else "Your check-in was submitted for staff review. This screening is not a diagnosis."
        ),
    }
