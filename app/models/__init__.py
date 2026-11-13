"""Modèles SQLAlchemy d'AstroVitals (cahier des charges §9).

Tous les modèles sont importés ici pour être enregistrés dans ``Base.metadata``
avant ``Base.metadata.create_all`` (voir ``app.main``).
"""

from app.models.alerts import Alert, EmergencyEvent
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.crew import Baseline, CrewMember, Device
from app.models.medical import ConsultationNote, InventoryItem, InventoryUsage
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
    "Device",
    "EmergencyEvent",
    "ExerciseSession",
    "FeatureSnapshot",
    "GroundMessage",
    "IntakeLog",
    "InventoryItem",
    "InventoryUsage",
    "Protocol",
    "ProtocolRequirement",
    "ProtocolRun",
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
