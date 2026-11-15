"""Risk pipeline (spec §6, §8.1): features → rules → anomaly → scores → alerts.

``run_once`` processes every active crew member at the mission clock. A member is only
recomputed when new telemetry arrived since the engine's last scores (or with ``force``),
so the scheduler can call it every few seconds without filling the database.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import anomaly, baselines, features, scoring
from app.engine.config import EngineConfig, Rule, load_config
from app.models import CrewMember, FeatureSnapshot, RiskScore, SimRun
from app.models.enums import RiskDomain, SimRunStatus
from app.services.alerts import create_alert


@dataclass
class MemberReport:
    code: str
    skipped: bool
    status: str | None = None
    global_score: float | None = None
    domains: dict[str, float] = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    pending_confirmation: list[str] = field(default_factory=list)
    anomaly_score: float | None = None
    new_alert_ids: list[int] = field(default_factory=list)


@dataclass
class PipelineReport:
    computed_at: datetime
    model_version: str
    duration_ms: float
    members: list[MemberReport]

    @property
    def new_alert_ids(self) -> list[int]:
        return [i for m in self.members for i in m.new_alert_ids]


def mission_clock(db: Session) -> datetime:
    from app.services.views import mission_now

    return mission_now(db)


def running_sim(db: Session) -> SimRun | None:
    return db.scalars(select(SimRun).where(SimRun.status == SimRunStatus.RUNNING)).first()


def _format(template: str, values: dict) -> str:
    safe = {k: (v if v is not None else float("nan")) for k, v in values.items()}
    try:
        return template.format(**safe)
    except (KeyError, ValueError):
        return template


def _last_engine_run(db: Session, member: CrewMember, cfg: EngineConfig) -> datetime | None:
    value = db.scalar(
        select(func.max(RiskScore.computed_at)).where(
            RiskScore.crew_member_id == member.id, RiskScore.model_version == cfg.model_version
        )
    )
    return features.naive_utc(value) if value else None


def process_member(
    db: Session,
    member: CrewMember,
    at: datetime,
    cfg: EngineConfig,
    *,
    sim_run_id: int | None = None,
    force: bool = False,
) -> MemberReport:
    data = features.load_member(db, member, at, cfg, sim_run_id)
    latest = features.latest_reading_time(data)
    last_run = _last_engine_run(db, member, cfg)
    if not force and (latest is None or (last_run is not None and last_run >= latest)):
        return MemberReport(code=member.code, skipped=True)

    refreshed = baselines.refresh(db, data, at, cfg)

    # Two consecutive evaluations: WARNING rules must hold on both (spec §6.3).
    previous_at = at - timedelta(minutes=cfg.windows["confirm_minutes"])
    current = features.compute(data, at, cfg)
    previous = features.compute(data, previous_at, cfg)
    current["anomaly_score"] = anomaly.score(data, current, at, cfg)
    previous["anomaly_score"] = anomaly.score(data, previous, previous_at, cfg)
    fired = scoring.evaluate(cfg.rules, current)
    rules = scoring.confirmed(fired, scoring.evaluate(cfg.rules, previous))
    pending = [r.code for r in fired if r not in rules]

    domains = scoring.score_domains(current, rules, cfg)
    total, level = scoring.global_score(domains, cfg)

    snapshot = FeatureSnapshot(
        crew_member_id=member.id,
        sim_run_id=sim_run_id,
        computed_at=at,
        window_start=at - timedelta(hours=24),
        window_end=at,
        features={
            **current,
            "_rules": [r.code for r in rules],
            "_pending": pending,
            "_model": cfg.model_version,
            "_baselines_refreshed": refreshed,
        },
    )
    db.add(snapshot)
    db.flush()

    rows: dict[RiskDomain, RiskScore] = {}
    for d in domains:
        rows[d.domain] = RiskScore(
            crew_member_id=member.id,
            feature_snapshot_id=snapshot.id,
            sim_run_id=sim_run_id,
            computed_at=at,
            domain=d.domain,
            score=d.score,
            level=d.level,
            anomaly_score=current["anomaly_score"],
            factors=d.factors,
            model_version=cfg.model_version,
        )
    top = sorted(domains, key=lambda d: -d.score)
    rows[RiskDomain.GLOBAL] = RiskScore(
        crew_member_id=member.id,
        feature_snapshot_id=snapshot.id,
        sim_run_id=sim_run_id,
        computed_at=at,
        domain=RiskDomain.GLOBAL,
        score=total,
        level=level,
        factors=[f for d in top for f in d.factors][:3],
        model_version=cfg.model_version,
    )
    db.add_all(rows.values())
    db.flush()

    report = MemberReport(
        code=member.code,
        skipped=False,
        status=level.value,
        global_score=total,
        domains={d.domain.value: d.score for d in domains},
        rules=[r.code for r in rules],
        pending_confirmation=pending,
        anomaly_score=current["anomaly_score"],
    )
    by_domain = {d.domain: d for d in domains}
    for rule in rules:
        alert = _raise(
            db, member, rule, current, by_domain[rule.domain], rows[rule.domain], at, sim_run_id
        )
        if alert is not None:
            report.new_alert_ids.append(alert.id)
    return report


def _raise(db, member, rule: Rule, values, domain_score, risk_score, at, sim_run_id):
    threshold = rule.threshold
    if rule.threshold_feature:
        threshold = values.get(rule.threshold_feature)
    alert = create_alert(
        db,
        member,
        rule_code=rule.code,
        level=rule.level,
        domain=rule.domain,
        domain_label=rule.domain_label,
        method=rule.method,
        title=rule.title,
        message=_format(rule.message, values),
        at=at,
        metric=rule.metric,
        observed_value=values.get(rule.observed) if rule.observed else None,
        threshold=threshold,
        factors=domain_score.factors,
        protocol_code=rule.protocol,
        risk_score=risk_score,
        sim_run_id=sim_run_id,
    )
    if alert is not None:
        db.flush()
    return alert


def run_once(db: Session, at: datetime | None = None, *, force: bool = False) -> PipelineReport:
    cfg = load_config()
    started = time.perf_counter()
    at = features.naive_utc(at or mission_clock(db))
    sim = running_sim(db)
    members = db.scalars(
        select(CrewMember).where(CrewMember.is_active.is_(True)).order_by(CrewMember.code)
    ).all()
    reports = [
        process_member(db, m, at, cfg, sim_run_id=sim.id if sim else None, force=force)
        for m in members
    ]
    db.commit()
    return PipelineReport(
        computed_at=at.replace(tzinfo=UTC),
        model_version=cfg.model_version,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        members=reports,
    )
