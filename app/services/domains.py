from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrewMember, RiskScore
from app.models.enums import RiskDomain
from app.schemas.domains import CrewDomainHistoryOut, DomainFactor, DomainScorePoint


def _parse_domain_factors(raw_factors: list[Any]) -> list[DomainFactor]:
    parsed: list[DomainFactor] = []
    for item in raw_factors:
        if isinstance(item, dict):
            feature = item.get("feature") or item.get("label") or item.get("name") or "Inconnu"
            parsed.append(
                DomainFactor(
                    feature=str(feature),
                    value=item.get("value"),
                    baseline=item.get("baseline"),
                    contribution=item.get("contribution"),
                )
            )
    return parsed


def crew_domain_history(
    db: Session,
    member: CrewMember,
    domain: RiskDomain,
    limit: int = 50,
) -> CrewDomainHistoryOut:
    # Requête descendante utilisant l'index (crew_member_id, domain, computed_at)
    rows_desc = db.scalars(
        select(RiskScore)
        .where(
            RiskScore.crew_member_id == member.id,
            RiskScore.domain == domain,
        )
        .order_by(RiskScore.computed_at.desc())
        .limit(limit)
    ).all()

    if not rows_desc:
        return CrewDomainHistoryOut(
            crew_id=member.code,
            domain=domain,
        )

    # Remettre dans l'ordre chronologique pour le graphique
    chronological = list(reversed(rows_desc))
    latest = chronological[-1]

    history_points = [
        DomainScorePoint(
            t=row.computed_at,
            score=row.score,
            level=row.level,
            anomaly_score=row.anomaly_score,
            factors=_parse_domain_factors(row.factors),
        )
        for row in chronological
    ]

    return CrewDomainHistoryOut(
        crew_id=member.code,
        domain=domain,
        current_score=latest.score,
        current_level=latest.level,
        latest_factors=history_points[-1].factors,
        history=history_points,
    )
