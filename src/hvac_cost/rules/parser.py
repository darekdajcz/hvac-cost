from __future__ import annotations

from typing import Any, List

from rules.models import Rule, ROI


def parse_roi(roi_raw: Any) -> ROI:
    roi_raw = roi_raw or {}

    return ROI(
        enabled=bool(roi_raw.get("enabled", False)),
        xmin=float(roi_raw.get("xmin", 0.0)),
        xmax=float(roi_raw.get("xmax", 0.0)),
        ymin=float(roi_raw.get("ymin", 0.0)),
        ymax=float(roi_raw.get("ymax", 0.0)),
        margin=float(roi_raw.get("margin", 0.0)),
    )


def parse_rule(rule_raw: Any) -> Rule:
    if not isinstance(rule_raw, dict):
        raise ValueError("Each rule must be an object")

    rule = Rule(
        id=str(rule_raw.get("id") or ""),
        name=str(rule_raw.get("name") or ""),
        type=str(rule_raw.get("type") or ""),
        enabled=bool(rule_raw.get("enabled", True)),
        roi=parse_roi(rule_raw.get("roi")),
        params=dict(rule_raw.get("params") or {}),
    )

    if not rule.id:
        raise ValueError("Rule id is required")
    if not rule.name:
        raise ValueError("Rule name is required")
    if not rule.type:
        raise ValueError("Rule type is required")

    return rule


def parse_rules(rules_raw: Any) -> List[Rule]:
    if not isinstance(rules_raw, list):
        raise ValueError("rules_json must be a list")

    return [parse_rule(rule_raw) for rule_raw in rules_raw]