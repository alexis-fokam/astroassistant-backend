from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Alert
from app.schemas.alerts import AlertExplanationOut, AlertFactor


def _parse_factors(raw_factors: list[Any]) -> list[AlertFactor]:
    parsed: list[AlertFactor] = []
    for item in raw_factors:
        if isinstance(item, dict):
            label = item.get("label") or item.get("feature") or item.get("name") or "Facteur inconnu"
            parsed.append(
                AlertFactor(
                    label=str(label),
                    value=item.get("value"),
                    contribution=item.get("contribution"),
                )
            )
        elif isinstance(item, str):
            parsed.append(AlertFactor(label=item))
    return parsed


def _count_confirmations(db: Session, alert: Alert) -> int:
    """Compte le nombre d'occurrences confirmant cette alerte sur les 24 dernières heures."""
    window_start = alert.triggered_at - timedelta(hours=24)

    filters = [
        Alert.crew_member_id == alert.crew_member_id,
        Alert.triggered_at >= window_start,
        Alert.triggered_at <= alert.triggered_at,
    ]

    if alert.sim_run_id is not None:
        filters.append(Alert.sim_run_id == alert.sim_run_id)

    if alert.rule_code:
        filters.append(Alert.rule_code == alert.rule_code)
    elif alert.metric is not None:
        filters.append(Alert.metric == alert.metric)
    else:
        filters.append(Alert.domain == alert.domain)

    count = db.scalar(select(func.count(Alert.id)).where(*filters))
    return max(count or 1, 1)


def get_alert_explanation(db: Session, alert_id: int) -> tuple[Alert, AlertExplanationOut] | None:
    alert = db.scalars(
        select(Alert)
        .options(
            joinedload(Alert.crew_member),
            joinedload(Alert.risk_score),
        )
        .where(Alert.id == alert_id)
    ).first()

    if alert is None:
        return None

    # Utilise les facteurs de l'alerte, ou à défaut ceux du RiskScore associé
    raw_factors = alert.factors or (alert.risk_score.factors if alert.risk_score else [])
    factors = _parse_factors(raw_factors)

    anomaly_score = alert.risk_score.anomaly_score if alert.risk_score else None
    confirmations = _count_confirmations(db, alert)

    explanation = AlertExplanationOut(
        alert_id=alert.id,
        crew_code=alert.crew_member.code,
        method=alert.method,
        rule_code=alert.rule_code,
        anomaly_score=anomaly_score,
        confirmations_count=confirmations,
        factors=factors,
    )
    return alert, explanation