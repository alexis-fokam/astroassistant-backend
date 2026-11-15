from typing import Dict, Any
import numpy as np


DOMAIN_WEIGHTS = {
    "cardio": 0.25,
    "radiation": 0.25,
    "musculo": 0.15,
    "behavioral": 0.20,
    "immune": 0.15,
}


def compute_domain_scores(features: Dict[str, Any], signals: Dict[str, float]) -> Dict[str, int]:
    # Cardio : FC, VFC, PA, SpO2 + composante multivariée
    cardio_raw = (
        0.35 * min(1.0, signals["z_hrv"] / 3.0)
        + 0.25 * min(1.0, signals["z_hr"] / 3.0)
        + 0.20 * min(1.0, signals["z_sbp"] / 2.5)
        + 0.20 * signals["iso_score"]
    )
    if features["spo2"] <= 90:
        cardio_raw = max(cardio_raw, 0.90)
    elif features["spo2"] <= 94:
        cardio_raw = max(cardio_raw, 0.55)

    # Radiation : débit de dose (SPE) + cumul carrière
    rad_rate_score = min(1.0, features["radiation_rate_msv_h"] / 5.0)
    rad_cumul_score = min(1.0, features["radiation_cumul_pct"] / 85.0)
    radiation_raw = max(rad_rate_score, rad_cumul_score)

    # Musculosquelettique : manque d'exercice + symptômes SANS (vision/céphalées)
    ex_deficit = max(0.0, (90.0 - features["exercise_adherence_pct"]) / 75.0)
    sans_flag = 0.65 if (features["blurred_vision"] and features["headache_intensity"] >= 5) else 0.0
    musculo_raw = max(ex_deficit, sans_flag)

    # Comportemental : dette de sommeil, VFC basse, score de stress
    sleep_penalty = min(1.0, features["sleep_debt_h"] / 6.0)
    stress_penalty = min(1.0, features["stress_score"] / 85.0)
    behavioral_raw = 0.45 * sleep_penalty + 0.35 * stress_penalty + 0.20 * min(1.0, signals["z_hrv"] / 2.5)

    # Immunitaire : température corporelle
    immune_raw = min(1.0, signals["z_temp"] / 3.0)
    if features["temp"] >= 38.5:
        immune_raw = max(immune_raw, 0.85)

    return {
        "cardio": int(np.clip(round(cardio_raw * 100), 0, 100)),
        "radiation": int(np.clip(round(radiation_raw * 100), 0, 100)),
        "musculo": int(np.clip(round(musculo_raw * 100), 0, 100)),
        "behavioral": int(np.clip(round(behavioral_raw * 100), 0, 100)),
        "immune": int(np.clip(round(immune_raw * 100), 0, 100)),
    }


def compute_global_score(domain_scores: Dict[str, int]) -> int:
    weighted = sum(domain_scores[d] * w for d, w in DOMAIN_WEIGHTS.items())
    # Influence du domaine le plus critique pour éviter la dilution
    peak_domain = max(domain_scores.values())
    combined = 0.55 * weighted + 0.45 * peak_domain
    return int(np.clip(round(combined), 0, 100))
"""Rule evaluation, domain scores, global score and explanations (spec F2.4-F2.7, §6.3)."""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.config import OPERATORS, EngineConfig, Rule
from app.engine.features import Features
from app.models.enums import AlertLevel, HealthLevel, RiskDomain

LEVEL_RANK = {HealthLevel.NOMINAL: 0, HealthLevel.WARNING: 1, HealthLevel.CRITICAL: 2}
RULE_LEVEL = {
    AlertLevel.INFO: HealthLevel.NOMINAL,
    AlertLevel.WARNING: HealthLevel.WARNING,
    AlertLevel.CRITICAL: HealthLevel.CRITICAL,
}


def level_for(score: float) -> HealthLevel:
    """0-39 NOMINAL · 40-69 WARNING · 70-100 CRITICAL (spec §6.3)."""
    if score >= 70:
        return HealthLevel.CRITICAL
    if score >= 40:
        return HealthLevel.WARNING
    return HealthLevel.NOMINAL


def _holds(condition, features: Features) -> bool:
    feature, op, threshold = condition
    value = features.get(feature)
    return value is not None and OPERATORS[op](value, threshold)


def evaluate(rules: tuple[Rule, ...], features: Features) -> list[Rule]:
    """Rules whose conditions hold, minus those suppressed by a more specific one."""
    fired = [
        r
        for r in rules
        if all(_holds(c, features) for c in r.when)
        and (not r.any or any(_holds(c, features) for c in r.any))
    ]
    codes = {r.code for r in fired}
    return [r for r in fired if not codes.intersection(r.suppressed_by)]


def confirmed(current: list[Rule], previous: list[Rule]) -> list[Rule]:
    """CRITICAL rules fire at once; WARNING rules need two consecutive evaluations."""
    before = {r.code for r in previous}
    return [r for r in current if r.level is AlertLevel.CRITICAL or r.code in before]


@dataclass
class DomainScore:
    domain: RiskDomain
    score: float
    level: HealthLevel
    factors: list[dict]
    rules: list[str]


def _baseline_of(feature: str, features: Features):
    for key in (
        f"{feature.removesuffix('_now').removesuffix('_z')}_baseline",
        f"{feature}_baseline",
    ):
        if features.get(key) is not None:
            return features[key]
    return {"hr_z": features.get("hr_baseline"), "spo2_now": features.get("spo2_baseline")}.get(
        feature
    )


def score_domains(features: Features, rules: list[Rule], cfg: EngineConfig) -> list[DomainScore]:
    results = []
    for domain, indicators in cfg.domains.items():
        parts = [(i, i.weight * i.severity(features.get(i.feature))) for i in indicators]
        raw = min(1.0, sum(p for _, p in parts)) * 100
        domain_rules = [r for r in rules if r.domain is domain]
        floor = max((cfg.rule_floor[r.level.value] for r in domain_rules), default=0)
        score = round(max(raw, floor), 1)
        total = sum(p for _, p in parts) or 1.0
        factors = [
            {
                "feature": i.feature,
                "label": i.label,
                "value": features.get(i.feature),
                "baseline": _baseline_of(i.feature, features),
                "contribution": round(p / total, 2),
            }
            for i, p in sorted(parts, key=lambda x: -x[1])
            if p > 0
        ][:3]
        level = level_for(score)
        for r in domain_rules:
            if LEVEL_RANK[RULE_LEVEL[r.level]] > LEVEL_RANK[level]:
                level = RULE_LEVEL[r.level]
        results.append(DomainScore(domain, score, level, factors, [r.code for r in domain_rules]))
    return results


def global_score(domains: list[DomainScore], cfg: EngineConfig) -> tuple[float, HealthLevel]:
    """score = blend of worst domain and weighted mean; status = max(level(score), worst rule)."""
    weighted = sum(cfg.global_weights[d.domain.value] * d.score for d in domains)
    worst = max(d.score for d in domains)
    share = cfg.worst_domain_share
    score = round(share * worst + (1 - share) * weighted, 1)
    level = level_for(score)
    for d in domains:
        if LEVEL_RANK[d.level] > LEVEL_RANK[level]:
            level = d.level
    score = max(score, cfg.status_floor.get(level.value, 0))
    return score, level
