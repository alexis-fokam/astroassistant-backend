"""Données de démonstration : équipage, pharmacie, protocoles, scénarios S1 à S6.

Usage :
    python -m app.seed           # remplit une base vide (ne fait rien si l'équipage existe)
    python -m app.seed --reset   # supprime toutes les tables, les recrée puis remplit

Seules des données de référence sont créées ; la télémétrie est produite par le
simulateur (F15). Les PIN de démo sont dans ``DEMO_PINS``.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.security import hash_pin
from app.models import (
    AuditLog,
    Base,
    Baseline,
    ContactWindow,
    CrewMember,
    Device,
    GroundMessage,
    InventoryItem,
    Protocol,
    ProtocolRequirement,
    SimScenario,
)
from app.models.audit import GENESIS_HASH
from app.models.enums import (
    AccessRole,
    AlertLevel,
    CrewRole,
    DeviceKind,
    HealthLevel,
    Metric,
    RiskDomain,
    Sex,
)

PROTOCOLS_DIR = BASE_DIR / "app" / "protocols"
MISSION_START = date(2026, 5, 24)

# Profils fictifs. PIN de démonstration uniquement.
DEMO_PINS = {"AV-01": "1111", "AV-02": "2222", "AV-03": "3333", "AV-04": "4444"}

CREW = [
    {
        "code": "AV-01",
        "first_name": "Nadia",
        "last_name": "Okafor",
        "crew_role": CrewRole.COMMANDER,
        "sex": Sex.FEMALE,
        "birth_date": date(1984, 3, 12),
        "height_cm": 168,
        "mass_kg": 61,
        "prior_career_dose_msv": 98,
    },
    {
        "code": "AV-02",
        "first_name": "Léo",
        "last_name": "Martin",
        "crew_role": CrewRole.FLIGHT_ENGINEER,
        "sex": Sex.MALE,
        "birth_date": date(1989, 7, 2),
        "height_cm": 181,
        "mass_kg": 77,
        "prior_career_dose_msv": 100,
    },
    {
        "code": "AV-03",
        "first_name": "Sara",
        "last_name": "Lindqvist",
        "crew_role": CrewRole.MISSION_SPECIALIST,
        "sex": Sex.FEMALE,
        "birth_date": date(1991, 11, 23),
        "height_cm": 172,
        "mass_kg": 64,
        "prior_career_dose_msv": 41,
    },
    {
        "code": "AV-04",
        "first_name": "Kenji",
        "last_name": "Arai",
        "crew_role": CrewRole.MISSION_SPECIALIST,
        "access_role": AccessRole.CMO,
        "sex": Sex.MALE,
        "birth_date": date(1982, 5, 30),
        "height_cm": 175,
        "mass_kg": 72,
        "prior_career_dose_msv": 57,
    },
]

# Baselines de repos (moyenne, écart-type) ; légère variation par membre.
BASELINES: dict[Metric, tuple[float, float]] = {
    Metric.HEART_RATE: (64, 6),
    Metric.HRV_RMSSD: (48, 6),
    Metric.SYSTOLIC_BP: (117, 7),
    Metric.DIASTOLIC_BP: (75, 5),
    Metric.SPO2: (97.8, 0.6),
    Metric.CORE_TEMPERATURE: (36.8, 0.2),
    Metric.RESPIRATORY_RATE: (14, 1.5),
}
BASELINE_OFFSETS = {"AV-01": -0.04, "AV-02": 0.0, "AV-03": 0.05, "AV-04": 0.02}

INVENTORY = [
    # code, nom, catégorie, unité, quantité, seuil, péremption, emplacement
    (
        "MED-PARA-500",
        "Paracétamol 500 mg",
        "médicament",
        "cp",
        46,
        20,
        date(2027, 8, 31),
        "Module B · tiroir 1",
    ),
    (
        "MED-PROM-25",
        "Prométhazine 25 mg",
        "médicament",
        "cp",
        6,
        10,
        date(2027, 2, 28),
        "Module B · tiroir 1",
    ),
    (
        "MED-MELA-3",
        "Mélatonine 3 mg",
        "médicament",
        "cp",
        22,
        10,
        date(2027, 10, 31),
        "Module B · tiroir 1",
    ),
    (
        "MED-ADRE-SYR",
        "Seringue d'adrénaline",
        "médicament",
        "unité",
        3,
        2,
        date(2027, 5, 31),
        "Kit urgence",
    ),
    (
        "MED-COLLY-LUB",
        "Collyre lubrifiant",
        "médicament",
        "flacon",
        4,
        3,
        date(2026, 11, 30),
        "Module B · tiroir 2",
    ),
    ("EQ-O2-PORT", "Oxygène portable", "matériel", "bouteille", 2, 1, None, "Module A · mur"),
    ("EQ-OXIMETER", "Oxymètre de pouls", "matériel", "unité", 2, 1, None, "Kit urgence"),
    ("EQ-BP-CUFF", "Tensiomètre à brassard", "matériel", "unité", 2, 1, None, "Kit urgence"),
    ("EQ-AMSLER", "Grille d'Amsler", "matériel", "unité", 2, 1, None, "Module B · tiroir 2"),
    (
        "EQ-ACUITY",
        "Échelle d'acuité visuelle",
        "matériel",
        "unité",
        1,
        1,
        None,
        "Module B · tiroir 2",
    ),
    ("EQ-OCT", "OCT portable", "matériel", "unité", 1, 1, None, "Module B · baie médicale"),
    ("EQ-DOSI-ACT", "Dosimètre personnel actif", "matériel", "unité", 6, 4, None, "Abri blindé B2"),
    (
        "CONS-BANDAGE",
        "Bande élastique",
        "consommable",
        "rouleau",
        0,
        2,
        None,
        "Module B · tiroir 3",
    ),
]

SCENARIOS = [
    {
        "code": "S1",
        "name": "Journée nominale",
        "description": "Paramètres stables, statut vert, rappels d'exercice et de check-in.",
        "expected_level": HealthLevel.NOMINAL,
        "duration_seconds": 86_400,
        "parameters": {"crew": "all"},
    },
    {
        "code": "S2",
        "name": "Stress et dette de sommeil",
        "description": "VFC en baisse sur 3 jours et sommeil < 6 h : WARNING.",
        "expected_level": HealthLevel.WARNING,
        "expected_protocol_code": "PRT-STRESS-01",
        "duration_seconds": 259_200,
        "parameters": {"crew": "AV-02", "hrv_drop_pct": 35, "sleep_hours": 5.5, "stress": 7},
    },
    {
        "code": "S3",
        "name": "Événement à particules solaires",
        "description": "Pic de débit de dose : CRITICAL, consigne d'abri et minuteur.",
        "expected_level": HealthLevel.CRITICAL,
        "expected_protocol_code": "PRT-RAD-02",
        "duration_seconds": 14_400,
        "parameters": {
            "crew": "all",
            "peak_dose_rate_msv_h": 1.82,
            "flare_class": "X8.2",
            "donki_replay": "2017-09-10",
            "shelter_countdown_s": 600,
        },
    },
    {
        "code": "S4",
        "name": "Suspicion SANS",
        "description": "Vision floue déclarée et maux de tête répétés : WARNING, test visuel.",
        "expected_level": HealthLevel.WARNING,
        "expected_protocol_code": "PRT-SANS-01",
        "duration_seconds": 172_800,
        "parameters": {"crew": "AV-04", "vision_change": 2, "headache": 2, "days": 2},
    },
    {
        "code": "S5",
        "name": "Déconditionnement",
        "description": "Séances d'exercice manquées : projection de perte osseuse aggravée.",
        "expected_level": HealthLevel.WARNING,
        "expected_protocol_code": "PRT-EX-03",
        "duration_seconds": 432_000,
        "parameters": {"crew": "AV-01", "missed_sessions": 3, "kind": "resistance"},
    },
    {
        "code": "S6",
        "name": "Fenêtre de contact",
        "description": "Paquet de synthèse transmis au sol, puis réception d'une consigne.",
        "duration_seconds": 2_700,
        "parameters": {"one_way_latency_s": 720, "bandwidth_kbps": 256},
    },
]


def load_protocol_files(directory: Path = PROTOCOLS_DIR) -> list[tuple[Path, dict, str]]:
    """Lit chaque YAML de la bibliothèque : (chemin, contenu, SHA-256 du fichier)."""
    files = []
    for path in sorted(directory.glob("*.yaml")):
        raw = path.read_bytes()
        files.append((path, yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()))
    return files


def seed(session: Session, now: datetime | None = None) -> bool:
    """Remplit une base vide. Renvoie False sans rien faire si l'équipage existe déjà."""
    if session.scalar(select(func.count()).select_from(CrewMember)):
        return False
    now = now or datetime.now(UTC)

    crew: dict[str, CrewMember] = {}
    for spec in CREW:
        member = CrewMember(
            **spec, pin_hash=hash_pin(DEMO_PINS[spec["code"]]), mission_start_date=MISSION_START
        )
        crew[member.code] = member
        session.add(member)
        session.add(
            Device(
                crew_member=member,
                kind=DeviceKind.WEARABLE,
                serial_number=f"WR-{member.code}",
                firmware_version="2.4.1",
            )
        )
        offset = BASELINE_OFFSETS[member.code]
        for metric, (mean, std) in BASELINES.items():
            value = round(mean * (1 + offset), 2) if metric is not Metric.SPO2 else mean
            session.add(
                Baseline(
                    crew_member=member,
                    metric=metric,
                    mean=value,
                    std=std,
                    median=value,
                    mad=round(std * 0.6745, 3),
                    sample_count=1240,
                )
            )
    session.add(
        Device(kind=DeviceKind.CABIN_SENSOR, serial_number="CAB-CO2-01", firmware_version="1.0")
    )

    items: dict[str, InventoryItem] = {}
    for code, name, category, unit, qty, minimum, expires, location in INVENTORY:
        items[code] = InventoryItem(
            code=code,
            name=name,
            category=category,
            unit=unit,
            quantity=qty,
            min_quantity=minimum,
            expires_on=expires,
            location=location,
        )
        session.add(items[code])

    for path, spec, checksum in load_protocol_files():
        protocol = Protocol(
            code=spec["code"],
            version=str(spec["version"]),
            title=spec["title"],
            description=spec.get("description"),
            domain=RiskDomain(spec["domain"]) if spec.get("domain") else None,
            severity=AlertLevel(spec["severity"]),
            expected_duration_min=spec.get("expected_duration_min"),
            file_path=path.relative_to(BASE_DIR).as_posix(),
            checksum=checksum,
        )
        for req in spec.get("requirements", []):
            protocol.requirements.append(
                ProtocolRequirement(
                    item=items[req["item"]],
                    quantity=req.get("quantity", 1),
                    is_optional=req.get("optional", False),
                )
            )
        session.add(protocol)

    for spec in SCENARIOS:
        session.add(SimScenario(**spec))

    # Fenêtres de contact sur 3 jours, toutes les 12 h, latence vers Mars ~12 min (F10.3).
    first = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    for i in range(6):
        start = first + timedelta(hours=12 * i)
        session.add(
            ContactWindow(
                starts_at=start,
                ends_at=start + timedelta(minutes=45),
                one_way_latency_s=720,
                bandwidth_kbps=256,
            )
        )

    body = (
        "Prolonger la fenêtre de sommeil de 45 min pendant 3 nuits. Réévaluer la VFC dans 3 jours."
    )
    session.flush()
    session.add(
        GroundMessage(
            crew_member_id=crew["AV-02"].id,
            author="Dr M. Reyes · Houston",
            subject="Consigne sommeil",
            body=body,
            sha256=hashlib.sha256(body.encode()).hexdigest(),
            sent_at=now - timedelta(hours=21),
            received_at=now - timedelta(hours=21) + timedelta(seconds=720),
        )
    )

    session.flush()
    entry = {
        "at": now,
        "actor_label": "Système",
        "action": "seed.load",
        "entity_type": None,
        "entity_id": None,
        "details": {"crew": len(crew), "items": len(items), "scenarios": len(SCENARIOS)},
    }
    session.add(
        AuditLog(
            prev_hash=GENESIS_HASH,
            entry_hash=AuditLog.compute_hash(GENESIS_HASH, **entry),
            **entry,
        )
    )
    session.commit()
    return True


def reset(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def main() -> None:
    from app.core.database import SessionLocal, engine

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="recrée toutes les tables")
    args = parser.parse_args()

    if args.reset:
        reset(engine)
    else:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        created = seed(session)
    print("Données de démo chargées." if created else "Équipage déjà présent : rien à faire.")


if __name__ == "__main__":
    main()
