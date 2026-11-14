"""Business enumerations shared by models, schemas and the engine."""

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
    """Local profile rights (spec §7, RBAC): an astronaut only sees their own data."""

    ASTRONAUT = "astronaut"
    CMO = "cmo"  # Crew Medical Officer: access to the whole crew


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
    """Physiological time series. The unit is fixed by the metric (see METRIC_UNITS).

    Radiation dose has its own table (``radiation_doses``), cumulative values included.
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
    DATASET = "dataset"  # imported from an open dataset (see dataset_sources)


class HealthLevel(StrEnum):
    """Three-level status (F1.1); score thresholds 0-39 | 40-69 | 70-100 (spec §6.3)."""

    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"


class RiskDomain(StrEnum):
    """Risk domains scored by the engine (F2.5); GLOBAL is the aggregate (F2.6)."""

    GLOBAL = "global"
    CARDIO = "cardio"
    RADIATION = "radiation"
    MUSCULOSKELETAL = "musculoskeletal"
    BEHAVIORAL = "behavioral"
    IMMUNE = "immune"


class DetectionMethod(StrEnum):
    """Origin of an alert (F2.2-F2.4), shown in the explanation (F2.7)."""

    THRESHOLD = "threshold"  # clinical threshold
    ROBUST_ZSCORE = "robust_zscore"  # median / MAD vs baseline
    ISOLATION_FOREST = "isolation_forest"  # multivariate
    TREND = "trend"  # slope over a sliding window
    CHECKIN = "checkin"  # check-in answers (F3.4)
    MANUAL = "manual"  # reported by the CMO


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
    """Mission profile chosen at setup (A-03); drives latency and day/night cycle."""

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
