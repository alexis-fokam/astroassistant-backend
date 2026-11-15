"""Évaluation du moteur de risque sur des anomalies injectées (§5, indicateurs du jury).

    python -m app.engine.evaluation          # écrit docs/evaluation.json

Pour chaque anomalie que le simulateur peut injecter (tachycardie, chute de SpO2, fièvre,
baisse de VFC, tempête solaire, SANS, déconditionnement) et chaque membre qui ne présente
pas déjà ce trouble dans l'historique de démo, une copie neuve de la base de démo avance pas
à pas jusqu'à ce que la règle attendue se déclenche (ou que le budget de temps s'épuise).
Des exécutions nominales sans injection comptent les fausses alertes. Comme le demande le
cahier des charges : taux de détection, taux de fausses alertes, temps d'inférence par
membre et taille du modèle.
"""

from __future__ import annotations

import json
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, get_settings
from app.engine import anomaly
from app.models import Alert, Base
from app.sim import live

OUTPUT = BASE_DIR / "docs" / "evaluation.json"

# anomalie → (membres sans ce trouble dans l'histoire de démo, vitesse, budget de pas)
PLAN: dict[str, tuple[tuple[str, ...], int, int]] = {
    "tachycardia": (("AV-01", "AV-02", "AV-04"), 60, 30),
    "desaturation": (("AV-01", "AV-02", "AV-04"), 60, 30),
    "fever": (("AV-01", "AV-02", "AV-03"), 60, 60),
    "hrv_drop": (("AV-01", "AV-03", "AV-04"), 1000, 50),
    "radiation": (("all",), 60, 10),
    "sans": (("AV-01", "AV-02", "AV-03"), 60, 5),
    "deconditioning": (("AV-02", "AV-03", "AV-04"), 60, 5),
}
# (vitesse, pas, graine) : 1,5 h, 25 h et 50 h de physiologie normale pour les 4 membres.
NOMINAL_RUNS = ((60, 45, 7), (1000, 45, 11), (1000, 90, 13))


def _session(path: Path) -> Session:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return Session(engine)


def _template(folder: Path, *, history: bool = True) -> Path:
    from app.seed import seed

    path = folder / ("template.db" if history else "template-clean.db")
    with _session(path) as db:
        Base.metadata.create_all(db.get_bind())
        seed(db, history=history)
        db.get_bind().dispose()
    return path


def _fresh(template: Path, folder: Path, name: str) -> Session:
    path = folder / f"{name}.db"
    shutil.copy(template, path)
    anomaly.clear_cache()
    return _session(path)


def _run_trial(
    db: Session, anomaly_code: str, crew: str, speed: int, ticks: int, seed: int
) -> dict:
    state = live.SimState()
    live.start(db, state, run_id=0, scenario="S1", speed=speed, seed=seed, crew=None)
    effect = live.inject(db, state, anomaly_code, crew, actor_label="Évaluation")
    expected = set(effect.kind.expected_rules)
    first_alert = db.scalar(select(Alert.id).order_by(Alert.id.desc())) or 0
    durations = []
    for tick in range(1, ticks + 1):
        report = live.tick(db, state)
        durations.append(report.duration_ms / max(1, len(report.members)))
        raised = db.scalars(
            select(Alert).where(Alert.id > first_alert, Alert.rule_code.in_(expected))
        ).all()
        targets = set(effect.crew_codes)
        if {a.crew_member.code for a in raised} >= targets:
            minutes = (state.sim_time - effect.started_at).total_seconds() / 60
            return {"detected": True, "minutes": round(minutes, 1), "ticks": tick, "ms": durations}
    return {"detected": False, "minutes": None, "ticks": ticks, "ms": durations}


def _run_nominal(db: Session, speed: int, ticks: int, seed: int) -> dict:
    state = live.SimState()
    live.start(db, state, run_id=0, scenario="S1", speed=speed, seed=seed, crew=None)
    first_alert = db.scalar(select(Alert.id).order_by(Alert.id.desc())) or 0
    durations = [live.tick(db, state).duration_ms / 4 for _ in range(ticks)]
    false_alerts = db.scalars(select(Alert).where(Alert.id > first_alert)).all()
    hours = ticks * live.TICK_SECONDS * speed / 3600
    return {
        "simulated_hours": round(hours, 1),
        "member_hours": round(hours * 4, 1),
        "false_alerts": [f"{a.crew_member.code} {a.rule_code}" for a in false_alerts],
        "ms": durations,
    }


def evaluate() -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="astro-eval-", ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        settings = get_settings()
        models_dir = settings.models_dir
        settings.models_dir = str(folder / "models")
        try:
            template = _template(folder)
            # Les fausses alertes ne sont comptées que sur une physiologie normale : une base sans
            # demo story, whose anomalies (e.g. AV-03 tachycardia) would otherwise linger.
            clean = _template(folder, history=False)
            trials, timings = [], []
            for code, (members, speed, ticks) in PLAN.items():
                for i, crew in enumerate(members):
                    with _fresh(template, folder, f"{code}-{crew}") as db:
                        result = _run_trial(db, code, crew, speed, ticks, seed=100 + i)
                        db.get_bind().dispose()
                    timings += result.pop("ms")
                    trials.append({"anomaly": code, "crew": crew, **result})
                    print(
                        f"  {code:15} {crew:5} → {'détectée' if result['detected'] else 'MANQUÉE'}"
                        f" {result['minutes'] or ''}"
                    )
            nominal = []
            for speed, ticks, seed in NOMINAL_RUNS:
                with _fresh(clean, folder, f"nominal-{seed}") as db:
                    run = _run_nominal(db, speed, ticks, seed)
                    db.get_bind().dispose()
                timings += run.pop("ms")
                nominal.append(run)
                print(f"  nominal ×{speed}: {len(run['false_alerts'])} fausse(s) alerte(s)")
            sizes = [f.stat().st_size for f in (folder / "models").glob("*.joblib")]
        finally:
            settings.models_dir = models_dir

    detected = [t for t in trials if t["detected"]]
    by_anomaly = {}
    for code in PLAN:
        rows = [t for t in trials if t["anomaly"] == code]
        hits = [t for t in rows if t["detected"]]
        by_anomaly[code] = {
            "trials": len(rows),
            "detected": len(hits),
            "rate": round(len(hits) / len(rows), 3),
            "median_minutes_to_alert": statistics.median([t["minutes"] for t in hits])
            if hits
            else None,
        }
    member_hours = sum(n["member_hours"] for n in nominal)
    false_alerts = sum(len(n["false_alerts"]) for n in nominal)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": "Simulateur Astro Assistant (app/sim/live.py) sur copies de la base de démo",
        "detection_rate": round(len(detected) / len(trials), 3),
        "trials": len(trials),
        "by_anomaly": by_anomaly,
        "false_alerts": false_alerts,
        "nominal_member_hours": round(member_hours, 1),
        "false_alerts_per_member_day": round(false_alerts / member_hours * 24, 3)
        if member_hours
        else None,
        "nominal_runs": nominal,
        "inference_ms_per_member": {
            "median": round(statistics.median(timings), 1),
            "p95": round(sorted(timings)[int(0.95 * (len(timings) - 1))], 1),
        },
        "model_size_kb": {
            "isolation_forest_per_member": round(statistics.median(sizes) / 1024, 1)
            if sizes
            else None,
            "rules_and_config": round(
                sum(p.stat().st_size for p in (BASE_DIR / "app" / "engine").glob("*.yaml")) / 1024,
                1,
            ),
        },
        "duration_s": round(time.perf_counter() - started, 1),
        "trial_details": trials,
    }


def main() -> None:
    report = evaluate()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Détection {report['detection_rate']:.0%} ({report['trials']} essais) · "
        f"{report['false_alerts']} fausse(s) alerte(s) "
        f"sur {report['nominal_member_hours']} h·membre · "
        f"inférence {report['inference_ms_per_member']['median']} ms/membre → {OUTPUT}"
    )


if __name__ == "__main__":
    main()
