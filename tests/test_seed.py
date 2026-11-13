import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.security import hash_pin, verify_pin
from app.models import (
    AuditLog,
    Baseline,
    ContactWindow,
    CrewMember,
    InventoryItem,
    Protocol,
    SimScenario,
)
from app.models.enums import AccessRole
from app.seed import BASELINES, CREW, DEMO_PINS, INVENTORY, SCENARIOS, load_protocol_files, seed


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_seed_loads_reference_data(db: Session) -> None:
    assert seed(db) is True

    assert _count(db, CrewMember) == len(CREW)
    assert _count(db, Baseline) == len(CREW) * len(BASELINES)
    assert _count(db, InventoryItem) == len(INVENTORY)
    assert _count(db, SimScenario) == len(SCENARIOS) == 6
    assert _count(db, ContactWindow) == 6
    assert db.scalars(select(AuditLog.action)).one() == "seed.load"

    cmo = db.scalars(select(CrewMember).where(CrewMember.access_role == AccessRole.CMO)).one()
    assert cmo.code == "AV-04"
    assert verify_pin(DEMO_PINS["AV-04"], cmo.pin_hash)
    assert not verify_pin("0000", cmo.pin_hash)


def test_seed_is_idempotent(db: Session) -> None:
    assert seed(db) is True
    assert seed(db) is False
    assert _count(db, CrewMember) == len(CREW)


def test_scenarios_reference_existing_protocols(db: Session) -> None:
    seed(db)
    protocol_codes = set(db.scalars(select(Protocol.code)))
    expected = {s.expected_protocol_code for s in db.scalars(select(SimScenario))} - {None}
    assert expected <= protocol_codes


def test_protocols_match_their_yaml_files(db: Session) -> None:
    seed(db)
    files = load_protocol_files()
    assert _count(db, Protocol) == len(files) == 5
    for protocol in db.scalars(select(Protocol)):
        raw = (BASE_DIR / protocol.file_path).read_bytes()
        assert protocol.checksum == hashlib.sha256(raw).hexdigest()

    emergency = db.scalars(select(Protocol).where(Protocol.code == "EMRG-01")).one()
    required = {r.item.code for r in emergency.requirements if not r.is_optional}
    assert required == {"EQ-OXIMETER", "EQ-BP-CUFF", "EQ-O2-PORT"}


def test_inventory_has_low_stock_items_for_the_demo(db: Session) -> None:
    seed(db)
    low = {i.code for i in db.scalars(select(InventoryItem)) if i.is_low_stock}
    assert {"MED-PROM-25", "CONS-BANDAGE"} <= low


def test_pin_hash_is_salted() -> None:
    first, second = hash_pin("1234"), hash_pin("1234")
    assert first != second
    assert verify_pin("1234", first) and verify_pin("1234", second)
    assert not verify_pin("1234", "not-a-hash")
