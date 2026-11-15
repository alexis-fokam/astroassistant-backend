"""Données échangées pour les protocoles, la pharmacie et les rapports."""

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
    """Valider l'étape suivante, ou clôturer l'exécution."""

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


class RunListItem(RunOut):
    """Une exécution de protocole avec ce dont l'écran « Mes protocoles » a besoin (F4.5)."""

    protocol_title: str
    severity: AlertLevel
    expected_duration_min: int | None
    total_steps: int
    trigger: str | None = Field(description="Règle et titre de l'alerte déclenchante")


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
    """Enregistrer une utilisation en pharmacie ; CMO uniquement (F11.3). Décrémente le stock."""

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


class ReportOut(BaseModel):
    """Synthèse hebdomadaire d'un membre (§10 GET /reports)."""

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
