'''
Goal: One module that turns a scored scenario into "how close did each rule come"
Used by: Red's history (So red can adapt to what caught it)
    Analyst breakdown
    Lives in detector folder because it reads rules/features
        separate from the agents' actions.

    '''
from collections.abc import Sequence

from __future__ import annotations

from pydantic import Field


from sentinel.detector.score import diagnose, rules_fired
from sentinel.schemas import FeatureKey, Model, Operator

"""Explain a scored scenario: how close each rule that did not fire came to firing (2c)."""
from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from sentinel.detector.score import diagnose, rules_fired
from sentinel.schemas import FeatureKey, Model, Operator, Rule, Scenario


class NearMiss(Model):
    """The condition that came closest to firing, for one rule that did not fire."""
    rule_id: str = Field(pattern=r"^R[0-9]{1,4}$")
    feature_key: FeatureKey
    operator: Operator
    threshold: int | float
    closest_value: float
    gap: float = Field(ge=0)                       # 0 = fired; bigger = further from firing
    window_hours: int | None = None                # the rule's look-back window, for the sentence


def gap(operator: str, threshold: float, closest: float) -> float:
    """How far `closest` was from satisfying `closest <operator> threshold`, as a share of the threshold."""
    if operator in (">=", ">"):
        short = threshold - closest                # needed to go up
    else:
        short = closest - threshold                # needed to go down
    if operator in (">", "<") and short == 0:
        short = 1e-9                               # sitting exactly on a strict threshold still misses
    if short <= 0:
        return 0.0
    return short / threshold if threshold else short   # threshold 0: fall back to the raw distance


def near_misses(scenario: Scenario, rules: Sequence[Rule]) -> list[NearMiss]:
    """For each rule that did not fire, the condition that blocked it with the smallest gap."""
    fired = rules_fired(scenario, rules)
    windows = {r.rule_id: [c.window_hours for c in r.all_of] for r in rules}
    out = []
    for rd in diagnose(scenario, rules):
        if rd.rule_id in fired:
            continue
        # Only conditions that never fired blocked the rule; one that fired has gap 0 but saved nobody.
        blockers = [(i, c) for i, c in enumerate(rd.conditions) if c.held]
        if not blockers:
            continue   # every condition fired somewhere but never on the same transfer; nothing single blocked it
        i, best = min(blockers, key=lambda ic: gap(ic[1].operator, ic[1].threshold, ic[1].closest_value))
        out.append(NearMiss(
            rule_id=rd.rule_id, feature_key=best.feature_key, operator=best.operator,
            threshold=best.threshold, closest_value=best.closest_value,
            gap=gap(best.operator, best.threshold, best.closest_value),
            window_hours=windows[rd.rule_id][i],
        ))
    return out


FEATURE_LABELS: dict[str, str] = {
    "velocity_out_count": "transfers sent", # labels each action
    "velocity_out_amount": "money sent",
    "velocity_in_amount": "money received",
    "transfer_amount": "largest single transfer",
    "near_threshold_amount": "transfers just under the reporting limit",
    "pass_through_ratio": "share of incoming money passed on",
    "min_hold_hours": "time money sat before moving on",
    "short_hold_hop_count": "hop count",
    "new_device_before_transfer": "sent from a new device",
}

FEATURE_KIND: dict[str, str] = {
    "velocity_out_count": "count",
    "velocity_out_amount": "dollars",
    "velocity_in_amount": "dollars",
    "transfer_amount": "dollars",
    "near_threshold_amount": "count",
    "pass_through_ratio": "percent",
    "min_hold_hours": "hours",
    "short_hold_hop_count": "count",
    "new_device_before_transfer": "yes_no",
}

# Features whose value is a total over a look-back window, so "within Nh" belongs in the sentence.
_WINDOWED = {"velocity_out_count", "velocity_out_amount", "velocity_in_amount",
             "near_threshold_amount", "pass_through_ratio"}

_SYMBOL = {">=": "≥", ">": ">", "<=": "≤", "<": "<"}


def _fmt(kind: str, value: float) -> str:
    if kind == "dollars":
        return f"${value / 100:,.0f}"
    if kind == "percent":
        return f"{value * 100:.0f}%"
    if kind == "hours":
        return f"{value:g}h"
    if kind == "yes_no":
        return "yes" if value >= 1 else "no"
    return f"{value:g}"                            # count


def describe(nm: NearMiss) -> str:
    """One plain-English sentence, e.g. "hop count reached 3; rule needs ≥ 4"."""
    label, kind = FEATURE_LABELS[nm.feature_key], FEATURE_KIND[nm.feature_key]
    if nm.window_hours and nm.feature_key in _WINDOWED:
        label = f"{label} within {nm.window_hours}h"
    if kind == "yes_no":
        return f"{label}: {_fmt(kind, nm.closest_value)}; rule needs {_fmt(kind, nm.threshold)}"
    return (f"{label} reached {_fmt(kind, nm.closest_value)}; "
            f"rule needs {_SYMBOL[nm.operator]} {_fmt(kind, nm.threshold)}")