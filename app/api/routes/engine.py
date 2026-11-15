"""Pilotage du moteur de risque et explications (F2.7, §6)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentCmo, CurrentMember, DbSession, visible_member
from app.engine.config import load_config
from app.engine.pipeline import run_once
from app.engine.scheduler import broadcast
from app.models import Alert, FeatureSnapshot, RiskScore
from app.models.enums import RiskDomain
from app.schemas.engine import (
    AlertExplanation,
    DomainHistory,
    EngineReport,
    EngineStatus,
    RuleOut,
)
from app.services import audit
from app.services.views import as_utc

router = APIRouter(tags=["engine"])


@router.get("/engine/status", response_model=EngineStatus)
def engine_status(db: DbSession, _: CurrentMember) -> EngineStatus:
    cfg = load_config()
    last = db.scalar(
        select(func.max(RiskScore.computed_at)).where(RiskScore.model_version == cfg.model_version)
    )
    return EngineStatus(
        model_version=cfg.model_version,
        last_run_at=as_utc(last),
        rules=[
            RuleOut(
                code=r.code,
                domain=r.domain,
                level=r.level,
                method=r.method,
                title=r.title,
                protocol=r.protocol,
                conditions=[f"{f} {op} {v:g}" for f, op, v in r.when],
                any_of=[f"{f} {op} {v:g}" for f, op, v in r.any],
            )
            for r in cfg.rules
        ],
    )


@router.post("/engine/run", response_model=EngineReport)
async def engine_run(db: DbSession, cmo: CurrentCmo, force: bool = False) -> EngineReport:
    """Lancer le pipeline maintenant (CMO). ``force`` recalcule même sans nouvelle mesure."""
    report = run_once(db, force=force)
    audit.record(db, "engine.run", actor=cmo, force=force, alerts=report.new_alert_ids)
    db.commit()
    await broadcast(report)
    return EngineReport.model_validate(report, from_attributes=True)


@router.get("/alerts/{alert_id}/explanation", response_model=AlertExplanation)
def explanation(alert_id: int, db: DbSession, viewer: CurrentMember) -> AlertExplanation:
    """Pourquoi une alerte s'est déclenchée (F2.7) : facteurs, règle, score, confirmations."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerte introuvable")
    visible_member(db, viewer, alert.crew_member.code)
    cfg = load_config()
    rule = next((r for r in cfg.rules if r.code == alert.rule_code), None)
    score = alert.risk_score
    snapshot = score.feature_snapshot if score else None
    confirmations = 1
    if rule is not None and rule.level.value == "warning":
        confirmations = 2
    return AlertExplanation(
        alert_id=alert.id,
        rule_code=alert.rule_code,
        method=alert.method,
        rule=(" ∧ ".join(f"{f} {op} {v:g}" for f, op, v in rule.when) if rule else None),
        any_of=[f"{f} {op} {v:g}" for f, op, v in rule.any] if rule else [],
        factors=alert.factors,
        anomaly_score=score.anomaly_score if score else None,
        domain_score=score.score if score else None,
        confirmations=confirmations,
        features=snapshot.features if snapshot else {},
    )


@router.get("/crew/{code}/domains/{domain}", response_model=DomainHistory)
def domain_history(
    code: str, domain: RiskDomain, db: DbSession, viewer: CurrentMember, limit: int = 56
) -> DomainHistory:
    """Historique des scores d'un domaine, avec les derniers facteurs explicatifs."""
    member = visible_member(db, viewer, code)
    rows = list(
        db.scalars(
            select(RiskScore)
            .where(
                RiskScore.crew_member_id == member.id,
                RiskScore.domain == domain,
                RiskScore.sim_run_id.is_(None),
            )
            .order_by(RiskScore.computed_at.desc())
            .limit(limit)
        )
    )[::-1]
    latest = rows[-1] if rows else None
    snapshot = (
        db.get(FeatureSnapshot, latest.feature_snapshot_id)
        if latest and latest.feature_snapshot_id
        else None
    )
    return DomainHistory(
        crew_id=member.code,
        domain=domain,
        score=latest.score if latest else None,
        level=latest.level if latest else None,
        factors=latest.factors if latest else [],
        rules=(snapshot.features.get("_rules", []) if snapshot else []),
        history=[{"t": as_utc(r.computed_at), "score": r.score, "level": r.level} for r in rows],
    )
