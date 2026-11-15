"""Moteur de risque (§6) : tests unitaires et tests d'acceptation sur l'histoire de démo."""

from __future__ import annotations

from datetime import timedelta

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.engine import stats
from app.engine.config import Indicator, load_config
from app.engine.pipeline import run_once
from app.engine.scoring import confirmed, evaluate, level_for
from app.models import Alert, CrewMember, RadiationDose, RiskScore, VitalReading
from app.models.enums import AlertStatus, DataSource, HealthLevel, Metric, RiskDomain
from app.seed import seed
from app.sim.history import DEMO_NOW


@pytest.fixture
def demo(db: Session) -> Session:
    seed(db)
    return db


def _member(db: Session, code: str) -> CrewMember:
    return db.scalars(select(CrewMember).where(CrewMember.code == code)).one()


# --------------------------------------------------------------------- unit
def test_robust_z_uses_a_dispersion_floor() -> None:
    assert stats.robust_z(80, 64, 0.0, floor=2.0) == 8.0
    assert stats.robust_z(None, 64, 3, floor=2.0) is None
    assert round(stats.robust_z(70, 64, 3, floor=2.0), 2) == round(6 / (3 * 1.4826), 2)


def test_slope_per_hour() -> None:
    assert stats.slope_per_hour([0, 1, 2, 3], [10, 12, 14, 16]) == pytest.approx(2.0)
    assert stats.slope_per_hour([0, 1], [1, 2]) is None


def test_indicator_severity_both_directions() -> None:
    higher_is_worse = Indicator("stress", 3, 9, 1, "Stress")
    lower_is_worse = Indicator("spo2_now", 96, 88, 1, "SpO2")
    assert higher_is_worse.severity(6) == 0.5
    assert lower_is_worse.severity(92) == 0.5
    assert lower_is_worse.severity(99) == 0.0 and lower_is_worse.severity(80) == 1.0
    assert higher_is_worse.severity(None) == 0.0


def test_levels_follow_spec_thresholds() -> None:
    assert [level_for(s) for s in (0, 39.9, 40, 69.9, 70, 100)] == [
        HealthLevel.NOMINAL,
        HealthLevel.NOMINAL,
        HealthLevel.WARNING,
        HealthLevel.WARNING,
        HealthLevel.CRITICAL,
        HealthLevel.CRITICAL,
    ]


def test_rules_suppression_and_confirmation() -> None:
    rules = load_config().rules
    tachy = {"hr_now": 130, "spo2_now": 91, "hr_z": 5, "anomaly_score": 0.95}
    fired = {r.code for r in evaluate(rules, tachy)}
    assert "CARDIO-CRIT-01" in fired
    assert not fired & {"HR-02", "ANOMALY-01"}  # masquée par la règle critique spécifique

    warning_now = evaluate(rules, {"hr_z": 3.0})
    assert [r.code for r in warning_now] == ["HR-02"]
    assert confirmed(warning_now, previous=[]) == []  # WARNING needs two evaluations
    assert confirmed(warning_now, previous=warning_now) == warning_now
    critical = evaluate(rules, {"dose_rate_msv_h": 0.5})
    assert confirmed(critical, previous=[]) == critical  # CRITICAL se déclenche tout de suite


def test_rules_match_the_protocol_library() -> None:
    """Chaque règle qui recommande un protocole figure dans le déclencheur de ce protocole."""
    for rule in load_config().rules:
        if not rule.protocol or rule.protocol == "EMRG-01":
            continue
        spec = yaml.safe_load(
            (BASE_DIR / "app" / "protocols" / f"{rule.protocol.lower()}.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert rule.code in spec["trigger"]["rules"], rule.code


# --------------------------------------------------------------------- acceptance (demo story)
def test_engine_finds_the_demo_story(demo: Session) -> None:
    report = run_once(demo)
    by_code = {m.code: m for m in report.members}
    assert {c: m.status for c, m in by_code.items()} == {
        "AV-01": "warning",
        "AV-02": "warning",
        "AV-03": "critical",
        "AV-04": "warning",
    }
    assert "EX-MISSED-01" in by_code["AV-01"].rules  # S5 deconditioning
    assert "HRV-01" in by_code["AV-02"].rules  # S2 : stress et dette de sommeil
    assert "CARDIO-CRIT-01" in by_code["AV-03"].rules  # tachycardia + desaturation
    assert "SANS-01" in by_code["AV-04"].rules  # S4 SANS suspicion
    assert by_code["AV-03"].anomaly_score > by_code["AV-01"].anomaly_score


def test_open_alerts_are_not_duplicated_and_runs_are_idempotent(demo: Session) -> None:
    before = len(demo.scalars(select(Alert)).all())
    first = run_once(demo)
    assert first.new_alert_ids == []  # les alertes de l'histoire sont déjà ouvertes
    assert len(demo.scalars(select(Alert)).all()) == before
    second = run_once(demo)
    assert all(m.skipped for m in second.members)  # pas de nouvelle mesure → rien d'écrit


def test_scores_are_explained(demo: Session) -> None:
    run_once(demo)
    model = load_config().model_version
    av02 = _member(demo, "AV-02")
    behavioral = demo.scalars(
        select(RiskScore).where(
            RiskScore.crew_member_id == av02.id,
            RiskScore.domain == RiskDomain.BEHAVIORAL,
            RiskScore.model_version == model,
        )
    ).one()
    features = [f["feature"] for f in behavioral.factors]
    assert features[0] == "hrv_ratio"
    assert 0 < len(behavioral.factors) <= 3
    assert abs(sum(f["contribution"] for f in behavioral.factors) - 1) <= 0.35


def test_radiation_storm_raises_a_critical_alert_at_once(demo: Session) -> None:
    member = _member(demo, "AV-01")
    last = demo.scalars(
        select(RadiationDose)
        .where(RadiationDose.crew_member_id == member.id)
        .order_by(RadiationDose.recorded_at.desc())
    ).first()
    at = DEMO_NOW + timedelta(minutes=10)
    demo.add(
        RadiationDose(
            crew_member_id=member.id,
            recorded_at=at,
            dose_rate_msv_h=1.82,
            mission_cumulative_msv=last.mission_cumulative_msv + 0.3,
            career_cumulative_msv=last.career_cumulative_msv + 0.3,
            neutron_fraction=0.05,
            source=DataSource.SENSOR,
        )
    )
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.HEART_RATE,
            value=70,
            recorded_at=at,
            received_at=at,
        )
    )
    demo.commit()

    report = run_once(demo, at=at)
    av01 = next(m for m in report.members if m.code == "AV-01")
    assert "RAD-SPE-01" in av01.rules and av01.status == "critical"
    alert = demo.get(Alert, av01.new_alert_ids[0])
    assert alert.rule_code == "RAD-SPE-01" and alert.recommended_protocol.code == "PRT-RAD-02"
    assert alert.status is AlertStatus.OPEN and "1.820" in alert.message


def test_isolated_spike_is_not_confirmed(demo: Session) -> None:
    """Une seule mesure anormale ne doit pas lever de WARNING (confirmation, §6.3)."""
    member = _member(demo, "AV-04")
    at = DEMO_NOW + timedelta(minutes=10)
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.HEART_RATE,
            value=140,
            recorded_at=at,
            received_at=at,
        )
    )
    demo.commit()
    report = run_once(demo, at=at)
    av04 = next(m for m in report.members if m.code == "AV-04")
    assert "HR-02" not in av04.rules


def test_artifacts_are_rejected(demo: Session) -> None:
    member = _member(demo, "AV-02")
    at = DEMO_NOW + timedelta(minutes=10)
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.HEART_RATE,
            value=400,
            recorded_at=at,
            received_at=at,
        )
    )
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.SPO2,
            value=97,
            quality=0.2,
            recorded_at=at,
            received_at=at,
        )
    )
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.HRV_RMSSD,
            value=33,
            recorded_at=at,
            received_at=at,
        )
    )
    demo.commit()
    report = run_once(demo, at=at)
    av02 = next(m for m in report.members if m.code == "AV-02")
    assert "CARDIO-CRIT-01" not in av02.rules and av02.status != "critical"


# --------------------------------------------------------------------- engine completion
def test_baselines_are_refreshed_from_flight_data(demo: Session) -> None:
    from app.models import Baseline

    run_once(demo)
    av02 = _member(demo, "AV-02")
    hrv = demo.scalars(
        select(Baseline).where(
            Baseline.crew_member_id == av02.id, Baseline.metric == Metric.HRV_RMSSD
        )
    ).one()
    assert hrv.computed_at.replace(tzinfo=None) == DEMO_NOW.replace(tzinfo=None)
    assert hrv.sample_count > 48 and hrv.sample_count != 1240
    # L'écart garde la dérive récente hors de la référence : elle reste proche d'avant la dérive.
    assert 44 < hrv.mean < 54


def test_anomaly_models_are_persisted_with_joblib(demo: Session) -> None:
    from pathlib import Path

    from app.core.config import get_settings

    run_once(demo)
    files = sorted(Path(get_settings().models_dir).glob("isolation_forest_AV-0*_*.joblib"))
    assert {f.name.split("_")[2] for f in files} >= {"AV-01", "AV-02", "AV-03", "AV-04"}


def test_goes_storm_raises_the_early_warning(demo: Session) -> None:
    from app.models import DatasetSource, ProtonFluxReading

    source = demo.scalars(
        select(DatasetSource).where(DatasetSource.code == "noaa-goes-protons")
    ).one()
    at = DEMO_NOW + timedelta(minutes=10)
    # GOES publie toutes les 5 min : deux relevés de suite > 10 pfu confirment la tempête.
    for minutes, flux in ((5, 180.0), (0, 250.0)):
        demo.add(
            ProtonFluxReading(
                source_id=source.id,
                measured_at=at - timedelta(minutes=minutes),
                satellite=18,
                energy_band=">=10 MeV",
                flux_pfu=flux,
            )
        )
    for member in demo.scalars(select(CrewMember)):
        demo.add(
            VitalReading(
                crew_member_id=member.id,
                metric=Metric.HEART_RATE,
                value=66,
                recorded_at=at,
                received_at=at,
            )
        )
    demo.commit()
    report = run_once(demo, at=at)
    assert all("GOES-S1-01" in m.rules for m in report.members)
    alert = demo.scalars(select(Alert).where(Alert.rule_code == "GOES-S1-01")).first()
    assert alert.recommended_protocol.code == "PRT-RAD-02" and "250 pfu" in alert.message


def test_hrv_trend_and_bone_projection_features() -> None:
    rules = load_config().rules
    fired = {r.code for r in evaluate(rules, {"hrv_slope_24h": -0.3, "hrv_ratio": 0.85})}
    assert "HRV-TREND-01" in fired
    # Remplacée par la règle de VFC basse persistante quand les deux sont vraies.
    both = {r.code for r in evaluate(rules, {"hrv_slope_24h": -0.3, "hrv_ratio": 0.7, "stress": 8})}
    assert "HRV-01" in both and "HRV-TREND-01" not in both


def test_bone_loss_projection_reflects_adherence(demo: Session) -> None:
    from app.models import FeatureSnapshot

    run_once(demo)
    model = load_config().model_version
    projections = {}
    for snapshot in demo.scalars(select(FeatureSnapshot)):
        if snapshot.features.get("_model") == model:
            code = demo.get(CrewMember, snapshot.crew_member_id).code
            projections[code] = snapshot.features["bone_loss_projection_pct"]
    assert projections["AV-01"] > projections["AV-02"]  # three missed ARED sessions


def test_new_baselines_are_not_duplicated_across_runs(demo: Session) -> None:
    """Une référence créée par le moteur (ex. activité) est mise à jour, pas réinsérée."""
    from app.models import Baseline

    member = _member(demo, "AV-01")
    run_once(demo, force=True)
    later = DEMO_NOW + timedelta(days=2)
    demo.add(
        VitalReading(
            crew_member_id=member.id,
            metric=Metric.HEART_RATE,
            value=65,
            recorded_at=later,
            received_at=later,
        )
    )
    demo.commit()
    run_once(demo, at=later, force=True)
    activity = demo.scalars(
        select(Baseline).where(
            Baseline.crew_member_id == member.id, Baseline.metric == Metric.ACTIVITY_LEVEL
        )
    ).all()
    assert len(activity) == 1
