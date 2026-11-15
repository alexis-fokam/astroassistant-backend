from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.models.enums import (
    DataSource,
    ExerciseIntensity,
    ExerciseKind,
    SessionStatus,
)

T = TypeVar("T")


class PaginatedOut[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class CheckinDetailOut(BaseModel):
    id: int
    scheduled_for: datetime | None
    submitted_at: datetime
    duration_seconds: int | None
    headache: int | None
    vision_change: int | None
    congestion: int | None
    back_pain: int | None
    nausea: int | None
    sleep_quality: int | None
    mood: int | None
    stress: int | None
    isolation: int | None
    energy: int | None
    notes: str | None


class SleepOut(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime
    quality: int | None
    awakenings: int | None
    latency_min: int | None
    source: DataSource


class ExerciseDetailOut(BaseModel):
    id: int
    kind: ExerciseKind
    status: SessionStatus
    scheduled_at: datetime
    started_at: datetime | None
    duration_min: int | None
    intensity: ExerciseIntensity | None
    avg_heart_rate: float | None
    notes: str | None


class PvtDetailOut(BaseModel):
    id: int
    taken_at: datetime
    duration_seconds: int
    stimuli_count: int
    median_rt_ms: float
    lapses: int
    false_starts: int
