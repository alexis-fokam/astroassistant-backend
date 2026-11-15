"""Historique de mission fictif et déterministe pour la base de démo.

Génère les ``HISTORY_DAYS`` derniers jours de la mission Artemis-M (jusqu'à J+142, l'horloge
affichée par le frontend) pour les quatre membres fictifs, afin que chaque table du schéma
contienne des données cohérentes :

* AV-01 saute trois séances de résistance → WARNING musculo-squelettique (scénario S5) ;
* AV-02 accumule une dette de sommeil avec une VFC en baisse → WARNING comportemental (S2) ;
* AV-03 développe une tachycardie avec désaturation → alerte CRITICAL et urgence (EMRG-01) ;
* AV-04 signale vision floue et céphalées → suspicion de SANS (S4) ;
* il y a deux jours, tout l'équipage s'est abrité pendant le rejeu de l'événement à
  particules solaires de septembre 2017 (S3).

Le fond de radiation suit le vrai profil de Curiosity RAD quand le CSV est disponible.
Tout l'aléa vient de ``random.Random(seed)`` : la même graine produit toujours la même base.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datasets import msl_rad
from app.datasets.paths import MSL_RAD_CSV
from app.models import (
    Alert,
    AuditLog,
    Checkin,
    ConsultationNote,
    CrewMember,
    Device,
    EmergencyEvent,
    ExerciseSession,
    FeatureSnapshot,
    GroundMessage,
    IntakeLog,
    InventoryItem,
    InventoryUsage,
    Mission,
    Protocol,
    ProtocolRun,
    PvtResult,
    RadiationDose,
    RiskScore,
    SimRun,
    SimScenario,
    SleepSession,
    SpaceWeatherEvent,
    SyncPacket,
    VitalReading,
)
from app.models.audit import GENESIS_HASH
from app.models.enums import (
    AlertLevel,
    AlertStatus,
    DataSource,
    DetectionMethod,
    DeviceKind,
    EmergencyStatus,
    ExerciseIntensity,
    ExerciseKind,
    HealthLevel,
    IntakeKind,
    Metric,
    ProtocolRunStatus,
    RiskDomain,
    SessionStatus,
    SimRunStatus,
    SpaceWeatherKind,
    SyncPacketKind,
    SyncPacketStatus,
)
from app.models.sync import PRIORITY_CRITICAL, PRIORITY_HIGH, PRIORITY_NORMAL

DEMO_NOW = datetime(2026, 10, 13, 14, 5, tzinfo=UTC)  # J+142 · 14:05 (frontend clock)
HISTORY_DAYS = 14
MODEL_VERSION = "risk-engine 0.4.0"

# Équivalent de dose moyen en croisière sans fichier RAD (Zeitlin 2013 : 1,84 mSv/jour).
FALLBACK_DOSE_MSV_H = 1.84 / 24
SPE_PEAK_MSV_H = 1.82
# Facteur de blindage de la cabine de chaque membre par rapport à l'instrument RAD.
SHIELDING = {"AV-01": 0.94, "AV-02": 1.0, "AV-03": 0.97, "AV-04": 0.95}

# Scores finaux par domaine à DEMO_NOW, identiques aux données de démo du frontend (crew.ts).
FINAL_SCORES = {
    "AV-01": {"cardio": 22, "radiation": 24, "musculoskeletal": 52, "behavioral": 30, "immune": 15},
    "AV-02": {"cardio": 61, "radiation": 22, "musculoskeletal": 35, "behavioral": 68, "immune": 18},
    "AV-03": {"cardio": 84, "radiation": 25, "musculoskeletal": 28, "behavioral": 40, "immune": 21},
    "AV-04": {"cardio": 30, "radiation": 23, "musculoskeletal": 26, "behavioral": 34, "immune": 20},
}
FINAL_GLOBAL = {"AV-01": 41, "AV-02": 54, "AV-03": 81, "AV-04": 47}
# Heures avant DEMO_NOW où un domaine commence à dériver vers son score final.
ONSET_H = {
    ("AV-01", "musculoskeletal"): 72,
    ("AV-02", "behavioral"): 80,
    ("AV-02", "cardio"): 80,
    ("AV-03", "cardio"): 1,
    ("AV-04", "cardio"): 50,
}


def level_for(score: float) -> HealthLevel:
    if score >= 70:
        return HealthLevel.CRITICAL
    if score >= 40:
        return HealthLevel.WARNING
    return HealthLevel.NOMINAL


def global_score(domains: dict[str, float]) -> float:
    """Agrégat : max/moyenne pondérés, forcé au max quand un domaine est critique."""
    top, mean = max(domains.values()), sum(domains.values()) / len(domains)
    return round(top if top >= 70 else 0.6 * top + 0.4 * mean, 1)


@dataclass
class AuditEvent:
    at: datetime
    actor_label: str
    action: str
    entity_type: str | None = None
    entity_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    actor_id: int | None = None


@dataclass
class HistoryBuilder:
    session: Session
    now: datetime = DEMO_NOW
    days: int = HISTORY_DAYS
    seed: int = 142
    audit: list[AuditEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.start = (self.now - timedelta(days=self.days)).replace(hour=0, minute=0)
        self.crew = {
            c.code: c for c in self.session.scalars(select(CrewMember).order_by(CrewMember.code))
        }
        self.cmo = self.crew["AV-04"]
        self.mission = self.session.scalars(select(Mission)).one()
        self.protocols = {p.code: p for p in self.session.scalars(select(Protocol))}
        self.items = {i.code: i for i in self.session.scalars(select(InventoryItem))}
        self.wearables = {
            d.crew_member_id: d
            for d in self.session.scalars(select(Device).where(Device.kind == DeviceKind.WEARABLE))
        }
        self.baselines = {(c.code, b.metric): b for c in self.crew.values() for b in c.baselines}
        self.spe_start = (self.now - timedelta(days=2)).replace(hour=9, minute=40)

    # ------------------------------------------------------------------ helpers
    def log(
        self, at: datetime, actor: str, action: str, entity: Any = None, **details: Any
    ) -> None:
        actor_member = self.crew.get(actor)
        self.audit.append(
            AuditEvent(
                at=at,
                actor_label=actor,
                action=action,
                entity_type=entity.__tablename__ if entity is not None else None,
                entity_id=entity.id if entity is not None else None,
                details=details,
                actor_id=actor_member.id if actor_member else None,
            )
        )

    def add(self, obj: Any) -> Any:
        self.session.add(obj)
        self.session.flush()
        return obj

    def hours(self, step_min: int = 60, start: datetime | None = None):
        t = start or self.start
        while t <= self.now:
            yield t
            t += timedelta(minutes=step_min)

    def hours_before_now(self, t: datetime) -> float:
        return (self.now - t).total_seconds() / 3600

    # ------------------------------------------------------------------ vitals
    def vital_value(self, code: str, metric: Metric, t: datetime) -> float:
        base = self.baselines[(code, metric)]
        noise = self.rng.gauss(0, base.std * 0.35)
        circadian = math.sin((t.hour + t.minute / 60 - 10) / 24 * 2 * math.pi)
        h = self.hours_before_now(t)
        value = base.mean + noise
        if metric is Metric.HEART_RATE:
            value += 6 * circadian
            if code == "AV-02" and 72 <= h <= 75:  # resting HR episode (alert resolved 3 days ago)
                value = 94 + self.rng.uniform(0, 3)
            if code == "AV-03" and h <= 0.75:
                value = base.mean + (128 - base.mean) * (1 - h / 0.75) + self.rng.uniform(-2, 2)
        elif metric is Metric.HRV_RMSSD:
            value -= 4 * circadian
            if code == "AV-02" and h <= 80:
                value = base.mean * (1 - 0.35 * (1 - h / 80)) + self.rng.gauss(0, 2)
        elif metric is Metric.SPO2:
            value = min(value, 99.6)
            if code == "AV-03" and h <= 0.75:
                value = 97.5 - 5.5 * (1 - h / 0.75) + self.rng.uniform(-0.3, 0.3)
        elif metric is Metric.RESPIRATORY_RATE and code == "AV-03" and h <= 0.75:
            value = 22 + self.rng.uniform(-1, 1)
        elif metric in (Metric.SYSTOLIC_BP, Metric.DIASTOLIC_BP) and code == "AV-04" and h <= 50:
            value += 4
        return round(value, 1 if metric in (Metric.SPO2, Metric.CORE_TEMPERATURE) else 0)

    def build_vitals(self) -> int:
        rows = []
        fine_start = self.now - timedelta(hours=2)
        for code, member in self.crew.items():
            device = self.wearables[member.id]
            for t in self.hours():
                for metric in (
                    Metric.HEART_RATE,
                    Metric.HRV_RMSSD,
                    Metric.SPO2,
                    Metric.RESPIRATORY_RATE,
                    Metric.CORE_TEMPERATURE,
                ):
                    rows.append(self._vital_row(member, device, metric, t))
                if t.hour in (7, 19):  # cuff blood pressure twice a day
                    for metric in (Metric.SYSTOLIC_BP, Metric.DIASTOLIC_BP):
                        rows.append(self._vital_row(member, device, metric, t))
                rows.append(
                    self._vital_row(
                        member, device, Metric.ACTIVITY_LEVEL, t, value=self._met(code, t)
                    )
                )
            # Résolution de 5 minutes sur les deux dernières heures (tableau de bord en direct).
            for t in self.hours(5, start=fine_start):
                if t.minute == 0:
                    continue
                for metric in (Metric.HEART_RATE, Metric.HRV_RMSSD, Metric.SPO2):
                    rows.append(self._vital_row(member, device, metric, t))
            device.last_seen_at = self.now
        # Un artefact rejeté par le nettoyage (§6.1) : sangle déplacée sur AV-01.
        rows.append(
            self._vital_row(
                self.crew["AV-01"],
                self.wearables[self.crew["AV-01"].id],
                Metric.HEART_RATE,
                self.now - timedelta(hours=30, minutes=12),
                value=212,
                quality=0.18,
                artifact=True,
            )
        )
        self.session.execute(VitalReading.__table__.insert(), rows)
        return len(rows)

    def _met(self, code: str, t: datetime) -> float:
        if t.hour in (8, 17) and not (code == "AV-01" and self.hours_before_now(t) <= 72):
            return round(self.rng.uniform(5.5, 7.5), 1)
        if 0 <= t.hour < 7:
            return 1.0
        return round(self.rng.uniform(1.3, 2.2), 1)

    def _vital_row(
        self,
        member: CrewMember,
        device: Device,
        metric: Metric,
        t: datetime,
        *,
        value: float | None = None,
        quality: float | None = None,
        artifact: bool = False,
    ) -> dict[str, Any]:
        return {
            "crew_member_id": member.id,
            "device_id": device.id,
            "metric": metric,
            "value": value if value is not None else self.vital_value(member.code, metric, t),
            "quality": quality if quality is not None else round(self.rng.uniform(0.86, 0.99), 2),
            "is_artifact": artifact,
            "source": DataSource.SENSOR,
            "recorded_at": t,
            "received_at": t + timedelta(seconds=2),
        }

    # ------------------------------------------------------------------ radiation
    def cruise_profile(self) -> list[float]:
        """Équivalent de dose horaire (mSv/h) tiré du vrai trajet RAD, sinon une constante."""
        if MSL_RAD_CSV.exists():
            samples = msl_rad.load(MSL_RAD_CSV)
            if samples:
                return [s.dose_equivalent_usv_h / 1000 for s in samples]
        return [FALLBACK_DOSE_MSV_H]

    def build_radiation(self) -> SpaceWeatherEvent:
        profile = self.cruise_profile()
        spe = self.add(
            SpaceWeatherEvent(
                kind=SpaceWeatherKind.SOLAR_PARTICLE_EVENT,
                flare_class="X8.2",
                started_at=self.spe_start,
                peak_at=self.spe_start + timedelta(hours=1, minutes=20),
                ended_at=self.spe_start + timedelta(hours=6),
                peak_proton_flux_pfu=1490.0,
                shelter_deadline_at=self.spe_start + timedelta(minutes=10),
                description=(
                    "Rejeu de l'événement du 10 septembre 2017 (S3) à l'échelle de la mission."
                ),
            )
        )
        self.log(self.spe_start, "Moteur IA", "space_weather.detect", spe, flux_pfu=1490)

        elapsed_days = (self.start.date() - self.mission.start_date).days
        rows = []
        for code, member in self.crew.items():
            mission_dose = elapsed_days * sum(profile) / len(profile) * 24 * SHIELDING[code]
            for i, t in enumerate(self.hours()):
                rate = profile[(i * 7 + int(code[-1]) * 97) % len(profile)] * SHIELDING[code]
                neutron = round(self.rng.uniform(0.09, 0.15), 3)
                offset = (t - self.spe_start).total_seconds() / 3600
                event_id = None
                if 0 <= offset <= 6:
                    # Abrités dans l'abri anti-tempête : pic atténué après le délai de 10 minutes.
                    shape = math.exp(-((offset - 1.33) ** 2) / 1.2)
                    rate = max(rate, SPE_PEAK_MSV_H * shape * (0.35 if offset > 0.17 else 1))
                    neutron, event_id = round(self.rng.uniform(0.03, 0.06), 3), spe.id
                mission_dose += rate
                rows.append(
                    {
                        "crew_member_id": member.id,
                        "event_id": event_id,
                        "recorded_at": t,
                        "dose_rate_msv_h": round(rate, 4),
                        "mission_cumulative_msv": round(mission_dose, 3),
                        "career_cumulative_msv": round(
                            member.prior_career_dose_msv + mission_dose, 3
                        ),
                        "neutron_fraction": neutron,
                        "source": DataSource.SENSOR,
                    }
                )
        self.session.execute(RadiationDose.__table__.insert(), rows)
        return spe

    # ------------------------------------------------------------------ wellness
    def build_wellness(self) -> None:
        sleeps, exercises, pvts, intakes, checkins = [], [], [], [], []
        for day in range(self.days + 1):
            d0 = self.start + timedelta(days=day)
            for code, member in self.crew.items():
                late = self.hours_before_now(d0) <= 72
                # Nuit de d0 → d0+1 (AV-02 : < 6 h les trois dernières nuits).
                bed = d0 + timedelta(hours=22, minutes=self.rng.randint(0, 40))
                hours = (
                    5.4 + self.rng.uniform(0, 0.4)
                    if code == "AV-02" and late
                    else self.rng.uniform(6.8, 7.9)
                )
                wake = bed + timedelta(hours=hours)
                if wake <= self.now:
                    sleeps.append(
                        {
                            "crew_member_id": member.id,
                            "started_at": bed,
                            "ended_at": wake,
                            "quality": int(hours / 8 * 100 - self.rng.randint(0, 8)),
                            "awakenings": self.rng.randint(0, 2)
                            + (2 if code == "AV-02" and late else 0),
                            "latency_min": self.rng.randint(8, 25)
                            + (20 if code == "AV-02" and late else 0),
                            "source": DataSource.SENSOR,
                        }
                    )
                # Exercice : résistance (ARED) à 08:00, aérobie à 17:00.
                for hour, kind in (
                    (8, ExerciseKind.RESISTANCE),
                    (17, self.rng.choice([ExerciseKind.TREADMILL, ExerciseKind.CYCLE])),
                ):
                    slot = d0 + timedelta(hours=hour)
                    if slot > self.now + timedelta(days=1):
                        continue
                    missed = code == "AV-01" and kind is ExerciseKind.RESISTANCE and late
                    planned = slot > self.now
                    status = (
                        SessionStatus.PLANNED
                        if planned
                        else SessionStatus.MISSED
                        if missed
                        else SessionStatus.COMPLETED
                    )
                    done = status is SessionStatus.COMPLETED
                    exercises.append(
                        {
                            "crew_member_id": member.id,
                            "kind": kind,
                            "status": status,
                            "scheduled_at": slot,
                            "started_at": slot + timedelta(minutes=self.rng.randint(0, 10))
                            if done
                            else None,
                            "duration_min": self.rng.choice([45, 50, 60]) if done else None,
                            "intensity": (
                                ExerciseIntensity.HIGH
                                if kind is ExerciseKind.RESISTANCE
                                else self.rng.choice(
                                    [ExerciseIntensity.MODERATE, ExerciseIntensity.INTERVAL]
                                )
                            )
                            if done
                            else None,
                            "avg_heart_rate": self.rng.randint(118, 142) if done else None,
                            "notes": "Séance non réalisée (charge de travail)"
                            if missed and not planned
                            else None,
                        }
                    )
                # PVT du matin (dégradé pour AV-02 en dette de sommeil).
                taken = d0 + timedelta(hours=7, minutes=30)
                if taken <= self.now:
                    tired = code == "AV-02" and late
                    pvts.append(
                        {
                            "crew_member_id": member.id,
                            "taken_at": taken,
                            "duration_seconds": 180,
                            "stimuli_count": self.rng.randint(28, 34),
                            "median_rt_ms": round(
                                self.rng.uniform(305, 340) if tired else self.rng.uniform(245, 285),
                                1,
                            ),
                            "lapses": self.rng.randint(3, 6) if tired else self.rng.randint(0, 1),
                            "false_starts": self.rng.randint(0, 1),
                        }
                    )
                # Repas et eau.
                for hour, kind, kcal in (
                    (7, IntakeKind.MEAL, 650),
                    (12, IntakeKind.MEAL, 900),
                    (15, IntakeKind.SNACK, 250),
                    (19, IntakeKind.MEAL, 850),
                ):
                    at = d0 + timedelta(hours=hour, minutes=self.rng.randint(0, 30))
                    if at <= self.now:
                        intakes.append(
                            {
                                "crew_member_id": member.id,
                                "logged_at": at,
                                "kind": kind,
                                "portion_code": "main_dish"
                                if kind is IntakeKind.MEAL
                                else "snack_bar",
                                "energy_kcal": kcal + self.rng.randint(-80, 80),
                                "water_ml": None,
                            }
                        )
                for hour in (8, 11, 14, 17, 20):
                    at = d0 + timedelta(hours=hour, minutes=15)
                    if at <= self.now:
                        intakes.append(
                            {
                                "crew_member_id": member.id,
                                "logged_at": at,
                                "kind": IntakeKind.WATER,
                                "portion_code": "pouch_500",
                                "energy_kcal": None,
                                "water_ml": 500,
                            }
                        )
                # Check-in quotidien à 21:00.
                at = d0 + timedelta(hours=21)
                if at <= self.now:
                    checkins.append(self._checkin(code, member, at))
        self.session.execute(SleepSession.__table__.insert(), sleeps)
        self.session.execute(ExerciseSession.__table__.insert(), exercises)
        self.session.execute(PvtResult.__table__.insert(), pvts)
        self.session.execute(IntakeLog.__table__.insert(), intakes)
        self.session.execute(Checkin.__table__.insert(), checkins)
        # N'auditer que les check-ins cliniquement utiles, pour garder le journal lisible.
        for row in checkins:
            if row["stress"] >= 7 or row["vision_change"] >= 2:
                self.log(
                    row["submitted_at"],
                    self._code_of(row["crew_member_id"]),
                    "checkin.submit",
                    stress=row["stress"],
                    vision_change=row["vision_change"],
                )

    def _code_of(self, member_id: int) -> str:
        return next(code for code, m in self.crew.items() if m.id == member_id)

    def _checkin(self, code: str, member: CrewMember, at: datetime) -> dict[str, Any]:
        h = self.hours_before_now(at)
        r = self.rng
        row = {
            "crew_member_id": member.id,
            "scheduled_for": at,
            "submitted_at": at + timedelta(minutes=r.randint(0, 20)),
            "duration_seconds": r.randint(45, 85),
            "headache": r.choice([0, 0, 0, 1]),
            "vision_change": 0,
            "congestion": r.choice([0, 1, 1, 2]),  # fréquent en apesanteur
            "back_pain": r.choice([0, 0, 1]),
            "nausea": 0,
            "dizziness": 0,
            "skin_issue": r.choice([0, 0, 0, 1]),
            "sleep_quality": r.randint(6, 8),
            "mood": r.randint(6, 8),
            "stress": r.randint(2, 4),
            "isolation": r.randint(2, 4),
            "energy": r.randint(6, 8),
            "crew_relations": r.randint(7, 9),
            "notes": None,
        }
        if code == "AV-02" and h <= 80:
            row.update(
                sleep_quality=r.randint(3, 4),
                stress=7,
                mood=5,
                energy=4,
                notes="Difficulté à m'endormir, charge de travail EVA.",
            )
        if code == "AV-04" and h <= 50:
            row.update(
                vision_change=2,
                headache=2,
                notes="Vision floue de près, céphalées en fin de journée.",
            )
        if code == "AV-01" and h <= 72:
            row.update(back_pain=2, notes="Pas eu le temps pour l'ARED.")
        return row

    # ------------------------------------------------------------------ scores
    def build_scores(self) -> dict[str, list[RiskScore]]:
        latest: dict[str, list[RiskScore]] = {}
        step = timedelta(hours=6)
        t = self.start
        times = []
        while t <= self.now:
            times.append(t)
            t += step
        if times[-1] != self.now - timedelta(minutes=5):
            times.append(self.now - timedelta(minutes=5))
        for code, member in self.crew.items():
            for t in times:
                h = self.hours_before_now(t)
                snapshot = self.add(
                    FeatureSnapshot(
                        crew_member_id=member.id,
                        computed_at=t,
                        window_start=t - timedelta(hours=24),
                        window_end=t,
                        features=self._features(code, t),
                    )
                )
                domains: dict[str, float] = {}
                for domain, final in FINAL_SCORES[code].items():
                    onset = ONSET_H.get((code, domain))
                    base = min(final, 12 + self.rng.uniform(0, 10))
                    if onset and h <= onset:
                        value = base + (final - base) * (1 - h / onset)
                    elif onset:
                        value = base
                    else:
                        value = final + self.rng.uniform(-3, 3)
                    if (
                        domain == "radiation"
                        and 0 <= (t - self.spe_start).total_seconds() / 3600 <= 6
                    ):
                        value = 74 + self.rng.uniform(0, 6)
                    domains[domain] = round(min(max(value, 0), 100), 1)
                if h < 0.1:
                    domains = {k: float(v) for k, v in FINAL_SCORES[code].items()}
                scores = []
                overall = FINAL_GLOBAL[code] if h < 0.1 else global_score(domains)
                for domain, value in {**domains, "global": overall}.items():
                    scores.append(
                        RiskScore(
                            crew_member_id=member.id,
                            feature_snapshot_id=snapshot.id,
                            computed_at=t,
                            domain=RiskDomain(domain),
                            score=value,
                            level=level_for(value),
                            anomaly_score=round(
                                min(1, value / 100 + self.rng.uniform(-0.05, 0.05)), 3
                            )
                            if domain != "global"
                            else None,
                            factors=self._factors(code, domain, value),
                            model_version=MODEL_VERSION,
                        )
                    )
                self.session.add_all(scores)
                latest[code] = scores
        self.session.flush()
        return latest

    def _features(self, code: str, t: datetime) -> dict[str, Any]:
        out = {}
        for metric in (Metric.HEART_RATE, Metric.HRV_RMSSD, Metric.SPO2):
            base = self.baselines[(code, metric)]
            value = self.vital_value(code, metric, t)
            out[metric.value] = {
                "mean": value,
                "z": round((value - base.median) / (base.mad * 1.4826), 2),
            }
        return out

    def _factors(self, code: str, domain: str, score: float) -> list[dict[str, Any]]:
        if score < 40:
            return []
        catalogue = {
            ("AV-01", "musculoskeletal"): [
                ("ared_missed", 3, 0, 0.6),
                ("activity_level", 1.6, 2.4, 0.25),
            ],
            ("AV-02", "behavioral"): [
                ("hrv_rmssd", 31, 48, 0.45),
                ("sleep_hours", 5.6, 7.3, 0.35),
                ("stress", 7, 3, 0.2),
            ],
            ("AV-02", "cardio"): [("hrv_rmssd", 31, 48, 0.55), ("heart_rate", 74, 64, 0.3)],
            ("AV-03", "cardio"): [
                ("heart_rate", 128, 67, 0.55),
                ("spo2", 92, 97.8, 0.35),
                ("respiratory_rate", 22, 14.7, 0.1),
            ],
            ("AV-04", "cardio"): [
                ("vision_change", 2, 0, 0.5),
                ("headache", 2, 0, 0.3),
                ("systolic_bp", 124, 119, 0.2),
            ],
        }
        default = [("dose_rate_msv_h", SPE_PEAK_MSV_H, 0.075, 0.8)] if domain == "radiation" else []
        return [
            {"feature": f, "value": v, "baseline": b, "contribution": c}
            for f, v, b, c in catalogue.get((code, domain), default)
        ]

    # ------------------------------------------------------------------ alerts & care
    def alert(self, code: str, at: datetime, **fields: Any) -> Alert:
        alert = self.add(Alert(crew_member_id=self.crew[code].id, triggered_at=at, **fields))
        self.log(
            at, "Moteur IA", "alert.trigger", alert, level=alert.level.value, rule=alert.rule_code
        )
        return alert

    def acknowledge(self, alert: Alert, at: datetime, comment: str) -> None:
        alert.status, alert.acknowledged_at = AlertStatus.ACKNOWLEDGED, at
        alert.acknowledged_by_id, alert.ack_comment = self.cmo.id, comment
        self.log(at, "AV-04", "alert.acknowledge", alert, comment=comment)

    def resolve(self, alert: Alert, at: datetime) -> None:
        alert.status, alert.resolved_at = AlertStatus.RESOLVED, at
        self.log(at, "AV-04", "alert.resolve", alert)

    def run_protocol(
        self,
        code: str,
        protocol_code: str,
        alert: Alert | None,
        start: datetime,
        steps_done: int,
        *,
        total: int | None = None,
        efficacy: float | None = None,
    ) -> ProtocolRun:
        protocol = self.protocols[protocol_code]
        step_codes = {
            "PRT-STRESS-01": ["settle", "breathing", "hrv_check", "sleep_plan"],
            "PRT-RAD-02": ["shelter", "notify", "dosimeter", "exit"],
            "PRT-SANS-01": ["acuity", "amsler", "oct", "notify_cmo"],
            "PRT-EX-03": ["day1", "day2", "day3", "back_to_plan"],
            "EMRG-01": ["secure", "assess", "sensors", "oxygen", "call_cmo", "monitor"],
        }[protocol_code]
        gap = timedelta(minutes=(protocol.expected_duration_min or 12) / len(step_codes))
        if protocol_code == "PRT-EX-03":
            gap = timedelta(days=1)
        steps = [
            {"code": s, "validated_at": (start + gap * (i + 1)).isoformat()}
            for i, s in enumerate(step_codes[:steps_done])
        ]
        complete = steps_done == len(step_codes)
        run = self.add(
            ProtocolRun(
                protocol_id=protocol.id,
                alert_id=alert.id if alert else None,
                crew_member_id=self.crew[code].id,
                status=ProtocolRunStatus.COMPLETED if complete else ProtocolRunStatus.IN_PROGRESS,
                steps=steps,
                started_at=start,
                ended_at=start + gap * len(step_codes) if complete else None,
                efficacy=efficacy,
            )
        )
        self.log(start, code, "protocol.start", run, protocol=protocol_code)
        if complete:
            self.log(run.ended_at, code, "protocol.complete", run, efficacy=efficacy)
        return run

    def use_item(
        self,
        item_code: str,
        at: datetime,
        quantity: float,
        patient: str | None,
        note: str,
        **links: Any,
    ) -> None:
        usage = self.add(
            InventoryUsage(
                item_id=self.items[item_code].id,
                patient_id=self.crew[patient].id if patient else None,
                recorded_by_id=self.cmo.id,
                quantity=quantity,
                used_at=at,
                note=note,
                **links,
            )
        )
        self.log(at, "AV-04", "inventory.use", usage, item=item_code, quantity=quantity)

    def consult(
        self, patient: str, at: datetime, title: str, body: str, alert: Alert | None = None
    ) -> None:
        note = self.add(
            ConsultationNote(
                patient_id=self.crew[patient].id,
                author_id=self.cmo.id,
                alert_id=alert.id if alert else None,
                written_at=at,
                title=title,
                body=body,
            )
        )
        self.log(at, "AV-04", "consultation.write", note, patient=patient)

    def build_clinical_story(self, spe: SpaceWeatherEvent) -> list[Alert]:
        n = self.now
        alerts: list[Alert] = []

        # Alerte d'information de routine, au début de la fenêtre.
        info = self.alert(
            "AV-03",
            self.start + timedelta(days=2, hours=10),
            level=AlertLevel.INFO,
            domain=RiskDomain.IMMUNE,
            method=DetectionMethod.CHECKIN,
            title="Irritation cutanée signalée",
            message="Rougeur à l'avant-bras déclarée au check-in.",
            factors=[],
        )
        self.acknowledge(
            info, info.triggered_at + timedelta(hours=3), "Crème émolliente, revoir dans 48 h."
        )
        self.resolve(info, info.triggered_at + timedelta(days=2))
        alerts.append(info)

        # Rejeu de S3 : alerte radiation CRITICAL pour chaque membre, toutes résolues après l'abri.
        for code in self.crew:
            a = self.alert(
                code,
                self.spe_start + timedelta(minutes=2),
                level=AlertLevel.CRITICAL,
                domain=RiskDomain.RADIATION,
                method=DetectionMethod.THRESHOLD,
                rule_code="RAD-SPE-01",
                title="Événement à particules solaires",
                message=(
                    "Débit de dose prévu 1,82 mSv/h hors abri. "
                    "Rejoindre l'abri blindé B2 avant la fin du compte à rebours."
                ),
                metric=None,
                observed_value=SPE_PEAK_MSV_H,
                threshold=0.5,
                recommended_protocol_id=self.protocols["PRT-RAD-02"].id,
                factors=self._factors(code, "radiation", 80),
            )
            self.acknowledge(
                a, self.spe_start + timedelta(minutes=6), "Équipage à l'abri, dosimètres actifs."
            )
            self.resolve(a, spe.ended_at)
            self.run_protocol(
                code, "PRT-RAD-02", a, self.spe_start + timedelta(minutes=3), 4, efficacy=0.9
            )
            alerts.append(a)

        # AV-02: resting HR episode (resolved), then persistent low HRV (open).
        hr = self.alert(
            "AV-02",
            n - timedelta(hours=72),
            level=AlertLevel.WARNING,
            domain=RiskDomain.CARDIO,
            method=DetectionMethod.ROBUST_ZSCORE,
            rule_code="HR-02",
            title="FC au repos élevée",
            message="96 bpm, z-score robuste 2,8.",
            metric=Metric.HEART_RATE,
            observed_value=96,
            threshold=2.5,
            factors=[{"feature": "heart_rate", "value": 96, "baseline": 64, "contribution": 0.8}],
        )
        self.acknowledge(
            hr, hr.triggered_at + timedelta(hours=1), "Effort récent, hydratation. Recontrôle."
        )
        self.resolve(hr, hr.triggered_at + timedelta(hours=5))
        hrv = self.alert(
            "AV-02",
            n - timedelta(hours=8),
            level=AlertLevel.WARNING,
            domain=RiskDomain.BEHAVIORAL,
            method=DetectionMethod.TREND,
            rule_code="HRV-01",
            title="VFC basse persistante",
            message="VFC à 65 % de la baseline, sommeil < 6 h.",
            metric=Metric.HRV_RMSSD,
            observed_value=31,
            threshold=38.4,
            recommended_protocol_id=self.protocols["PRT-STRESS-01"].id,
            factors=self._factors("AV-02", "behavioral", 68),
        )
        self.run_protocol("AV-02", "PRT-STRESS-01", hrv, n - timedelta(hours=7, minutes=30), 2)
        alerts += [hr, hrv]

        # AV-01: three missed ARED sessions (acknowledged yesterday).
        ex = self.alert(
            "AV-01",
            n - timedelta(hours=26),
            level=AlertLevel.WARNING,
            domain=RiskDomain.MUSCULOSKELETAL,
            method=DetectionMethod.THRESHOLD,
            rule_code="EX-MISSED-01",
            title="Séances d'exercice manquées",
            message="3 séances ARED consécutives.",
            recommended_protocol_id=self.protocols["PRT-EX-03"].id,
            factors=self._factors("AV-01", "musculoskeletal", 52),
        )
        self.acknowledge(
            ex,
            n - timedelta(hours=22),
            "Replanifier l'ARED en début de journée, plan de rattrapage 3 jours.",
        )
        self.run_protocol("AV-01", "PRT-EX-03", ex, n - timedelta(hours=21), 1)
        alerts.append(ex)

        # AV-04: SANS suspicion.
        sans = self.alert(
            "AV-04",
            n - timedelta(hours=2),
            level=AlertLevel.WARNING,
            domain=RiskDomain.CARDIO,
            domain_label="Neuro-oculaire",
            method=DetectionMethod.CHECKIN,
            rule_code="SANS-01",
            title="Suspicion SANS",
            message="Vision floue et céphalées depuis 2 jours.",
            recommended_protocol_id=self.protocols["PRT-SANS-01"].id,
            factors=self._factors("AV-04", "cardio", 47),
        )
        self.run_protocol("AV-04", "PRT-SANS-01", sans, n - timedelta(hours=1, minutes=40), 2)
        self.use_item(
            "MED-PARA-500", n - timedelta(hours=28), 1, "AV-04", "Céphalée de fin de journée."
        )
        alerts.append(sans)

        # AV-03: tachycardia + desaturation → emergency mode.
        crit = self.alert(
            "AV-03",
            n - timedelta(minutes=4),
            level=AlertLevel.CRITICAL,
            domain=RiskDomain.CARDIO,
            method=DetectionMethod.ISOLATION_FOREST,
            rule_code="CARDIO-CRIT-01",
            title="Tachycardie et désaturation",
            message="FC 128 bpm, SpO₂ 92 %.",
            metric=Metric.HEART_RATE,
            observed_value=128,
            threshold=120,
            recommended_protocol_id=self.protocols["EMRG-01"].id,
            factors=self._factors("AV-03", "cardio", 84),
        )
        emergency = self.add(
            EmergencyEvent(
                patient_id=self.crew["AV-03"].id,
                triggered_by_id=self.crew["AV-01"].id,
                status=EmergencyStatus.ACTIVE,
                triggered_at=n - timedelta(minutes=3),
                steps=[
                    {"code": "secure", "validated_at": (n - timedelta(minutes=2)).isoformat()},
                    {"code": "assess", "validated_at": (n - timedelta(minutes=1)).isoformat()},
                ],
            )
        )
        self.log(emergency.triggered_at, "AV-01", "emergency.trigger", emergency, patient="AV-03")
        run = self.run_protocol("AV-03", "EMRG-01", crit, n - timedelta(minutes=3), 2)
        self.use_item(
            "EQ-O2-PORT",
            n - timedelta(minutes=1),
            1,
            "AV-03",
            "Oxygène 2 L/min au masque.",
            emergency_id=emergency.id,
            protocol_run_id=run.id,
        )
        alerts.append(crit)

        # Une urgence plus ancienne et clôturée (mal des transports au début de la fenêtre).
        old = self.add(
            EmergencyEvent(
                patient_id=self.crew["AV-02"].id,
                triggered_by_id=self.crew["AV-02"].id,
                closed_by_id=self.cmo.id,
                status=EmergencyStatus.CLOSED,
                triggered_at=self.start + timedelta(days=1, hours=3),
                steps=[{"code": "secure"}, {"code": "assess"}, {"code": "call_cmo"}],
                outcome="stabilisée",
                closed_at=self.start + timedelta(days=1, hours=3, minutes=40),
                summary="Malaise vagal après effort, résolu sans séquelle.",
            )
        )
        self.log(old.triggered_at, "AV-02", "emergency.trigger", old)
        self.log(old.closed_at, "AV-04", "emergency.close", old, outcome="stabilisée")
        self.use_item(
            "MED-PROM-25",
            old.triggered_at + timedelta(minutes=20),
            1,
            "AV-02",
            "Nausées associées.",
            emergency_id=old.id,
        )
        self.use_item(
            "MED-MELA-3",
            n - timedelta(hours=40),
            1,
            "AV-02",
            "Aide à l'endormissement, consigne sol.",
        )

        self.consult(
            "AV-02",
            n - timedelta(hours=6),
            "VFC basse et dette de sommeil",
            "VFC 31 ms (baseline 48). Sommeil 5 h 30 sur 3 nuits. "
            "Respiration guidée débutée, réévaluation à 72 h.",
            hrv,
        )
        self.consult(
            "AV-04",
            n - timedelta(hours=1, minutes=30),
            "Troubles visuels",
            "Acuité 8/10 OD, Amsler sans métamorphopsie. OCT à "
            "réaliser, transmis au flight surgeon.",
            sans,
        )
        self.consult(
            "AV-01",
            n - timedelta(hours=21),
            "Déconditionnement",
            "Trois séances ARED manquées. Lombalgie 2/3. Plan de rattrapage PRT-EX-03.",
            ex,
        )
        return alerts

    # ------------------------------------------------------------------ sync
    def packet(
        self,
        at: datetime,
        kind: SyncPacketKind,
        priority: int,
        content: dict[str, Any],
        member: CrewMember | None = None,
        *,
        status: SyncPacketStatus = SyncPacketStatus.ACKNOWLEDGED,
    ) -> SyncPacket:
        payload = gzip.compress(
            json.dumps(content, ensure_ascii=False, default=str).encode(), mtime=0
        )
        latency = timedelta(seconds=self.mission.one_way_latency_s)
        sent = at + timedelta(minutes=30) if status is not SyncPacketStatus.QUEUED else None
        packet = self.add(
            SyncPacket(
                crew_member_id=member.id if member else None,
                kind=kind,
                priority=priority,
                status=status,
                payload_gz=payload,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                created_at=at,
                sent_at=sent,
                acknowledged_at=sent + 2 * latency
                if status is SyncPacketStatus.ACKNOWLEDGED
                else None,
            )
        )
        if sent:
            self.log(sent, "Système", "sync.export", packet, kind=kind.value, bytes=len(payload))
        return packet

    def build_sync(self, alerts: list[Alert]) -> None:
        for day in range(self.days):
            at = self.start + timedelta(days=day + 1, hours=1)
            summary = {
                "mission_day": (at.date() - self.mission.start_date).days,
                "crew": {code: {"status": "nominal"} for code in self.crew},
            }
            self.packet(at, SyncPacketKind.DAILY_SUMMARY, PRIORITY_NORMAL, summary)
        for alert in alerts:
            if alert.level is AlertLevel.INFO:
                continue
            recent = self.hours_before_now(alert.triggered_at) < 9
            self.packet(
                alert.triggered_at + timedelta(minutes=1),
                SyncPacketKind.ALERT,
                PRIORITY_CRITICAL if alert.level is AlertLevel.CRITICAL else PRIORITY_HIGH,
                {"alert_id": alert.id, "title": alert.title, "level": alert.level.value},
                alert.crew_member,
                status=SyncPacketStatus.QUEUED if recent else SyncPacketStatus.ACKNOWLEDGED,
            )
        self.packet(
            self.now - timedelta(minutes=2),
            SyncPacketKind.EMERGENCY,
            PRIORITY_CRITICAL,
            {"patient": "AV-03", "hr": 128, "spo2": 92},
            self.crew["AV-03"],
            status=SyncPacketStatus.QUEUED,
        )
        self.packet(
            self.now - timedelta(days=5),
            SyncPacketKind.TIMESERIES,
            PRIORITY_NORMAL,
            {"metric": "hrv_rmssd", "days": 7},
            self.crew["AV-02"],
            status=SyncPacketStatus.FAILED,
        )

        messages = [
            (
                "AV-02",
                21,
                "Consigne sommeil",
                "Prolonger la fenêtre de sommeil de 45 min pendant 3 "
                "nuits. Réévaluer la VFC dans 3 jours.",
                True,
            ),
            (
                None,
                46,
                "Météo spatiale",
                "Activité solaire en baisse après l'événement d'hier. "
                "Reprise normale des EVA autorisée.",
                False,
            ),
            (
                "AV-01",
                20,
                "Plan d'exercice",
                "Plan de rattrapage ARED validé par le sol. Priorité "
                "aux squats et soulevés de terre.",
                True,
            ),
            (
                "AV-04",
                1,
                "Suivi SANS",
                "Merci de réaliser l'OCT avant la prochaine fenêtre et de transmettre les images.",
                True,
            ),
        ]
        latency = timedelta(seconds=self.mission.one_way_latency_s)
        for code, hours_ago, subject, body, instruction in messages:
            sent = self.now - timedelta(hours=hours_ago)
            message = self.add(
                GroundMessage(
                    crew_member_id=self.crew[code].id if code else None,
                    author="Dr M. Reyes · Houston",
                    subject=subject,
                    body=body,
                    is_instruction=instruction,
                    sha256=hashlib.sha256(body.encode()).hexdigest(),
                    sent_at=sent,
                    received_at=sent + latency,
                    read_at=sent + latency + timedelta(minutes=40) if hours_ago > 2 else None,
                )
            )
            self.log(sent + latency, "Système", "ground.import", message, subject=subject)

    # ------------------------------------------------------------------ simulation
    def build_sim_runs(self) -> None:
        scenarios = {s.code: s for s in self.session.scalars(select(SimScenario))}
        for code, member, hours_ago, status in (
            ("S1", None, 120, SimRunStatus.COMPLETED),
            ("S2", "AV-02", 30, SimRunStatus.ABORTED),
        ):
            started = self.now - timedelta(hours=hours_ago)
            run = self.add(
                SimRun(
                    scenario_id=scenarios[code].id,
                    crew_member_id=self.crew[member].id if member else None,
                    status=status,
                    seed=42,
                    speed_factor=60,
                    started_at=started,
                    ended_at=started + timedelta(minutes=25),
                )
            )
            target = self.crew[member or "AV-03"]
            # Quelques mesures étiquetées : supprimer l'exécution les supprime en cascade (F15).
            self.session.add_all(
                VitalReading(
                    crew_member_id=target.id,
                    sim_run_id=run.id,
                    metric=Metric.HEART_RATE,
                    value=70 + i,
                    quality=1.0,
                    source=DataSource.SIMULATOR,
                    recorded_at=started + timedelta(minutes=i),
                    received_at=started + timedelta(minutes=i),
                )
                for i in range(10)
            )
            self.log(started, "AV-04", "sim.start", run, scenario=code, speed=60)

    # ------------------------------------------------------------------ audit
    def write_audit(self) -> int:
        prev = (
            self.session.scalars(select(AuditLog.entry_hash).order_by(AuditLog.id.desc())).first()
            or GENESIS_HASH
        )
        for event in sorted(self.audit, key=lambda e: e.at):
            entry = {
                "at": event.at,
                "actor_label": event.actor_label,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "details": event.details,
            }
            digest = AuditLog.compute_hash(prev, **entry)
            self.session.add(
                AuditLog(actor_id=event.actor_id, prev_hash=prev, entry_hash=digest, **entry)
            )
            prev = digest
        self.session.flush()
        return len(self.audit)

    def build(self) -> None:
        self.build_vitals()
        spe = self.build_radiation()
        self.build_wellness()
        self.build_scores()
        alerts = self.build_clinical_story(spe)
        self.build_sync(alerts)
        self.build_sim_runs()
        self.write_audit()


def generate_history(
    session: Session, now: datetime = DEMO_NOW, days: int = HISTORY_DAYS, seed: int = 142
) -> None:
    """Remplir chaque table opérationnelle avec un historique fictif cohérent jusqu'à ``now``."""
    HistoryBuilder(session, now=now, days=days, seed=seed).build()
