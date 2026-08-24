"""
HCT-302: Finite rule engine V1 — expiry, low stock, duplicates, allergies, interactions.

Each rule is a pure function: facts → list of alerts. Alerts carry source event IDs.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    rule_id: str
    level: str  # SEVERE | WARNING | INFO | TIP (HCT-303)
    message: str
    source_event_ids: list[str] = field(default_factory=list)


RuleFunc = Callable[[dict[str, Any]], list[Alert]]

_registry: dict[str, RuleFunc] = {}


def _drug_ingredients(drug: dict[str, Any]) -> list[str]:
    raw = drug.get("active_ingredients")
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
        if values:
            return values
    ingredient = drug.get("ingredient")
    return [str(ingredient).strip().lower()] if ingredient else []


def register_rule(rule_id: str) -> Callable[[RuleFunc], RuleFunc]:
    def decorator(fn: RuleFunc) -> RuleFunc:
        _registry[rule_id] = fn
        return fn
    return decorator


# ── Rules ──────────────────────────────────────────────────────────


@register_rule("expiry_check")
def expiry_check(facts: dict[str, Any]) -> list[Alert]:
    drugs = facts.get("drugs", [])
    alerts: list[Alert] = []
    now = datetime.now(UTC).date()
    for drug in drugs:
        expiry_str = drug.get("expiry_date")
        if not expiry_str:
            continue
        try:
            expiry = datetime.fromisoformat(expiry_str).date()
        except (ValueError, TypeError):
            continue
        days_left = (expiry - now).days
        if days_left < 0:
            alerts.append(Alert("expiry_check", "SEVERE",
                f"药品 {drug.get('name')} 已过期", [drug.get("added_by", "")]))
        elif days_left <= 30:
            alerts.append(Alert("expiry_check", "WARNING",
                f"药品 {drug.get('name')} 将在 {days_left} 天后过期", [drug.get("added_by", "")]))
    return alerts


@register_rule("low_stock")
def low_stock(facts: dict[str, Any]) -> list[Alert]:
    drugs = facts.get("drugs", [])
    alerts: list[Alert] = []
    for drug in drugs:
        stock = drug.get("stock")
        if isinstance(stock, (int, float)) and stock <= 5:
            alerts.append(Alert("low_stock", "WARNING",
                f"药品 {drug.get('name')} 库存不足（剩余 {stock}）", [drug.get("added_by", "")]))
    return alerts


@register_rule("duplicate_ingredient")
def duplicate_ingredient(facts: dict[str, Any]) -> list[Alert]:
    drugs = facts.get("drugs", [])
    ingredient_map: dict[str, list[str]] = {}
    for drug in drugs:
        for ingredient in _drug_ingredients(drug):
            ingredient_map.setdefault(ingredient, []).append(drug.get("added_by", ""))
    alerts: list[Alert] = []
    for ingredient, sources in ingredient_map.items():
        if len(sources) > 1:
            alerts.append(Alert("duplicate_ingredient", "WARNING",
                f"重复成分 {ingredient} 出现在多个药品中", sources))
    return alerts


@register_rule("allergy_conflict")
def allergy_conflict(facts: dict[str, Any]) -> list[Alert]:
    allergies = {a.get("name", "").lower() for a in facts.get("allergies", [])}
    drugs = facts.get("drugs", [])
    alerts: list[Alert] = []
    for drug in drugs:
        drug_name = str(drug.get("name", "")).lower()
        drug_ingredients = str(drug.get("ingredient", "")).lower()
        for allergy in allergies:
            if allergy and (allergy in drug_name or allergy in drug_ingredients):
                alerts.append(Alert("allergy_conflict", "SEVERE",
                    f"药品 {drug.get('name')} 与过敏 {allergy} 冲突",
                    [drug.get("added_by", "")]))
    return alerts


@register_rule("interaction")
def interaction(facts: dict[str, Any]) -> list[Alert]:
    """Report only pair rules explicitly present in approved local metadata."""
    drugs = facts.get("drugs", [])
    alerts: list[Alert] = []
    for i, d1 in enumerate(drugs):
        for d2 in drugs[i + 1:]:
            left_id = d1.get("candidate_id")
            right_id = d2.get("candidate_id")
            if not left_id or not right_id:
                continue
            warnings = [
                warning
                for warning in d1.get("interaction_warnings", [])
                if isinstance(warning, dict) and warning.get("with_record_id") == right_id
            ]
            warnings.extend(
                warning
                for warning in d2.get("interaction_warnings", [])
                if isinstance(warning, dict) and warning.get("with_record_id") == left_id
            )
            if not warnings:
                continue
            warning = warnings[0]
            level = str(warning.get("level") or "WARNING")
            if level not in {"INFO", "WARNING"}:
                level = "WARNING"
            alerts.append(Alert(
                "interaction",
                level,
                str(warning.get("message") or "本地主数据要求核对这两种药品的相互作用信息"),
                [d1.get("added_by", ""), d2.get("added_by", "")],
            ))
    return alerts


# ── Engine ─────────────────────────────────────────────────────────


def run_rules(facts: dict[str, Any], rule_ids: list[str] | None = None) -> list[Alert]:
    """Run registered rules against *facts* and return all alerts."""
    ids = rule_ids if rule_ids is not None else list(_registry.keys())
    all_alerts: list[Alert] = []
    for rid in ids:
        rule_fn = _registry.get(rid)
        if rule_fn is None:
            continue
        try:
            rule_alerts = rule_fn(facts)
            all_alerts.extend(rule_alerts)
        except Exception:
            logger.exception("RULE_FAILED rule=%s", rid)
    return all_alerts


# ── HCT-303: Alert dedup & daily budget ────────────────────────────

DEFAULT_DAILY_BUDGET = 10  # max non-SEVERE alerts per member per day
SEVERE_LEVELS = frozenset({"SEVERE"})
WARNING_LEVELS = frozenset({"SEVERE", "WARNING"})


def dedup_alerts(alerts: list[Alert]) -> list[Alert]:
    """Merge alerts with the same rule_id and source event set."""
    seen: dict[tuple[str, ...], Alert] = {}
    for a in alerts:
        key = (a.rule_id, *sorted(a.source_event_ids))
        if key in seen:
            continue
        seen[key] = a
    return list(seen.values())


def apply_daily_budget(
    alerts: list[Alert],
    budget: int = DEFAULT_DAILY_BUDGET,
) -> list[Alert]:
    """Limit non-SEVERE alerts to *budget* per day. SEVERE alerts are exempt."""
    severe = [a for a in alerts if a.level == "SEVERE"]
    rest = [a for a in alerts if a.level != "SEVERE"]
    return severe + rest[:budget]

