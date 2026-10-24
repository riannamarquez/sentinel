"""Online, no-lookahead scoring (design-v2 §5.3).

This is the one place that builds HistoryViews: for each outgoing transaction from an account
the scenario owns, the view holds every transaction with timestamp <= that transaction's, and
nothing later. Features never see the full trace.
"""
from __future__ import annotations

import bisect
from collections.abc import Iterator, Sequence

from sentinel.features.registry import HistoryView, compute
from sentinel.schemas import (
    Condition, ConditionDiagnosis, DetectionResult, Rule, RuleDiagnosis, Scenario,
)

_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}


def views(scenario: Scenario) -> Iterator[HistoryView]:
    txns = tuple(scenario.transactions)
    timestamps = [t.timestamp for t in txns]
    owned = set(scenario.owned_account_ids)
    for t in txns:
        if t.from_id in owned:
            cut = bisect.bisect_right(timestamps, t.timestamp)
            yield HistoryView(txns[:cut], t, scenario.initial_devices)


def _value(cond: Condition, view: HistoryView, cache: dict) -> float:
    key = (cond.feature_key, cond.window_hours, tuple(sorted(cond.params.items())))
    if key not in cache:
        cache[key] = compute(cond, view)
    return cache[key]


def holds(cond: Condition, view: HistoryView, cache: dict) -> bool:
    return _OPS[cond.operator](_value(cond, view, cache), cond.threshold)


def score(scenario: Scenario, rules: Sequence[Rule], detector_version: int | None = None) -> DetectionResult:
    """Alert at the first outgoing transaction where any rule's conditions all hold."""
    for view in views(scenario):
        cache: dict = {}
        fired = [r for r in rules if all(holds(c, view, cache) for c in r.all_of)]
        if fired:
            snapshot = {f"{r.rule_id}.{c.feature_key}": _value(c, view, cache) for r in fired for c in r.all_of}
            return DetectionResult(
                scenario_id=scenario.scenario_id, detector_version=detector_version, alert=True,
                triggered_rule_ids=[r.rule_id for r in fired], features=snapshot,
                first_alert_time=view.scored.timestamp,
            )
    return DetectionResult(scenario_id=scenario.scenario_id, detector_version=detector_version, alert=False)


def timeline(scenario: Scenario, rules: Sequence[Rule]) -> list[tuple[str, tuple[str, ...]]]:
    """(transaction_id, rules that fire on it) for every scored transaction, in order."""
    out = []
    for view in views(scenario):
        cache: dict = {}
        out.append((view.scored.transaction_id,
                    tuple(r.rule_id for r in rules if all(holds(c, view, cache) for c in r.all_of))))
    return out


def rules_fired(scenario: Scenario, rules: Sequence[Rule]) -> set[str]:
    """Every rule that fires anywhere in the scenario, not just at the first alert."""
    out = set()
    for view in views(scenario):
        cache: dict = {}
        out |= {r.rule_id for r in rules if all(holds(c, view, cache) for c in r.all_of)}
    return out


def max_value(scenario: Scenario, cond: Condition) -> float:
    """Largest value a feature reaches across the scenario's outgoing transactions."""
    return max((compute(cond, v) for v in views(scenario)), default=0.0)


def diagnose(scenario: Scenario, rules: Sequence[Rule]) -> list[RuleDiagnosis]:
    """For each rule and condition, the value that came closest to firing ("why it worked")."""
    all_views = list(views(scenario))
    out = []
    for r in rules:
        conds = []
        for c in r.all_of:
            values = [compute(c, v) for v in all_views] or [0.0]
            closest = max(values) if c.operator in (">=", ">") else min(values)
            conds.append(ConditionDiagnosis(
                feature_key=c.feature_key, operator=c.operator, threshold=c.threshold,
                closest_value=closest, held=not any(_OPS[c.operator](x, c.threshold) for x in values),
            ))
        out.append(RuleDiagnosis(rule_id=r.rule_id, conditions=conds))
    return out
