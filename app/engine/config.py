"""Engine configuration and clinical rules, loaded from the YAML files next to this module."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.models.enums import AlertLevel, DetectionMethod, Metric, RiskDomain

ENGINE_DIR = Path(__file__).resolve().parent
OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}

Condition = tuple[str, str, float]


@dataclass(frozen=True)
class Rule:
    code: str
    domain: RiskDomain
    level: AlertLevel
    method: DetectionMethod
    title: str
    message: str
    when: tuple[Condition, ...]
    any: tuple[Condition, ...] = ()
    suppressed_by: tuple[str, ...] = ()
    domain_label: str | None = None
    metric: Metric | None = None
    observed: str | None = None
    threshold: float | None = None
    threshold_feature: str | None = None
    protocol: str | None = None

    def features(self) -> set[str]:
        return {c[0] for c in (*self.when, *self.any)}


@dataclass(frozen=True)
class Indicator:
    feature: str
    low: float
    high: float
    weight: float
    label: str

    def severity(self, value: float | None) -> float:
        """0 (normal) → 1 (severe); works for "higher is worse" and "lower is worse"."""
        if value is None:
            return 0.0
        span = self.high - self.low
        return min(max((value - self.low) / span, 0.0), 1.0) if span else 0.0


@dataclass(frozen=True)
class EngineConfig:
    model_version: str
    plausible: dict[str, tuple[float, float]]
    min_quality: float
    windows: dict[str, int]
    storm_rate_msv_h: float
    anomaly: dict[str, Any]
    global_weights: dict[str, float]
    worst_domain_share: float
    rule_floor: dict[str, float]
    domains: dict[RiskDomain, tuple[Indicator, ...]]
    rules: tuple[Rule, ...] = field(default=())


def _condition(raw: list) -> Condition:
    feature, op, value = raw
    if op not in OPERATORS:
        raise ValueError(f"Unknown operator {op!r}")
    return feature, op, float(value)


def _rule(raw: dict[str, Any]) -> Rule:
    return Rule(
        code=raw["code"],
        domain=RiskDomain(raw["domain"]),
        level=AlertLevel(raw["level"]),
        method=DetectionMethod(raw["method"]),
        title=raw["title"],
        message=raw["message"],
        when=tuple(_condition(c) for c in raw.get("when", [])),
        any=tuple(_condition(c) for c in raw.get("any", [])),
        suppressed_by=tuple(raw.get("suppressed_by", [])),
        domain_label=raw.get("domain_label"),
        metric=Metric(raw["metric"]) if raw.get("metric") else None,
        observed=raw.get("observed"),
        threshold=raw.get("threshold"),
        threshold_feature=raw.get("threshold_feature"),
        protocol=raw.get("protocol"),
    )


@lru_cache
def load_config() -> EngineConfig:
    raw = yaml.safe_load((ENGINE_DIR / "config.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ENGINE_DIR / "rules.yaml").read_text(encoding="utf-8"))
    return EngineConfig(
        model_version=raw["model_version"],
        plausible={k: tuple(v) for k, v in raw["plausible"].items()},
        min_quality=raw["min_quality"],
        windows=raw["windows"],
        storm_rate_msv_h=raw["radiation"]["storm_rate_msv_h"],
        anomaly=raw["anomaly"],
        global_weights=raw["global"]["weights"],
        worst_domain_share=raw["global"]["worst_domain_share"],
        rule_floor=raw["rule_floor"],
        domains={
            RiskDomain(name): tuple(Indicator(**i) for i in items)
            for name, items in raw["domains"].items()
        },
        rules=tuple(_rule(r) for r in rules),
    )
