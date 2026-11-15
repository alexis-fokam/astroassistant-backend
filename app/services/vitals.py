from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Baseline, VitalReading, CrewMember
from app.models.enums import HealthLevel, Metric, METRIC_UNITS
from app.schemas.telemetry import CrewVitalsLatest, VitalLatestItem, NormalBand, VitalPoint


def _eval_level(value: float, baseline: Baseline | None) -> HealthLevel:
    if baseline is None or baseline.std == 0:
        return HealthLevel.NOMINAL
    z = abs(value - baseline.mean) / baseline.std
    if z >= 3.0:
        return HealthLevel.CRITICAL
    if z >= 2.0:
        return HealthLevel.WARNING
    return HealthLevel.NOMINAL


def _eval_trend_pct(readings: list[VitalReading]) -> float | None:
    if len(readings) < 2:
        return None
    first = readings[0].value
    last = readings[-1].value
    if first == 0:
        return None
    return round(((last - first) / abs(first)) * 100, 2)


def crew_vitals_latest(db: Session, member: CrewMember) -> CrewVitalsLatest:
    baselines = {
        b.metric: b
        for b in db.scalars(
            select(Baseline).where(Baseline.crew_member_id == member.id)
        ).all()
    }

    result: dict[Metric, VitalLatestItem] = {}

    for metric in Metric:
        unit = METRIC_UNITS.get(metric, "")
        baseline = baselines.get(metric)
        band = (
            NormalBand(
                low=round(baseline.mean - 2 * baseline.std, 2),
                high=round(baseline.mean + 2 * baseline.std, 2),
            )
            if baseline is not None
            else None
        )

        # Récupération des 36 derniers points valides
        rows_desc = db.scalars(
            select(VitalReading)
            .where(
                VitalReading.crew_member_id == member.id,
                VitalReading.metric == metric,
                VitalReading.is_artifact.is_(False),
            )
            .order_by(VitalReading.recorded_at.desc())
            .limit(36)
        ).all()

        if not rows_desc:
            result[metric] = VitalLatestItem(
                metric=metric,
                unit=unit,
                normal_band=band,
            )
            continue

        chronological = list(reversed(rows_desc))
        latest = chronological[-1]

        result[metric] = VitalLatestItem(
            metric=metric,
            value=latest.value,
            unit=unit,
            level=_eval_level(latest.value, baseline),
            trend_pct=_eval_trend_pct(chronological),
            normal_band=band,
            points=[
                VitalPoint(
                    t=r.recorded_at,
                    value=r.value,
                    quality=r.quality,
                    is_artifact=r.is_artifact,
                )
                for r in chronological
            ],
        )

    return CrewVitalsLatest(crew_id=member.code, vitals=result)