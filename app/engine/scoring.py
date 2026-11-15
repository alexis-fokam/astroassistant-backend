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
