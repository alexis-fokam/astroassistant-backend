"""Point d'entrée unique pour lever une alerte clinique (F2.7, F9.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, CrewMember, RiskScore
from app.models.enums import AlertLevel, AlertStatus, DetectionMethod, Metric, RiskDomain
from app.services import audit
from app.services import protocols as library


def open_alert(db: Session, member: CrewMember, rule_code: str) -> Alert | None:
    """Une alerte non résolue de la même règle pour ce membre, s'il y en a une."""
    return db.scalars(
        select(Alert).where(
            Alert.crew_member_id == member.id,
            Alert.rule_code == rule_code,
            Alert.status != AlertStatus.RESOLVED,
        )
    ).first()


def create_alert(
    db: Session,
    member: CrewMember,
    *,
    rule_code: str | None,
    level: AlertLevel,
    domain: RiskDomain,
    method: DetectionMethod,
    title: str,
    message: str,
    at: datetime,
    domain_label: str | None = None,
    metric: Metric | None = None,
    observed_value: float | None = None,
    threshold: float | None = None,
    factors: list[dict[str, Any]] | None = None,
    protocol_code: str | None = None,
    risk_score: RiskScore | None = None,
    sim_run_id: int | None = None,
    actor_label: str = "Moteur IA",
) -> Alert | None:
    """Créer, auditer et renvoyer l'alerte ; None si la même règle est déjà ouverte."""
    if rule_code and open_alert(db, member, rule_code):
        return None
    protocol = library.active_protocol(db, protocol_code) if protocol_code else None
    alert = Alert(
        crew_member_id=member.id,
        risk_score_id=risk_score.id if risk_score else None,
        recommended_protocol_id=protocol.id if protocol else None,
        sim_run_id=sim_run_id,
        level=level,
        domain=domain,
        domain_label=domain_label,
        method=method,
        rule_code=rule_code,
        title=title,
        message=message,
        metric=metric,
        observed_value=observed_value,
        threshold=threshold,
        factors=factors or [],
        triggered_at=at,
    )
    db.add(alert)
    audit.record(
        db,
        "alert.trigger",
        actor_label=actor_label,
        entity=alert,
        at=at,
        level=level.value,
        rule=rule_code,
        crew=member.code,
    )
    return alert
