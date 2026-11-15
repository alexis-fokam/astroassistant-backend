"""Extraction des indicateurs d'un membre à un instant donné (§6.1, §6.2).

Tout ce dont les règles et le score ont besoin est aplati en un ``dict[str, float | None]``,
pour stocker un instantané en JSON et l'expliquer indicateur par indicateur.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.engine import stats
from app.engine.config import EngineConfig
from app.models import (
    Baseline,
    Checkin,
    CrewMember,
    ExerciseSession,
    ProtonFluxReading,
    PvtResult,
    RadiationDose,
    SleepSession,
    VitalReading,
)
from app.models.enums import ExerciseKind, Metric, SessionStatus

Features = dict[str, float | None]

CHECKIN_FIELDS = (
    "headache",
    "vision_change",
    "congestion",
    "back_pain",
    "nausea",
    "dizziness",
    "skin_issue",
    "sleep_quality",
    "mood",
    "stress",
    "isolation",
    "energy",
    "crew_relations",
)
# Dispersion minimale des z-scores robustes, par mesure (évite z → ∞ quand MAD ≈ 0).
GOES_LOOKBACK_H = 3  # Les relevés GOES plus anciens ne sont pas « actuels »
# Hip bone mineral density loss without countermeasures, %/month (LeBlanc et al., 2000;
# NASA HRP « Risk of early onset osteoporosis ») ; l'exercice de résistance en évite l'essentiel.
BONE_LOSS_PCT_MONTH = 1.25
EXERCISE_PROTECTION = 0.8
Z_FLOOR = {Metric.HEART_RATE: 2.0, Metric.SYSTOLIC_BP: 3.0, Metric.HRV_RMSSD: 2.0}


def naive_utc(value: datetime) -> datetime:
    """SQLite renvoie des dates naïves ; le moteur compare tout en UTC naïf."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


@dataclass
class Series:
    """Mesures propres d'une constante, triées par date."""

    times: list[datetime] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def window(self, start: datetime, end: datetime) -> list[float]:
        return self.values[bisect_left(self.times, start) : bisect_right(self.times, end)]

    def last(self, start: datetime, end: datetime) -> float | None:
        values = self.window(start, end)
        return values[-1] if values else None


@dataclass
class MemberData:
    """Tout ce qui est chargé une fois par membre et par exécution du pipeline."""

    member: CrewMember
    series: dict[Metric, Series]
    baselines: dict[Metric, Baseline]
    sleeps: list[SleepSession]
    resistance: list[ExerciseSession]
    pvts: list[PvtResult]
    checkins: list[Checkin]
    doses: list[RadiationDose]
    artifacts: int = 0
    proton_flux: list[tuple[datetime, float]] = field(default_factory=list)


def is_plausible(metric: Metric, value: float, cfg: EngineConfig) -> bool:
    low, high = cfg.plausible.get(metric.value, (float("-inf"), float("inf")))
    return low <= value <= high


def load_member(
    db: Session, member: CrewMember, at: datetime, cfg: EngineConfig, sim_run_id: int | None = None
) -> MemberData:
    at = naive_utc(at)
    days = cfg.windows["baseline_days"] + cfg.windows["baseline_gap_days"]
    start = at - timedelta(days=days)

    def scoped(column):
        # Données de mission, plus les mesures de la simulation en cours s'il y en a une.
        return or_(column.is_(None), column == sim_run_id) if sim_run_id else column.is_(None)

    rows = db.execute(
        select(
            VitalReading.metric,
            VitalReading.value,
            VitalReading.recorded_at,
            VitalReading.quality,
            VitalReading.is_artifact,
        )
        .where(
            VitalReading.crew_member_id == member.id,
            VitalReading.recorded_at >= start,
            VitalReading.recorded_at <= at,
            scoped(VitalReading.sim_run_id),
        )
        .order_by(VitalReading.recorded_at)
    ).all()
    series: dict[Metric, Series] = defaultdict(Series)
    artifacts = 0
    for metric, value, recorded_at, quality, is_artifact in rows:
        metric = Metric(metric)
        if (
            is_artifact
            or (quality is not None and quality < cfg.min_quality)
            or not is_plausible(metric, value, cfg)
        ):
            artifacts += 1
            continue
        s = series[metric]
        s.times.append(naive_utc(recorded_at))
        s.values.append(value)

    def recent(model, column, days_back: int, extra=()):
        return list(
            db.scalars(
                select(model)
                .where(
                    model.crew_member_id == member.id,
                    column >= at - timedelta(days=days_back),
                    column <= at,
                    scoped(model.sim_run_id),
                    *extra,
                )
                .order_by(column)
            )
        )

    return MemberData(
        member=member,
        series=dict(series),
        baselines={b.metric: b for b in member.baselines},
        sleeps=recent(SleepSession, SleepSession.ended_at, 7),
        resistance=recent(
            ExerciseSession,
            ExerciseSession.scheduled_at,
            14,
            (ExerciseSession.kind == ExerciseKind.RESISTANCE,),
        ),
        pvts=recent(PvtResult, PvtResult.taken_at, 10),
        checkins=recent(Checkin, Checkin.submitted_at, 4),
        doses=recent(RadiationDose, RadiationDose.recorded_at, 2),
        artifacts=artifacts,
        proton_flux=[
            (naive_utc(t), flux)
            for t, flux in db.execute(
                select(ProtonFluxReading.measured_at, ProtonFluxReading.flux_pfu)
                .where(
                    ProtonFluxReading.energy_band == ">=10 MeV",
                    ProtonFluxReading.measured_at >= at - timedelta(hours=GOES_LOOKBACK_H),
                    ProtonFluxReading.measured_at <= at,
                )
                .order_by(ProtonFluxReading.measured_at)
            )
        ],
    )


def _baseline(data: MemberData, metric: Metric, at: datetime, cfg: EngineConfig):
    """(moyenne, médiane, MAD) de la référence individuelle : ligne stockée, sinon recalcul."""
    stored = data.baselines.get(metric)
    if stored is not None and stored.median is not None:
        return stored.mean, stored.median, stored.mad
    series = data.series.get(metric)
    if series is None:
        return None, None, None
    end = at - timedelta(days=cfg.windows["baseline_gap_days"])
    values = series.window(end - timedelta(days=cfg.windows["baseline_days"]), end)
    med_mad = stats.median_mad(values)
    if med_mad is None:
        return None, None, None
    return stats.mean(values), *med_mad


def compute(data: MemberData, at: datetime, cfg: EngineConfig) -> Features:
    at = naive_utc(at)
    now_window = timedelta(minutes=cfg.windows["now_minutes"])
    f: Features = {}

    for metric in Metric:
        series = data.series.get(metric)
        if series is None:
            continue
        name = metric.value
        last_1h = series.window(at - timedelta(hours=1), at)
        f[f"{name}_now"] = stats.mean(series.window(at - now_window, at)) or stats.mean(last_1h)
        f[f"{name}_1h"] = stats.mean(last_1h)
        f[f"{name}_24h"] = stats.mean(series.window(at - timedelta(hours=24), at))

    hr_mean, hr_median, hr_mad = _baseline(data, Metric.HEART_RATE, at, cfg)
    f["hr_now"] = f.get("heart_rate_now")
    f["hr_1h"] = f.get("heart_rate_1h")
    f["hr_z"] = stats.robust_z(f["hr_1h"], hr_median, hr_mad, Z_FLOOR[Metric.HEART_RATE])
    f["hr_baseline"] = hr_median

    hrv_mean, _, _ = _baseline(data, Metric.HRV_RMSSD, at, cfg)
    f["hrv_24h"] = f.get("hrv_rmssd_24h")
    f["hrv_baseline"] = hrv_mean
    f["hrv_ratio"] = f["hrv_24h"] / hrv_mean if f["hrv_24h"] and hrv_mean else None
    f["hrv_ratio_pct"] = f["hrv_ratio"] * 100 if f["hrv_ratio"] is not None else None
    f["hrv_threshold"] = 0.8 * hrv_mean if hrv_mean else None
    hrv = data.series.get(Metric.HRV_RMSSD)
    if hrv is not None:
        day = [
            (t, v)
            for t, v in zip(hrv.times, hrv.values, strict=True)
            if t >= at - timedelta(hours=24)
        ]
        f["hrv_slope_24h"] = stats.slope_per_hour(
            [(t - at).total_seconds() / 3600 for t, _ in day], [v for _, v in day]
        )
        if f["hrv_slope_24h"] is not None:
            f["hrv_slope_day"] = f["hrv_slope_24h"] * 24

    _, sys_median, sys_mad = _baseline(data, Metric.SYSTOLIC_BP, at, cfg)
    systolic = data.series.get(Metric.SYSTOLIC_BP)
    sys_last = systolic.last(at - timedelta(hours=24), at) if systolic else None
    f["systolic_bp_last"] = sys_last
    f["systolic_bp_z"] = stats.robust_z(sys_last, sys_median, sys_mad, Z_FLOOR[Metric.SYSTOLIC_BP])

    _, spo2_median, _ = _baseline(data, Metric.SPO2, at, cfg)
    f["spo2_baseline"] = spo2_median
    f["activity_24h"] = f.get("activity_level_24h")

    # Sommeil (F7) : trois dernières nuits terminées.
    nights = [s for s in data.sleeps if naive_utc(s.ended_at) <= at][-3:]
    hours = [
        (naive_utc(s.ended_at) - naive_utc(s.started_at)).total_seconds() / 3600 for s in nights
    ]
    f["sleep_hours_3n"] = stats.mean(hours)
    f["short_nights_3n"] = float(sum(h < 6 for h in hours)) if hours else None

    # Exercice (F6) : séances de résistance manquées d'affilée, plus récentes d'abord.
    streak = 0
    for session in reversed([s for s in data.resistance if naive_utc(s.scheduled_at) <= at]):
        if session.status is SessionStatus.PLANNED:
            continue
        if session.status is not SessionStatus.MISSED:
            break
        streak += 1
    f["missed_resistance_streak"] = float(streak)
    done = [
        s
        for s in data.resistance
        if naive_utc(s.scheduled_at) <= at and s.status is not SessionStatus.PLANNED
    ]
    if done:
        adherence = sum(s.status is SessionStatus.COMPLETED for s in done) / len(done)
        mission = data.member.mission
        rate = BONE_LOSS_PCT_MONTH * (1 - EXERCISE_PROTECTION * adherence)
        f["exercise_adherence_14d"] = adherence
        f["bone_loss_rate_pct_month"] = rate
        # Perte osseuse de la hanche projetée en fin de mission à assiduité constante.
        f["bone_loss_projection_pct"] = (
            rate * mission.planned_duration_days / 30 if mission else None
        )

    # Vigilance (F8) : dernier PVT comparé au temps de réaction habituel du membre.
    pvts = [p for p in data.pvts if naive_utc(p.taken_at) <= at]
    if pvts:
        last = pvts[-1]
        f["pvt_rt_last"] = last.median_rt_ms
        f["pvt_lapses_last"] = float(last.lapses)
        previous = [
            p.median_rt_ms for p in pvts[:-1] if naive_utc(p.taken_at) <= at - timedelta(days=3)
        ]
        usual = stats.median_mad(previous)
        f["pvt_rt_ratio"] = last.median_rt_ms / usual[0] if usual else None

    # Déclaratif (F3) : dernier check-in, et persistance des symptômes sur trois jours.
    checkins = [c for c in data.checkins if naive_utc(c.submitted_at) <= at]
    recent = [
        c
        for c in checkins
        if naive_utc(c.submitted_at) >= at - timedelta(hours=cfg.windows["checkin_hours"])
    ]
    if recent:
        latest = recent[-1]
        for name in CHECKIN_FIELDS:
            value = getattr(latest, name)
            f[name] = float(value) if value is not None else None
    last_3_days = [c for c in checkins if naive_utc(c.submitted_at) >= at - timedelta(hours=72)]
    f["vision_days"] = float(sum((c.vision_change or 0) >= 2 for c in last_3_days))
    f["headache_days"] = float(sum((c.headache or 0) >= 2 for c in last_3_days))

    # Radiation (F5).
    doses = [d for d in data.doses if naive_utc(d.recorded_at) <= at]
    if doses:
        last_dose = doses[-1]
        f["dose_rate_msv_h"] = last_dose.dose_rate_msv_h
        f["dose_rate_ratio"] = last_dose.dose_rate_msv_h / cfg.storm_rate_msv_h
        f["neutron_fraction"] = last_dose.neutron_fraction
        f["career_pct"] = 100 * last_dose.career_cumulative_msv / data.member.career_dose_limit_msv
        f["mission_dose_msv"] = last_dose.mission_cumulative_msv

    # Space weather early warning (F5.4): NOAA GOES >= 10 MeV proton flux.
    flux = [v for t, v in data.proton_flux if at - timedelta(hours=GOES_LOOKBACK_H) <= t <= at]
    f["proton_flux_10mev"] = max(flux) if flux else None

    f["artifacts_rejected"] = float(data.artifacts)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()}


def latest_reading_time(data: MemberData) -> datetime | None:
    times = [s.times[-1] for s in data.series.values() if s.times]
    return max(times) if times else None
