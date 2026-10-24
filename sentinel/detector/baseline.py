"""Baseline detector v1 (design-v2 §4.2) and the demo fix used by the feasibility check."""
from __future__ import annotations

from sentinel.schemas import Condition, Rule

BASELINE_V1: list[Rule] = [
    # Velocity only counts when real money leaves: >= $1,000 out in the same hour (not bill-splitting).
    Rule(rule_id="R1", all_of=[
        Condition(feature_key="velocity_out_count", operator=">=", threshold=5, window_hours=1),
        Condition(feature_key="velocity_out_amount", operator=">=", threshold=100_000, window_hours=1),
    ]),
    # Pass-through only counts when a mule-sized sum came in: >= $5,000 received in the same 6h window.
    Rule(rule_id="R2", all_of=[
        Condition(feature_key="pass_through_ratio", operator=">=", threshold=0.9, window_hours=6),
        Condition(feature_key="velocity_in_amount", operator=">=", threshold=500_000, window_hours=6),
    ]),
    Rule(rule_id="R3", all_of=[
        Condition(feature_key="new_device_before_transfer", operator=">=", threshold=1, params={"n_hours": 24}),
        Condition(feature_key="transfer_amount", operator=">=", threshold=100_000),
    ]),
]


def hop_count_condition(k: int = 4) -> Condition:
    return Condition(feature_key="short_hold_hop_count", operator=">=", threshold=k, window_hours=72,
                     params={"hold_hours": 24, "min_carry_pct": 40})


def hop_count_rule(k: int = 4, rule_id: str = "R4") -> Rule:
    return Rule(rule_id=rule_id, all_of=[hop_count_condition(k)])
