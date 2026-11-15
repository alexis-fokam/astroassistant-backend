"""Live telemetry simulator for the jury demo (spec F15; new spec: "the AI detects an
injected anomaly live").

Every tick (2 s of real time) the simulated mission clock advances by ``2 s × speed``. For
each crew member the simulator writes one reading per vital sign around that member's own
baseline (circadian rhythm + noise), applies the active anomaly *effects*, then runs the
risk engine: new scores and alerts appear in the API and on the dashboards within seconds.

Simulated readings are mission telemetry (``source = simulator``, ``sim_run_id`` empty):
they drive the mission clock and every screen exactly like real sensors would. The
``sim_runs`` table keeps the trace of each demo run; ``python -m app.seed --reset`` restores
the reference story.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.pipeline import PipelineReport, run_once
from app.models import (
    Alert,
    Baseline,
    Checkin,
    CrewMember,
    DatasetSource,
    ExerciseSession,
    GroundMessage,
    Mission,
    ProtonFluxReading,
    RadiationDose,
    SleepSession,
    VitalReading,
)
from app.models.enums import (
    AlertStatus,
    DataSource,
    ExerciseKind,
    Metric,
    SessionStatus,
    SyncPacketKind,
)
from app.services import audit
from app.services.views import crew_summary, mission_now

TICK_SECONDS = 2.0
VITALS = (
    Metric.HEART_RATE,
    Metric.HRV_RMSSD,
    Metric.SPO2,
    Metric.RESPIRATORY_RATE,
    Metric.CORE_TEMPERATURE,
    Metric.SYSTOLIC_BP,
    Metric.DIASTOLIC_BP,
    Metric.ACTIVITY_LEVEL,
)
DEFAULTS = {
    Metric.HEART_RATE: (64, 4),
    Metric.HRV_RMSSD: (48, 4),
    Metric.SPO2: (97.8, 0.4),
    Metric.RESPIRATORY_RATE: (14, 1),
    Metric.CORE_TEMPERATURE: (36.8, 0.1),
    Metric.SYSTOLIC_BP: (117, 4),
    Metric.DIASTOLIC_BP: (75, 3),
    Metric.ACTIVITY_LEVEL: (1.6, 0.3),
}
ROUNDING = {Metric.SPO2: 1, Metric.CORE_TEMPERATURE: 2, Metric.ACTIVITY_LEVEL: 1}


# --------------------------------------------------------------------- anomalies
@dataclass(frozen=True)
class AnomalyKind:
    code: str
    label: str
    ramp_minutes: float
    expected_rules: tuple[str, ...]
    description: str


ANOMALIES: dict[str, AnomalyKind] = {
    a.code: a
    for a in (
        AnomalyKind(
            "tachycardia",
            "Tachycardie et désaturation",
            30,
            ("CARDIO-CRIT-01",),
            "FC qui monte vers 130 bpm, SpO₂ qui descend vers 92 %",
        ),
        AnomalyKind(
            "desaturation", "Chute de SpO₂", 20, ("SPO2-CRIT-01",), "SpO₂ qui descend vers 88 %"
        ),
        AnomalyKind("fever", "Fièvre", 60, ("TEMP-01",), "Température qui monte vers 38,7 °C"),
        AnomalyKind(
            "hrv_drop",
            "Stress et dette de sommeil",
            60,
            ("HRV-01",),
            "VFC à 60 % de la baseline, 3 nuits < 6 h, stress déclaré 8/10",
        ),
        AnomalyKind(
            "radiation",
            "Tempête solaire",
            10,
            ("RAD-SPE-01", "GOES-S1-01"),
            "Flux de protons GOES > 10 pfu puis débit de dose 1,8 mSv/h",
        ),
        AnomalyKind(
            "sans",
            "Suspicion SANS",
            1,
            ("SANS-01",),
            "Vision floue et céphalées déclarées deux jours de suite",
        ),
        AnomalyKind(
            "deconditioning",
            "Déconditionnement",
            1,
            ("EX-MISSED-01",),
            "Trois séances de résistance (ARED) manquées",
        ),
    )
}

# Scenario S1-S6 → anomaly and default target (backend seed, spec §4.1).
SCENARIO_EFFECTS: dict[str, tuple[str | None, str | None]] = {
    "S1": (None, None),
    "S2": ("hrv_drop", "AV-02"),
    "S3": ("radiation", "all"),
    "S4": ("sans", "AV-04"),
    "S5": ("deconditioning", "AV-01"),
    "S6": (None, None),
}


@dataclass
class Effect:
    kind: AnomalyKind
    crew_codes: tuple[str, ...]
    started_at: datetime  # simulated time

    def strength(self, now: datetime) -> float:
        minutes = (now - self.started_at).total_seconds() / 60
        return min(1.0, max(0.0, minutes / self.kind.ramp_minutes))


@dataclass
class SimState:
    run_id: int | None = None
    scenario: str | None = None
    speed: float = 60
    sim_time: datetime | None = None
    effects: list[Effect] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    ticks: int = 0
    rng: random.Random = field(default_factory=lambda: random.Random(42))

    def log(self, at: datetime, kind: str, message: str, **data: Any) -> None:
        self.events.append({"at": at.isoformat(), "kind": kind, "message": message, **data})
        del self.events[:-200]


# --------------------------------------------------------------------- generation
def _baselines(db: Session, member: CrewMember) -> dict[Metric, tuple[float, float]]:
    stored = {
        b.metric: (b.mean, max(b.std, 0.01))
        for b in db.scalars(select(Baseline).where(Baseline.crew_member_id == member.id))
    }
    return {m: stored.get(m, DEFAULTS[m]) for m in VITALS}


def _nominal(metric: Metric, mean: float, std: float, at: datetime, rng: random.Random) -> float:
    hour = at.hour + at.minute / 60
    circadian = math.sin(2 * math.pi * (hour - 10) / 24)
    value = mean + rng.gauss(0, std * 0.3)
    if metric is Metric.HEART_RATE:
        value += 5 * circadian
    elif metric is Metric.HRV_RMSSD:
        value -= 3 * circadian
    elif metric is Metric.SPO2:
        value = min(value, 99.6)
    elif metric is Metric.ACTIVITY_LEVEL:
        value = 1.0 if hour < 6 else value
    return value


def _apply(
    metric: Metric, value: float, mean: float, effects: list[tuple[AnomalyKind, float]]
) -> float:
    for kind, s in effects:
        if kind.code == "tachycardia":
            if metric is Metric.HEART_RATE:
                value += (130 - value) * s
            elif metric is Metric.SPO2:
                value -= (value - 92) * s
            elif metric is Metric.RESPIRATORY_RATE:
                value += 8 * s
        elif kind.code == "desaturation" and metric is Metric.SPO2:
            value -= (value - 88) * s
        elif kind.code == "fever":
            if metric is Metric.CORE_TEMPERATURE:
                value += (38.7 - value) * s
            elif metric is Metric.HEART_RATE:
                value += 10 * s
        elif kind.code == "hrv_drop" and metric is Metric.HRV_RMSSD:
            value = value - (value - 0.6 * mean) * s
    return round(value, ROUNDING.get(metric, 0))


def _one_shot_events(db: Session, state: SimState, effect: Effect, member: CrewMember) -> None:
    """Self-reported data that make an anomaly visible (check-ins, sleep, exercise)."""
    at = effect.started_at
    if effect.kind.code == "hrv_drop":
        for night in range(3, 0, -1):
            bed = (at - timedelta(days=night)).replace(hour=23, minute=10)
            db.add(
                SleepSession(
                    crew_member_id=member.id,
                    started_at=bed,
                    ended_at=bed + timedelta(hours=5, minutes=20),
                    quality=55,
                    awakenings=4,
                    latency_min=40,
                    source=DataSource.SIMULATOR,
                )
            )
        db.add(
            Checkin(
                crew_member_id=member.id,
                submitted_at=at,
                stress=8,
                mood=4,
                energy=3,
                sleep_quality=3,
            )
        )
    elif effect.kind.code == "sans":
        for days in (1, 0):
            db.add(
                Checkin(
                    crew_member_id=member.id,
                    submitted_at=at - timedelta(days=days),
                    vision_change=2,
                    headache=2,
                    notes="Vision floue de près, céphalées (simulation).",
                )
            )
    elif effect.kind.code == "deconditioning":
        # The astronaut skips the three most recent resistance (ARED) sessions.
        recent = db.scalars(
            select(ExerciseSession)
            .where(
                ExerciseSession.crew_member_id == member.id,
                ExerciseSession.kind == ExerciseKind.RESISTANCE,
                ExerciseSession.scheduled_at <= at,
            )
            .order_by(ExerciseSession.scheduled_at.desc())
            .limit(3)
        ).all()
        for session in recent:
            session.status, session.started_at = SessionStatus.MISSED, None
            session.duration_min = session.intensity = session.avg_heart_rate = None
            session.notes = "Séance manquée (simulation)"
        for days in range(len(recent), 3):
            db.add(
                ExerciseSession(
                    crew_member_id=member.id,
                    kind=ExerciseKind.RESISTANCE,
                    status=SessionStatus.MISSED,
                    scheduled_at=at - timedelta(days=days, minutes=5),
                    notes="Séance manquée (simulation)",
                )
            )


def _radiation(db: Session, member: CrewMember, at: datetime, dt_h: float, storm: float) -> None:
    last = db.scalars(
        select(RadiationDose)
        .where(RadiationDose.crew_member_id == member.id)
        .order_by(RadiationDose.recorded_at.desc())
    ).first()
    rate = 0.07 + 1.75 * storm
    mission = (last.mission_cumulative_msv if last else 0.0) + rate * dt_h
    career = max(
        (last.career_cumulative_msv if last else member.prior_career_dose_msv) + rate * dt_h,
        mission,
    )
    db.add(
        RadiationDose(
            crew_member_id=member.id,
            recorded_at=at,
            dose_rate_msv_h=round(rate, 4),
            mission_cumulative_msv=round(mission, 3),
            career_cumulative_msv=round(career, 3),
            neutron_fraction=0.05 if storm else 0.12,
            source=DataSource.SIMULATOR,
        )
    )


def _goes(db: Session, at: datetime, storm: float) -> None:
    source = db.scalars(
        select(DatasetSource).where(DatasetSource.code == "noaa-goes-protons")
    ).first()
    if source is not None and storm > 0:
        db.add(
            ProtonFluxReading(
                source_id=source.id,
                measured_at=at,
                satellite=18,
                energy_band=">=10 MeV",
                flux_pfu=round(5 + 245 * storm, 1),
            )
        )


# --------------------------------------------------------------------- public API
def start(
    db: Session,
    state: SimState,
    run_id: int,
    scenario: str,
    speed: float,
    seed: int,
    crew: str | None,
) -> None:
    state.run_id, state.scenario, state.speed = run_id, scenario, speed
    state.rng = random.Random(seed)
    state.sim_time = mission_now(db)
    state.effects, state.events, state.ticks = [], [], 0
    state.log(state.sim_time, "start", f"Scénario {scenario} lancé, vitesse ×{speed:g}")
    anomaly, default_target = SCENARIO_EFFECTS.get(scenario, (None, None))
    if anomaly:
        inject(db, state, anomaly, crew or default_target or "all", actor_label="Simulateur")
    if scenario == "S6":
        contact_window(db, state)


def inject(
    db: Session, state: SimState, anomaly: str, crew: str, actor_label: str = "Jury"
) -> Effect:
    """Start an anomaly now (simulated time) on one member or the whole crew."""
    kind = ANOMALIES[anomaly]
    members = list(db.scalars(select(CrewMember).where(CrewMember.is_active.is_(True))))
    targets = [m for m in members if crew == "all" or m.code == crew]
    if not targets:
        raise ValueError(f"Membre {crew} inconnu")
    at = state.sim_time or mission_now(db)
    # A demo re-run must be able to raise the alert again: close the previous ones.
    for member in targets:
        for alert in db.scalars(
            select(Alert).where(
                Alert.crew_member_id == member.id,
                Alert.rule_code.in_(kind.expected_rules),
                Alert.status != AlertStatus.RESOLVED,
            )
        ):
            alert.status, alert.resolved_at = AlertStatus.RESOLVED, at
            alert.ack_comment = alert.ack_comment or "Clôturée avant une nouvelle simulation"
    effect = Effect(kind, tuple(m.code for m in targets), at)
    state.effects.append(effect)
    for member in targets:
        _one_shot_events(db, state, effect, member)
    audit.record(db, "sim.inject", actor_label=actor_label, at=at, anomaly=anomaly, crew=crew)
    db.commit()
    state.log(
        at, "inject", f"Anomalie injectée : {kind.label} ({crew})", anomaly=anomaly, crew=crew
    )
    return effect


def contact_window(db: Session, state: SimState) -> None:
    """Scenario S6: export the crew summary now; the ground reply arrives after the delay."""
    from app.models.sync import PRIORITY_NORMAL
    from app.services.sync import queue_packet

    at = state.sim_time or mission_now(db)
    mission = db.scalars(select(Mission).where(Mission.is_active.is_(True))).first()
    latency = timedelta(seconds=mission.one_way_latency_s if mission else 720)
    members = list(db.scalars(select(CrewMember).where(CrewMember.is_active.is_(True))))
    packet = queue_packet(
        db,
        kind=SyncPacketKind.DAILY_SUMMARY.value,
        priority=PRIORITY_NORMAL,
        content={"crew": {m.code: crew_summary(db, m).model_dump(mode="json") for m in members}},
    )
    packet.created_at, packet.sent_at = at, at
    body = (
        "Synthèse reçue. Poursuivre le protocole en cours "
        "et transmettre la VFC à la prochaine fenêtre."
    )
    db.add(
        GroundMessage(
            author="Dr M. Reyes · Houston",
            subject="Accusé de réception de la synthèse",
            body=body,
            is_instruction=True,
            sha256=hashlib.sha256(f"{body}{at.isoformat()}".encode()).hexdigest(),
            sent_at=at + latency,
            received_at=at + 2 * latency,
        )
    )
    db.commit()
    state.log(at, "sync", f"Paquet de synthèse envoyé au sol (latence {latency.seconds // 60} min)")


def tick(db: Session, state: SimState) -> PipelineReport:
    """Advance the simulated clock by one tick, write telemetry and run the risk engine."""
    dt = timedelta(seconds=TICK_SECONDS * state.speed)
    state.sim_time = (state.sim_time or mission_now(db)) + dt
    at = state.sim_time
    members = list(db.scalars(select(CrewMember).where(CrewMember.is_active.is_(True))))
    rows = []
    storm = 0.0
    for member in members:
        baselines = _baselines(db, member)
        active = [(e.kind, e.strength(at)) for e in state.effects if member.code in e.crew_codes]
        for metric in VITALS:
            mean, std = baselines[metric]
            value = _apply(metric, _nominal(metric, mean, std, at, state.rng), mean, active)
            rows.append(
                {
                    "crew_member_id": member.id,
                    "metric": metric,
                    "value": value,
                    "quality": 0.95,
                    "is_artifact": False,
                    "source": DataSource.SIMULATOR,
                    "recorded_at": at,
                    "received_at": at,
                }
            )
        member_storm = max((s for k, s in active if k.code == "radiation"), default=0.0)
        storm = max(storm, member_storm)
        _radiation(db, member, at, dt.total_seconds() / 3600, member_storm)
    db.execute(VitalReading.__table__.insert(), rows)
    _goes(db, at, storm)
    db.commit()
    report = run_once(db, at=at)
    state.ticks += 1
    for alert_id in report.new_alert_ids:
        alert = db.get(Alert, alert_id)
        state.log(
            at,
            "alert",
            f"{alert.level.value.upper()} {alert.crew_member.code} · "
            f"{alert.title} ({alert.rule_code})",
            alert_id=alert_id,
            crew=alert.crew_member.code,
        )
    return report


def snapshot(state: SimState, running: bool) -> dict[str, Any]:
    return {
        "running": running,
        "run_id": state.run_id,
        "scenario": state.scenario,
        "speed_factor": state.speed,
        "sim_time": state.sim_time.astimezone(UTC).isoformat() if state.sim_time else None,
        "ticks": state.ticks,
        "effects": [
            {
                "anomaly": e.kind.code,
                "label": e.kind.label,
                "crew": list(e.crew_codes),
                "started_at": e.started_at.astimezone(UTC).isoformat(),
                "strength": round(e.strength(state.sim_time), 2) if state.sim_time else 0,
                "expected_rules": list(e.kind.expected_rules),
            }
            for e in state.effects
        ],
        "events": list(reversed(state.events[-50:])),
    }
