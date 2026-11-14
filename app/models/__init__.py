"""SQLAlchemy models of Astro Assistant (spec §9).

Every model is imported here so it is registered in ``Base.metadata`` before
``Base.metadata.create_all`` (see ``app.main``).
"""

from app.models.alerts import Alert, EmergencyEvent
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.crew import Baseline, CrewMember, Device
from app.models.datasets import CruiseDoseSample, DatasetSource, ProtonFluxReading
from app.models.medical import ConsultationNote, InventoryItem, InventoryUsage
from app.models.mission import Mission
from app.models.protocols import Protocol, ProtocolRequirement, ProtocolRun
from app.models.radiation import RadiationDose, SpaceWeatherEvent
from app.models.scoring import FeatureSnapshot, RiskScore
from app.models.simulation import SimRun, SimScenario
from app.models.sync import ContactWindow, GroundMessage, SyncPacket
from app.models.vitals import Checkin, VitalReading
from app.models.wellness import ExerciseSession, IntakeLog, PvtResult, SleepSession

__all__ = [
    "Alert",
    "AuditLog",
    "Base",
    "Baseline",
    "Checkin",
    "ConsultationNote",
    "ContactWindow",
    "CrewMember",
    "CruiseDoseSample",
    "DatasetSource",
    "Device",
    "EmergencyEvent",
    "ExerciseSession",
    "FeatureSnapshot",
    "GroundMessage",
    "IntakeLog",
    "InventoryItem",
    "InventoryUsage",
    "Mission",
    "Protocol",
    "ProtocolRequirement",
    "ProtocolRun",
    "ProtonFluxReading",
    "PvtResult",
    "RadiationDose",
    "RiskScore",
    "SimRun",
    "SimScenario",
    "SleepSession",
    "SpaceWeatherEvent",
    "SyncPacket",
    "VitalReading",
]
