"""Ground link, simulation, audit and dataset payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import HealthLevel, SimRunStatus, SyncPacketKind, SyncPacketStatus
from app.schemas.common import OrmModel


class PacketOut(OrmModel):
    id: int
    crew_code: str | None
    kind: SyncPacketKind
    priority: int
    status: SyncPacketStatus
    size_bytes: int
    sha256: str
    created_at: datetime
    sent_at: datetime | None
    acknowledged_at: datetime | None
    received_at_ground: datetime | None = Field(
        description="Arrivée au sol : envoi + latence aller (délai de communication)"
    )
    in_transit: bool


class ExportRequest(BaseModel):
    crew_code: str | None = Field(default=None, description="Vide : synthèse de tout l'équipage")


class ExportOut(BaseModel):
    packet: PacketOut
    content: dict[str, Any]
    queue: list[PacketOut] = Field(description="File d'export dans l'ordre d'envoi (F10.2)")


class ImportRequest(BaseModel):
    """Instruction received from the ground (F10.4)."""

    author: str = Field(max_length=120)
    subject: str | None = Field(default=None, max_length=160)
    body: str = Field(min_length=1)
    crew_code: str | None = None
    is_instruction: bool = False
    sent_at: datetime | None = None
    sha256: str | None = Field(default=None, description="Empreinte transmise par le sol")


class GroundMessageOut(OrmModel):
    id: int
    crew_code: str | None
    author: str
    subject: str | None
    body: str
    is_instruction: bool
    sha256: str
    sent_at: datetime | None
    received_at: datetime
    read_at: datetime | None
    in_transit: bool = Field(description="Encore en route vers le vaisseau (délai)")


class InstructionIn(BaseModel):
    """Instruction written on the ground; it reaches the crew after the one-way delay."""

    crew_code: str | None = Field(default=None, description="Vide : tout l'équipage")
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    author: str = Field(default="Dr M. Reyes · Houston", max_length=120)


class MissionPatch(BaseModel):
    """Mission profile (ISS, Moon, Mars): sets the communication delay."""

    destination: Literal["low_earth_orbit", "moon", "mars_transit", "mars_surface"]


class ContactWindowOut(OrmModel):
    starts_at: datetime
    ends_at: datetime
    one_way_latency_s: int
    bandwidth_kbps: float | None


class ScenarioOut(OrmModel):
    code: str
    name: str
    description: str | None
    expected_level: HealthLevel | None
    expected_protocol_code: str | None
    duration_seconds: int
    parameters: dict[str, Any]


class ScenarioStart(BaseModel):
    code: str = Field(examples=["S3"])
    crew_code: str | None = None
    speed_factor: float = Field(default=60, ge=1, le=1000)
    seed: int = 42


class InjectIn(BaseModel):
    """Inject an anomaly live (jury demo): the AI must detect it within seconds."""

    anomaly: Literal[
        "tachycardia", "desaturation", "fever", "hrv_drop", "radiation", "sans", "deconditioning"
    ]
    crew_code: str = Field(default="AV-03", description="Code d'un membre, ou « all »")


class SpeedIn(BaseModel):
    run_id: int
    speed_factor: float = Field(ge=1, le=1000)


class SimRunOut(OrmModel):
    id: int
    scenario_code: str
    crew_code: str | None
    status: SimRunStatus
    seed: int
    speed_factor: float
    started_at: datetime
    ended_at: datetime | None


class AuditOut(OrmModel):
    id: int
    at: datetime
    actor_label: str
    action: str
    entity_type: str | None
    entity_id: int | None
    details: dict[str, Any]
    entry_hash: str


class AuditVerifyOut(BaseModel):
    valid: bool
    entries: int
    broken_at: int | None


class DatasetOut(OrmModel):
    code: str
    name: str
    agency: str
    url: str
    licence: str
    usage: str
    bundled: bool
    retrieved_at: datetime | None
    record_count: int
