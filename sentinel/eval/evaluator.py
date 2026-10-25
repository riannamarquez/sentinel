"""Evaluator: baseline and candidate rules on identical frozen splits (design-v2 §6.1). No LLM."""
from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from sentinel.detector.score import score
from sentinel.eval import gates
from sentinel.features.registry import resolved_params
from sentinel.schemas import (
    Condition, Confusion, EvaluationReport, MissReason, Rule, Scenario, Split, canonical_json, sha256_of,
)
from sentinel.sim.clock import HOUR


def dataset_hash(scenarios: Sequence[Scenario]) -> str:
    h = hashlib.sha256()
    for s in scenarios:
        h.update(canonical_json([s.scenario_id, s.malicious_label]).encode())
        for t in s.transactions:
            h.update(canonical_json(t).encode())
    return h.hexdigest()


def flagged(scenarios: Sequence[Scenario], rules: Sequence[Rule]) -> set[str]:
    return {s.scenario_id for s in scenarios if score(s, rules).alert}


def confusion(scenarios: Sequence[Scenario], flags: set[str]) -> Confusion:
    tp = sum(1 for s in scenarios if s.malicious_label and s.scenario_id in flags)
    fp = sum(1 for s in scenarios if not s.malicious_label and s.scenario_id in flags)
    n_attack = sum(1 for s in scenarios if s.malicious_label)
    return Confusion(tp=tp, fp=fp, fn=n_attack - tp, tn=len(scenarios) - n_attack - fp)


def hop_condition(rules: Sequence[Rule]) -> Condition | None:
    """The first short_hold_hop_count check in the rules: the source of the miss thresholds."""
    return next((c for r in rules for c in r.all_of if c.feature_key == "short_hold_hop_count"), None)


def required_hops(cond: Condition) -> int:
    """Smallest hop count that makes the condition fire (">=" or ">" only)."""
    return math.ceil(cond.threshold) if cond.operator == ">=" else math.floor(cond.threshold) + 1


def miss_reason(scenario: Scenario, cond: Condition | None) -> str:
    """Primary reason a hop-chain rule missed this attack, checked in a fixed order."""
    if cond is None or cond.operator not in (">=", ">") or cond.window_hours is None:
        return "other"
    p = resolved_params(cond)
    hold_s, carry, window_s = p["hold_hours"] * HOUR, p["min_carry_pct"], cond.window_hours * HOUR
    need = required_hops(cond)
    txs = sorted(scenario.transactions, key=lambda t: (t.timestamp, t.transaction_id))
    # (earlier, later) pairs where money arrived in an account and something later left it.
    links = [(i, j) for j, y in enumerate(txs) for i in range(j) if txs[i].to_id == y.from_id]

    # long_hold: some account's most recent inflow sat at least hold_hours before going out.
    latest_in: dict[int, int] = {}
    for i, j in links:
        latest_in[j] = max(latest_in.get(j, 0), txs[i].timestamp)
    if any(txs[j].timestamp - ts >= hold_s for j, ts in latest_in.items()):
        return "long_hold"

    # short_chain: even ignoring hold and carry, no chain inside the window reaches the required length.
    def longest_ending_at(end: int) -> int:
        lo = txs[end].timestamp - window_s
        hops: dict[int, int] = {}
        for j in range(end + 1):
            if txs[j].timestamp > lo:
                hops[j] = 1 + max((hops[i] for i, k in links if k == j and i in hops), default=0)
        return hops[end]

    if max((longest_ending_at(j) for j in range(len(txs))), default=0) < need:
        return "short_chain"

    # low_carry: a quick hop forwarded less than the required share of what arrived.
    if any(txs[j].timestamp - txs[i].timestamp < hold_s and txs[j].amount_cents * 100 < txs[i].amount_cents * carry
           for i, j in links):
        return "low_carry"
    return "other"


def missed_breakdown(scenarios: Sequence[Scenario], flags: set[str], rules: Sequence[Rule]) -> list[MissReason]:
    """Counts of missed attacks by primary reason, in a fixed order, omitting empty buckets."""
    cond = hop_condition(rules)
    labels = {"other": "Other pattern"}
    if cond is not None and cond.operator in (">=", ">"):
        p = resolved_params(cond)
        labels |= {
            "long_hold": f"Held money longer than {p['hold_hours']} hours",
            "short_chain": f"Chain too short (under {required_hops(cond)} hops)",
            "low_carry": f"Forwarded less than {p['min_carry_pct']}% per hop",
        }
    counts = dict.fromkeys(["long_hold", "short_chain", "low_carry", "other"], 0)
    for s in scenarios:
        if s.malicious_label and s.scenario_id not in flags:
            counts[miss_reason(s, cond)] += 1
    return [MissReason(reason=r, label=labels[r], count=n) for r, n in counts.items() if n]


def evaluate(
    *, report_id: str, run_id: str, patch_id: str, splits: dict[Split, list[Scenario]],
    baseline_rules: Sequence[Rule], baseline_version: int, candidate_rules: Sequence[Rule],
    schema_ok: bool = True,
) -> EvaluationReport:
    base_flags = {split: flagged(sc, baseline_rules) for split, sc in splits.items()}
    cand_flags = {split: flagged(sc, candidate_rules) for split, sc in splits.items()}
    base_conf = {split: confusion(sc, base_flags[split]) for split, sc in splits.items()}
    cand_conf = {split: confusion(sc, cand_flags[split]) for split, sc in splits.items()}

    hold, reg = Split.FINAL_HOLDOUT, Split.REGRESSION
    attack_n = base_conf[hold].tp + base_conf[hold].fn
    benign_n = base_conf[hold].fp + base_conf[hold].tn
    reg_attacks = {s.scenario_id for s in splits[reg] if s.malicious_label}
    reg_benign_n = base_conf[reg].fp + base_conf[reg].tn
    results = [
        gates.schema_valid(schema_ok),
        gates.fpr_budget(base_conf[hold].fp, cand_conf[hold].fp, benign_n),
        gates.regression_no_loss(base_flags[reg] & reg_attacks, cand_flags[reg] & reg_attacks),
        gates.regression_benign(base_conf[reg].fp, cand_conf[reg].fp, reg_benign_n),
        gates.holdout_recall_gain(base_conf[hold].tp, cand_conf[hold].tp, attack_n),
    ]
    passed = {g.name: g.passed for g in results}
    gate_pass = all(passed.values())

    def rate(n: int, d: int) -> float | None:
        return n / d if d else None

    return EvaluationReport(
        report_id=report_id, run_id=run_id, patch_id=patch_id,
        baseline_version=baseline_version, candidate_version=baseline_version + 1,
        candidate_rules_hash=sha256_of(list(candidate_rules)),
        benign_n=benign_n, attack_n=attack_n,
        dataset_hashes={split: dataset_hash(sc) for split, sc in splits.items()},
        baseline_confusion=base_conf, candidate_confusion=cand_conf,
        recall_before=rate(base_conf[hold].tp, attack_n), recall_after=rate(cand_conf[hold].tp, attack_n),
        fpr_before=rate(base_conf[hold].fp, benign_n), fpr_after=rate(cand_conf[hold].fp, benign_n),
        regression_pass=passed["regression_no_loss"] and passed["regression_benign"],
        holdout_pass=passed["fpr_budget"] and passed["holdout_recall_gain"],
        gate_pass=gate_pass, gate_results=results, eligible_for_approval=gate_pass,
        missed_breakdown=missed_breakdown(splits[hold], cand_flags[hold], candidate_rules),
    )
