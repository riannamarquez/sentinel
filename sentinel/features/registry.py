"""Feature library (design-v2 §5.2). Features only ever receive a HistoryView (no lookahead, §5.3).

Each feature is f(view, window_hours, params) -> float. The registry key is what rules and Blue
may reference; FeatureSpec carries the bounds patch validation checks against.
"""
from __future__ import annotations

import math
import typing
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sentinel.schemas import MAX_CENTS, Condition, FeatureKey, Transaction
from sentinel.sim.clock import HOUR


@dataclass(frozen=True, slots=True)
class HistoryView:
    """Transactions with timestamp <= the scored transaction's, plus the scored transaction."""
    txns: tuple[Transaction, ...]
    scored: Transaction
    initial_devices: dict[str, str]


def _window_start(v: HistoryView, window_h: int) -> int:
    return v.scored.timestamp - window_h * HOUR


def velocity_out_count(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, _window_start(v, window_h)
    return sum(1 for x in v.txns if x.from_id == a and x.timestamp > lo)


def velocity_out_amount(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, _window_start(v, window_h)
    return sum(x.amount_cents for x in v.txns if x.from_id == a and x.timestamp > lo)


def velocity_in_amount(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, _window_start(v, window_h)
    return sum(x.amount_cents for x in v.txns if x.to_id == a and x.timestamp > lo)


def pass_through_ratio(v: HistoryView, window_h: int, p: dict) -> float:
    out = velocity_out_amount(v, window_h, p)
    inflow = velocity_in_amount(v, window_h, p)
    return out / inflow if inflow else 0.0  # no inflow in window: nothing passed through


def new_device_before_transfer(v: HistoryView, window_h: int, p: dict) -> float:
    a, dev = v.scored.from_id, v.scored.device_id
    if dev is None or dev == v.initial_devices.get(a):
        return 0.0
    first_seen = min(x.timestamp for x in v.txns if x.from_id == a and x.device_id == dev)
    return 1.0 if v.scored.timestamp - first_seen < p["n_hours"] * HOUR else 0.0


def transfer_amount(v: HistoryView, window_h: int, p: dict) -> float:
    return v.scored.amount_cents


def near_threshold_amount(v: HistoryView, window_h: int, p: dict) -> float:
    """Outgoing transfers in the window within 10% below the reporting threshold."""
    a, lo, limit = v.scored.from_id, _window_start(v, window_h), p["reporting_threshold_cents"]
    return sum(1 for x in v.txns if x.from_id == a and x.timestamp > lo and limit * 9 <= x.amount_cents * 10 < limit * 10)


def min_hold_hours(v: HistoryView, window_h: int, p: dict) -> float:
    """Hours since the most recent inflow; the window length if nothing came in during it."""
    a, lo = v.scored.from_id, _window_start(v, window_h)
    arrivals = [x.timestamp for x in v.txns if x.to_id == a and x.timestamp > lo]
    return (v.scored.timestamp - max(arrivals)) / HOUR if arrivals else float(window_h)


def short_hold_hop_count(v: HistoryView, window_h: int, p: dict) -> float:
    """Longest chain of transfers ending at the scored one, where each transfer is sent
    < hold_hours after the previous one arrived and forwards >= min_carry_pct of its amount
    (the same money moving on). Time-respecting DP over the window, in timestamp order."""
    lo, hold_s, carry = _window_start(v, window_h), p["hold_hours"] * HOUR, p["min_carry_pct"]
    arrivals: dict[str, list[tuple[int, int, int]]] = defaultdict(list)  # account -> [(ts, hops, cents)]
    for x in v.txns:
        if x.timestamp <= lo:
            continue
        hops = 1 + max((h for ts, h, cents in arrivals[x.from_id]
                        if x.timestamp - ts < hold_s and x.amount_cents * 100 >= cents * carry), default=0)
        if x is v.scored:
            return hops
        arrivals[x.to_id].append((x.timestamp, hops, x.amount_cents))
    raise AssertionError("scored transaction missing from its own history view")


@dataclass(frozen=True)
class FeatureSpec:
    fn: Callable[[HistoryView, int, dict], float]
    threshold_bounds: tuple[float, float]
    needs_window: bool = True
    params: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # name -> (default, lo, hi)


FEATURES: dict[str, FeatureSpec] = {
    "velocity_out_count": FeatureSpec(velocity_out_count, (1, 1_000)),
    "velocity_out_amount": FeatureSpec(velocity_out_amount, (1, MAX_CENTS)),
    "velocity_in_amount": FeatureSpec(velocity_in_amount, (1, MAX_CENTS)),
    "new_device_before_transfer": FeatureSpec(
        new_device_before_transfer, (0, 1), needs_window=False, params={"n_hours": (24, 1, 168)}),
    "transfer_amount": FeatureSpec(transfer_amount, (1, MAX_CENTS), needs_window=False),
    "near_threshold_amount": FeatureSpec(
        near_threshold_amount, (1, 1_000), params={"reporting_threshold_cents": (1_000_000, 10_000, MAX_CENTS)}),
    "pass_through_ratio": FeatureSpec(pass_through_ratio, (0.1, 10)),
    "min_hold_hours": FeatureSpec(min_hold_hours, (0, 168)),
    "short_hold_hop_count": FeatureSpec(
        short_hold_hop_count, (2, 10), params={"hold_hours": (24, 1, 168), "min_carry_pct": (40, 0, 100)}),
}
assert set(FEATURES) == set(typing.get_args(FeatureKey)), "registry and schemas.FeatureKey must match"


def resolved_params(cond: Condition) -> dict[str, int]:
    spec = FEATURES[cond.feature_key]
    return {name: cond.params.get(name, default) for name, (default, _, _) in spec.params.items()}


def validate_condition(cond: Condition) -> None:
    """Raises ValueError when a condition is outside what the registry allows (design-v2 §6)."""
    spec = FEATURES[cond.feature_key]
    lo, hi = spec.threshold_bounds
    if not lo <= cond.threshold <= hi:
        raise ValueError(f"{cond.feature_key}: threshold {cond.threshold} outside [{lo}, {hi}]")
    if spec.needs_window and cond.window_hours is None:
        raise ValueError(f"{cond.feature_key} needs window_hours")
    if not spec.needs_window and cond.window_hours is not None:
        raise ValueError(f"{cond.feature_key} takes no window_hours")
    unknown = set(cond.params) - set(spec.params)
    if unknown:
        raise ValueError(f"{cond.feature_key}: unknown params {sorted(unknown)}")
    for name, value in cond.params.items():
        _, p_lo, p_hi = spec.params[name]
        if not p_lo <= value <= p_hi:
            raise ValueError(f"{cond.feature_key}: {name}={value} outside [{p_lo}, {p_hi}]")


def compute(cond: Condition, view: HistoryView) -> float:
    value = FEATURES[cond.feature_key].fn(view, cond.window_hours or 0, resolved_params(cond))
    if math.isnan(value):
        raise ValueError(f"{cond.feature_key} returned NaN")
    return float(value)
