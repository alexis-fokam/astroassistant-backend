from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ScenarioCode(str, Enum):
    S1 = "S1"  # Journée nominale
    S2 = "S2"  # Stress & dette de sommeil
    S3 = "S3"  # Événement à particules solaires (SPE)
    S4 = "S4"  # Suspicion SANS
    S5 = "S5"  # Déconditionnement musculosquelettique
    S6 = "S6"  # Fenêtre de contact sol


class AlertLevel(str, Enum):
    NOMINAL = "NOMINAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ScenarioRequest(BaseModel):
    scenario: ScenarioCode
    crew_id: str = Field(default="AV-01", description="Identifiant de l'astronaute cible")
    seed: Optional[int] = Field(default=42, description="Graine aléatoire pour la reproductibilité")


class SpeedRequest(BaseModel):
    speed_multiplier: int = Field(..., ge=1, le=1000, description="Facteur d'accélération (x1 à x1000)")


class VitalBatch(BaseModel):
    crew_id: str
    timestamp: datetime
    hr: float = Field(..., ge=25, le=240, description="Fréquence cardiaque (bpm)")
    hrv_rmssd: float = Field(..., ge=1, le=250, description="VFC RMSSD (ms)")
    sbp: float = Field(..., ge=50, le=250, description="Pression artérielle systolique (mmHg)")
    dbp: float = Field(..., ge=30, le=150, description="Pression artérielle diastolique (mmHg)")
    spo2: float = Field(..., ge=50, le=100, description="Saturation en oxygène (%)")
    temp: float = Field(..., ge=32.0, le=43.0, description="Température corporelle (°C)")
    radiation_rate_msv_h: float = Field(default=0.0002, ge=0, description="Débit de dose (mSv/h)")
    radiation_cumul_pct: float = Field(default=12.0, ge=0, le=200, description="% de la limite de carrière")
    sleep_hours: float = Field(default=7.5, ge=0, le=24)
    sleep_debt_h: float = Field(default=0.0, ge=0)
    exercise_adherence_pct: float = Field(default=100.0, ge=0, le=100)
    stress_score: float = Field(default=20.0, ge=0, le=100)
    blurred_vision: bool = False
    headache_intensity: int = Field(default=0, ge=0, le=10)


class FactorExplanation(BaseModel):
    feature: str
    value: float | str
    baseline: Optional[float] = None
    contribution: float


class EngineEvaluationResponse(BaseModel):
    crew_id: str
    timestamp: datetime
    status: AlertLevel
    global_score: int = Field(..., ge=0, le=100)
    domains: Dict[str, int]
    top_factors: List[FactorExplanation]
    triggered_rules: List[str]
    recommended_protocol: Optional[str] = None