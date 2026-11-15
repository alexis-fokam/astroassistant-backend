"""Protocol, pharmacy and report payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import AlertLevel, ProtocolRunStatus, RiskDomain
from app.schemas.common import OrmModel


class ProtocolStepOut(BaseModel):
    code: str
    title: str
    duration_min: float | None = None
    timer: bool = False


class ProtocolMaterialOut(BaseModel):
    item_code: str
    name: str
    quantity: float
    in_stock: float
    available: bool
    optional: bool


class ProtocolSummary(OrmModel):
    code: str
    version: str
    title: str
    domain: RiskDomain | None
    severity: AlertLevel
    expected_duration_min: int | None


class ProtocolOut(ProtocolSummary):
    description: str | None
    trigger: dict[str, Any]
    exit_criterion: str | None
    steps: list[ProtocolStepOut]
    materials: list[ProtocolMaterialOut]
    ready: bool = Field(description="Tout le matériel obligatoire est disponible (F11.2)")
    checksum: str


class RunCreate(BaseModel):
    crew_code: str | None = None
    alert_id: int | None = None


class RunPatch(BaseModel):
    """Validate the next step, or close the run."""

    step_code: str | None = None
    status: Literal["completed", "aborted"] | None = None
    efficacy: float | None = Field(default=None, ge=0, le=1)


class RunOut(OrmModel):
    id: int
    protocol_code: str
    crew_code: str
    alert_id: int | None
    status: ProtocolRunStatus
    steps: list[Any]
    next_step: str | None
    started_at: datetime
    ended_at: datetime | None
    efficacy: float | None


class InventoryItemOut(OrmModel):
    code: str
    name: str
    category: str | None
    unit: str
    quantity: float
    min_quantity: float
    expires_on: date | None
    location: str | None
    is_low_stock: bool
    is_expired: bool


class UsageIn(BaseModel):
    """Record a pharmacy use; CMO only (F11.3). Decrements the stock."""

    item_code: str
    quantity: float = Field(gt=0)
    patient_code: str | None = None
    protocol_run_id: int | None = None
    emergency_id: int | None = None
    note: str | None = Field(default=None, max_length=2000)


class UsageOut(OrmModel):
    id: int
    item_code: str
    quantity: float
    remaining: float
    used_at: datetime

# --- Nouveau schéma pour GET /inventory/usages ---
class UsageLogOut(OrmModel):
    id: int
    item_code: str
    item_name: str
    unit: str
    quantity: float
    patient_code: str | None
    recorded_by_code: str
    protocol_run_id: int | None
    emergency_id: int | None
    used_at: datetime
    note: str | None


class ReportOut(BaseModel):
    """Weekly synthesis of one member (spec §10 GET /reports)."""

    crew_id: str
    period_start: datetime
    period_end: datetime
    status: str | None
    global_score: float | None
    vitals: dict[str, dict[str, float]]
    sleep_hours_avg: float | None
    exercise_completed: int
    exercise_missed: int
    pvt_median_rt_ms: float | None
    pvt_lapses: int
    checkins: int
    dose_received_msv: float
    alerts: dict[str, int]

class ConsultationIn(BaseModel):
    alert_id: int | None = Field(
        default=None, description="ID de l'alerte à l'origine de la consultation"
    )
    title: str = Field(..., min_length=1, max_length=160, description="Motif de consultation")
    body: str = Field(..., min_length=1, description="Observations et conduite à tenir")


class ConsultationOut(OrmModel):
    id: int
    patient_code: str
    author_code: str | None
    author_name: str | None
    alert_id: int | None
    written_at: datetime
    title: str
    body: str
