"""Risk engine payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import AlertLevel, DetectionMethod, HealthLevel, RiskDomain


class RuleOut(BaseModel):
    code: str
    domain: RiskDomain
    level: AlertLevel
    method: DetectionMethod
    title: str
    protocol: str | None
    conditions: list[str]
    any_of: list[str]


class EngineStatus(BaseModel):
    model_version: str
    last_run_at: datetime | None
    rules: list[RuleOut]


class MemberReportOut(BaseModel):
    code: str
    skipped: bool
    status: str | None
    global_score: float | None
    domains: dict[str, float]
    rules: list[str]
    pending_confirmation: list[str]
    anomaly_score: float | None
    new_alert_ids: list[int]


class EngineReport(BaseModel):
    computed_at: datetime
    model_version: str
    duration_ms: float
    members: list[MemberReportOut]


class AlertExplanation(BaseModel):
    alert_id: int
    rule_code: str | None
    method: DetectionMethod
    rule: str | None
    any_of: list[str]
    factors: list[Any]
    anomaly_score: float | None
    domain_score: float | None
    confirmations: int
    features: dict[str, Any]


class DomainPoint(BaseModel):
    t: datetime
    score: float
    level: HealthLevel


class DomainHistory(BaseModel):
    crew_id: str
    domain: RiskDomain
    score: float | None
    level: HealthLevel | None
    factors: list[Any]
    rules: list[str]
    history: list[DomainPoint]
