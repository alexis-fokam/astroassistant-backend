"""Données envoyées : constantes, radiation, check-in, exercice et PVT."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ExerciseIntensity, ExerciseKind, HealthLevel, Metric, SessionStatus
from app.schemas.common import OrmModel


class VitalIn(BaseModel):
    metric: Metric
    value: float
    recorded_at: datetime
    quality: float | None = Field(default=None, ge=0, le=1)


class VitalBatch(BaseModel):
    """Lot de mesures pour un membre (§10 POST /vitals)."""

    crew_code: str | None = Field(default=None, description="Défaut : soi-même")
    device_serial: str | None = None
    readings: list[VitalIn] = Field(min_length=1, max_length=5000)


class VitalBatchResult(BaseModel):
    accepted: int


class VitalPoint(BaseModel):
    t: datetime
    value: float
    quality: float | None
    is_artifact: bool


class VitalSeries(BaseModel):
    crew_id: str
    metric: Metric
    unit: str
    baseline_mean: float | None
    baseline_std: float | None
    points: list[VitalPoint]


class NormalBand(BaseModel):
    low: float
    high: float


class VitalLatestItem(BaseModel):
    metric: Metric
    value: float | None = None
    unit: str
    level: HealthLevel = HealthLevel.NOMINAL
    trend_pct: float | None = None
    normal_band: NormalBand | None = None
    recorded_at: datetime | None = None
    points: list[VitalPoint] = []


class CrewVitalsLatest(BaseModel):
    crew_id: str
    vitals: dict[Metric, VitalLatestItem]


class RadiationPoint(BaseModel):
    t: datetime
    dose_rate_msv_h: float
    mission_cumulative_msv: float


class RadiationOut(BaseModel):
    """Dose cumulée, débit actuel et projection (F5.1, F5.2)."""

    crew_id: str
    recorded_at: datetime | None
    dose_rate_msv_h: float | None
    neutron_fraction: float | None
    mission_cumulative_msv: float
    career_cumulative_msv: float
    career_limit_msv: float
    career_used_pct: float
    daily_average_msv: float
    projected_mission_end_msv: float
    projected_career_end_msv: float
    history: list[RadiationPoint]


class CheckinIn(BaseModel):
    """Check-in quotidien (F3) : symptômes de 0 à 3, ressentis de 0 à 10."""

    crew_code: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    headache: int | None = Field(default=None, ge=0, le=3)
    vision_change: int | None = Field(default=None, ge=0, le=3)
    congestion: int | None = Field(default=None, ge=0, le=3)
    back_pain: int | None = Field(default=None, ge=0, le=3)
    nausea: int | None = Field(default=None, ge=0, le=3)
    dizziness: int | None = Field(default=None, ge=0, le=3)
    skin_issue: int | None = Field(default=None, ge=0, le=3)
    sleep_quality: int | None = Field(default=None, ge=0, le=10)
    mood: int | None = Field(default=None, ge=0, le=10)
    stress: int | None = Field(default=None, ge=0, le=10)
    isolation: int | None = Field(default=None, ge=0, le=10)
    energy: int | None = Field(default=None, ge=0, le=10)
    crew_relations: int | None = Field(default=None, ge=0, le=10)
    notes: str | None = Field(default=None, max_length=2000)


class CheckinOut(OrmModel):
    id: int
    submitted_at: datetime


class ExerciseIn(BaseModel):
    crew_code: str | None = None
    kind: ExerciseKind
    status: SessionStatus = SessionStatus.COMPLETED
    scheduled_at: datetime
    started_at: datetime | None = None
    duration_min: int | None = Field(default=None, gt=0)
    intensity: ExerciseIntensity | None = None
    avg_heart_rate: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class ExerciseOut(OrmModel):
    id: int
    kind: ExerciseKind
    status: SessionStatus
    scheduled_at: datetime
    duration_min: int | None


class PvtIn(BaseModel):
    crew_code: str | None = None
    taken_at: datetime | None = None
    duration_seconds: int = Field(default=180, gt=0)
    stimuli_count: int = Field(gt=0)
    median_rt_ms: float = Field(gt=0)
    lapses: int = Field(ge=0)
    false_starts: int = Field(default=0, ge=0)


class PvtOut(OrmModel):
    id: int
    taken_at: datetime
    median_rt_ms: float
    lapses: int
