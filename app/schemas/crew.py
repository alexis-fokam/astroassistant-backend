"""Authentication, mission, crew and status payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AccessRole, CrewRole, HealthLevel, MissionDestination, Sex
from app.schemas.alerts import AlertOut
from app.schemas.common import OrmModel


class LoginRequest(BaseModel):
    code: str = Field(examples=["AV-02"])
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$", examples=["2222"])


class MemberOut(OrmModel):
    code: str
    first_name: str
    last_name: str
    crew_role: CrewRole
    access_role: AccessRole
    sex: Sex | None
    mission_start_date: date


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    member: MemberOut


class MissionOut(OrmModel):
    code: str
    name: str
    destination: MissionDestination
    start_date: date
    planned_duration_days: int
    flight_profile: str
    one_way_latency_s: int
    day_length_min: int
    mission_day: int
    mission_time: datetime
    clock: str = Field(description="Horloge de mission, ex. « J+142 · 14:05 »")
    next_contact_at: datetime | None
    next_contact_time: str | None
    next_contact_in_s: int | None


class Factor(BaseModel):
    feature: str
    value: Any
    baseline: Any | None = None
    contribution: float


class CrewSummary(BaseModel):
    code: str
    first_name: str
    last_name: str
    crew_role: CrewRole
    is_cmo: bool
    status: HealthLevel | None
    global_score: float | None
    top_alert: str | None


class CrewStatus(BaseModel):
    """Current status of one member (spec §10.1)."""

    crew_id: str
    timestamp: datetime | None
    status: HealthLevel | None
    global_score: float | None
    domains: dict[str, float]
    top_factors: list[Factor]
    recommended_protocol: str | None
    active_alerts: list[AlertOut]


class CrewProfile(BaseModel):
    code: str
    first_name: str
    last_name: str
    crew_role: CrewRole
    is_cmo: bool
