from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import HealthLevel, RiskDomain


class DomainFactor(BaseModel):
    feature: str
    value: float | str | None = None
    baseline: float | str | None = None
    contribution: float | None = None


class DomainScorePoint(BaseModel):
    t: datetime
    score: float = Field(..., ge=0, le=100)
    level: HealthLevel
    anomaly_score: float | None = Field(default=None, ge=0, le=1)
    factors: list[DomainFactor] = []


class CrewDomainHistoryOut(BaseModel):
    crew_id: str
    domain: RiskDomain
    current_score: float | None = None
    current_level: HealthLevel | None = None
    latest_factors: list[DomainFactor] = []
    history: list[DomainScorePoint] = []
