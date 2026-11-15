"""Alert and emergency payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    AlertLevel,
    AlertStatus,
    DetectionMethod,
    EmergencyStatus,
    Metric,
    RiskDomain,
)
from app.schemas.common import OrmModel


class AlertOut(OrmModel):
    id: int
    crew_code: str
    level: AlertLevel
    domain: RiskDomain
    domain_label: str | None
    method: DetectionMethod
    rule_code: str | None
    status: AlertStatus
    title: str
    message: str
    metric: Metric | None
    observed_value: float | None
    threshold: float | None
    factors: list[Any]
    recommended_protocol: str | None
    triggered_at: datetime
    ground_received_at: datetime | None = None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    ack_comment: str | None
    resolved_at: datetime | None


class AlertPatch(BaseModel):
    """Acknowledge (with a comment, F9.2) or resolve an alert."""

    status: Literal["acknowledged", "resolved"]
    comment: str | None = Field(default=None, max_length=2000)


class EmergencyIn(BaseModel):
    patient_code: str | None = Field(default=None, description="Défaut : soi-même")


class EmergencyStep(BaseModel):
    code: str


class EmergencyClose(BaseModel):
    outcome: Literal["stabilisée", "surveillance rapprochée", "évacuation demandée"]
    summary: str = Field(min_length=1, max_length=4000)


class EmergencyOut(OrmModel):
    id: int
    patient_code: str | None
    triggered_by_code: str | None
    status: EmergencyStatus
    triggered_at: datetime
    steps: list[Any]
    outcome: str | None
    closed_at: datetime | None
    summary: str | None
