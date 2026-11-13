"""Énumérations métier partagées par les modèles, les schémas et le moteur."""

from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class CrewRole(StrEnum):
    """Fonction à bord (information de profil)."""

    COMMANDER = "commander"
    PILOT = "pilot"
    FLIGHT_ENGINEER = "flight_engineer"
    MISSION_SPECIALIST = "mission_specialist"
    PAYLOAD_SPECIALIST = "payload_specialist"


class AccessRole(StrEnum):
    """Droits du profil local (§7, RBAC) : l'astronaute ne voit que ses données."""

    ASTRONAUT = "astronaut"
    CMO = "cmo"  # Crew Medical Officer : toutes les données de l'équipage


class DeviceKind(StrEnum):
    WEARABLE = "wearable"
    ECG_PATCH = "ecg_patch"
    PULSE_OXIMETER = "pulse_oximeter"
    THERMOMETER = "thermometer"
    BP_MONITOR = "bp_monitor"
    DOSIMETER = "dosimeter"
    CABIN_SENSOR = "cabin_sensor"
    SIMULATOR = "simulator"


class Metric(StrEnum):
    """Mesures physiologiques en série temporelle. L'unité est fixée par la métrique.

    La dose de rayonnement a sa propre table (``radiation_doses``), cumuls compris.
    """

    HEART_RATE = "heart_rate"
    HRV_RMSSD = "hrv_rmssd"
    SPO2 = "spo2"
    RESPIRATORY_RATE = "respiratory_rate"
    SKIN_TEMPERATURE = "skin_temperature"
    CORE_TEMPERATURE = "core_temperature"
    SYSTOLIC_BP = "systolic_bp"
    DIASTOLIC_BP = "diastolic_bp"
    ACTIVITY_LEVEL = "activity_level"
    CABIN_CO2 = "cabin_co2"


METRIC_UNITS: dict[Metric, str] = {
    Metric.HEART_RATE: "bpm",
    Metric.HRV_RMSSD: "ms",
    Metric.SPO2: "%",
    Metric.RESPIRATORY_RATE: "rpm",
    Metric.SKIN_TEMPERATURE: "°C",
    Metric.CORE_TEMPERATURE: "°C",
    Metric.SYSTOLIC_BP: "mmHg",
    Metric.DIASTOLIC_BP: "mmHg",
    Metric.ACTIVITY_LEVEL: "MET",
    Metric.CABIN_CO2: "%",
}


class DataSource(StrEnum):
    SENSOR = "sensor"
    SIMULATOR = "simulator"
    MANUAL = "manual"


class HealthLevel(StrEnum):
    """Statut à 3 niveaux (F1.1) — seuils de score : 0-39 | 40-69 | 70-100 (§6.3)."""

    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskDomain(StrEnum):
    """Domaines de risque scorés par le moteur (F2.5) ; GLOBAL = agrégation (F2.6)."""

    GLOBAL = "global"
    CARDIO = "cardio"
    RADIATION = "radiation"
    MUSCULOSKELETAL = "musculoskeletal"
    BEHAVIORAL = "behavioral"
    IMMUNE = "immune"


class DetectionMethod(StrEnum):
    """Origine d'une alerte (F2.2 à F2.4), affichée dans l'explication (F2.7)."""

    THRESHOLD = "threshold"  # seuil clinique
    ROBUST_ZSCORE = "robust_zscore"  # médiane / MAD vs baseline
    ISOLATION_FOREST = "isolation_forest"  # multivarié
    TREND = "trend"  # pente sur fenêtre glissante
    CHECKIN = "checkin"  # réponses du check-in (F3.4)
    MANUAL = "manual"  # signalement par le CMO


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ProtocolRunStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"


class EmergencyStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class SpaceWeatherKind(StrEnum):
    SOLAR_FLARE = "solar_flare"
    SOLAR_PARTICLE_EVENT = "solar_particle_event"  # SPE
    CME = "cme"
    GCR_PEAK = "gcr_peak"


class ExerciseKind(StrEnum):
    RESISTANCE = "resistance"  # ARED
    TREADMILL = "treadmill"  # T2
    CYCLE = "cycle"  # CEVIS
    OTHER = "other"


class ExerciseIntensity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    INTERVAL = "interval"


class SessionStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    MISSED = "missed"


class IntakeKind(StrEnum):
    MEAL = "meal"
    SNACK = "snack"
    WATER = "water"


class SyncPacketKind(StrEnum):
    DAILY_SUMMARY = "daily_summary"
    ALERT = "alert"
    EMERGENCY = "emergency"
    EVENT = "event"
    REPORT = "report"
    TIMESERIES = "timeseries"


class SyncPacketStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"


class SimRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"
