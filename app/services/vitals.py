"""Dernières constantes pour le tableau de bord (GET /crew/{code}/vitals/latest).

Cohérent avec le moteur de risque : même nettoyage (plages plausibles, qualité minimale,
simulations exclues), mêmes références individuelles et même z-score robuste.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import stats
from app.engine.config import load_config
from app.engine.features import Z_FLOOR, is_plausible
from app.models import Baseline, CrewMember, VitalReading
from app.models.enums import METRIC_UNITS, HealthLevel, Metric
from app.schemas.telemetry import CrewVitalsLatest, NormalBand, VitalLatestItem, VitalPoint
from app.services.views import as_utc

POINTS = 36
# Mesures affichées sur le tableau de bord ; activité et CO2 cabine sont du contexte.
DASHBOARD_METRICS = (
    Metric.HEART_RATE,
    Metric.HRV_RMSSD,
    Metric.SPO2,
    Metric.RESPIRATORY_RATE,
    Metric.CORE_TEMPERATURE,
    Metric.SYSTOLIC_BP,
    Metric.DIASTOLIC_BP,
)
# La VFC protège : seule une baisse est anormale. Pareil pour la SpO2 : seule une chute.
LOWER_IS_WORSE = {Metric.HRV_RMSSD, Metric.SPO2}


def level_for(metric: Metric, value: float, baseline: Baseline | None) -> HealthLevel:
    """Couleur de la carte, avec les mêmes seuils que les règles du moteur (rules.yaml).

    SpO2 et température suivent des seuils cliniques (SPO2-CRIT-01, TEMP-01) ; la VFC son
    ratio à la référence (HRV-01 : < 80 %) ; les autres un z-score robuste (|z| ≥ 2 / 3).
    """
    if metric is Metric.SPO2:
        if value <= 90:
            return HealthLevel.CRITICAL
        return HealthLevel.WARNING if value < 94 else HealthLevel.NOMINAL
    if metric is Metric.CORE_TEMPERATURE:
        if value >= 39.5:
            return HealthLevel.CRITICAL
        return HealthLevel.WARNING if value >= 38.0 else HealthLevel.NOMINAL
    if metric is Metric.HRV_RMSSD and baseline is not None and baseline.mean:
        ratio = value / baseline.mean
        if ratio < 0.6:
            return HealthLevel.CRITICAL
        return HealthLevel.WARNING if ratio < 0.8 else HealthLevel.NOMINAL
    if baseline is None or baseline.median is None:
        return HealthLevel.NOMINAL
    z = stats.robust_z(value, baseline.median, baseline.mad, Z_FLOOR.get(metric, 0.5))
    if z is None:
        return HealthLevel.NOMINAL
    if metric in LOWER_IS_WORSE:
        z = -z  # une hausse de VFC ou de SpO2 n'est jamais un risque
    elif metric not in (Metric.CORE_TEMPERATURE,):
        z = abs(z)
    if z >= 3:
        return HealthLevel.CRITICAL
    if z >= 2:
        return HealthLevel.WARNING
    return HealthLevel.NOMINAL


def trend_pct(values: list[float]) -> float | None:
    """Variation de la dernière valeur par rapport à la moyenne de la fenêtre, en %."""
    if len(values) < 2:
        return None
    reference = sum(values[:-1]) / (len(values) - 1)
    return round((values[-1] - reference) / abs(reference) * 100, 1) if reference else None


def crew_vitals_latest(db: Session, member: CrewMember) -> CrewVitalsLatest:
    cfg = load_config()
    baselines = {
        b.metric: b
        for b in db.scalars(select(Baseline).where(Baseline.crew_member_id == member.id))
    }
    result: dict[Metric, VitalLatestItem] = {}
    for metric in DASHBOARD_METRICS:
        baseline = baselines.get(metric)
        band = (
            NormalBand(
                low=round(baseline.mean - 2 * baseline.std, 2),
                high=round(baseline.mean + 2 * baseline.std, 2),
            )
            if baseline is not None
            else None
        )
        rows = db.scalars(
            select(VitalReading)
            .where(
                VitalReading.crew_member_id == member.id,
                VitalReading.metric == metric,
                VitalReading.is_artifact.is_(False),
                VitalReading.sim_run_id.is_(None),
            )
            .order_by(VitalReading.recorded_at.desc())
            .limit(POINTS * 2)
        ).all()
        clean = [
            r
            for r in reversed(rows)
            if (r.quality is None or r.quality >= cfg.min_quality)
            and is_plausible(metric, r.value, cfg)
        ][-POINTS:]
        if not clean:
            result[metric] = VitalLatestItem(
                metric=metric, unit=METRIC_UNITS[metric], normal_band=band
            )
            continue
        latest = clean[-1]
        result[metric] = VitalLatestItem(
            metric=metric,
            value=latest.value,
            unit=METRIC_UNITS[metric],
            level=level_for(metric, latest.value, baseline),
            trend_pct=trend_pct([r.value for r in clean]),
            normal_band=band,
            recorded_at=as_utc(latest.recorded_at),
            points=[
                VitalPoint(
                    t=as_utc(r.recorded_at), value=r.value, quality=r.quality, is_artifact=False
                )
                for r in clean
            ],
        )
    return CrewVitalsLatest(crew_id=member.code, vitals=result)
