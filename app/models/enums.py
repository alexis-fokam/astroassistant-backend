"""Énumérations métier partagées par les modèles, les schémas et le moteur."""

from enum import StrEnum


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class CrewRole(StrEnum):
    """Function on board (profile information)."""

    COMMANDER = "commander"
    PILOT = "pilot"
    FLIGHT_ENGINEER = "flight_engineer"
    MISSION_SPECIALIST = "mission_specialist"
    PAYLOAD_SPECIALIST = "payload_specialist"


class AccessRole(StrEnum):
    """Droits des profils locaux (§7, RBAC) : un astronaute ne voit que ses propres données."""

    ASTRONAUT = "astronaut"
    CMO = "cmo"  # Médecin de bord (CMO) : accès à tout l'équipage


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
    """Séries physiologiques. L'unité est fixée par la mesure (voir METRIC_UNITS).

    La dose de radiation a sa propre table (``radiation_doses``), valeurs cumulées comprises.
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
    DATASET = "dataset"  # importée d'un jeu de données ouvert (voir dataset_sources)


class HealthLevel(StrEnum):
    """Three-level status (F1.1); score thresholds 0-39 | 40-69 | 70-100 (spec §6.3)."""

    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskDomain(StrEnum):
    """Domaines de risque notés par le moteur (F2.5) ; GLOBAL est l'agrégat (F2.6)."""

    GLOBAL = "global"
    CARDIO = "cardio"
    RADIATION = "radiation"
    MUSCULOSKELETAL = "musculoskeletal"
    BEHAVIORAL = "behavioral"
    IMMUNE = "immune"


class DetectionMethod(StrEnum):
    """Origine d'une alerte (F2.2-F2.4), affichée dans l'explication (F2.7)."""

    THRESHOLD = "threshold"  # clinical threshold
    ROBUST_ZSCORE = "robust_zscore"  # median / MAD vs baseline
    ISOLATION_FOREST = "isolation_forest"  # multivariate
    TREND = "trend"  # slope over a sliding window
    CHECKIN = "checkin"  # réponses du check-in (F3.4)
    MANUAL = "manual"  # signalée par le CMO


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


class MissionDestination(StrEnum):
    """Profil de mission choisi à la configuration (A-03) : latence et cycle jour/nuit."""

    LOW_EARTH_ORBIT = "low_earth_orbit"
    MOON = "moon"
    MARS_TRANSIT = "mars_transit"
    MARS_SURFACE = "mars_surface"


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
