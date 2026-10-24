"""Evaluator: baseline and candidate rules on identical frozen splits (design-v2 §6.1). No LLM."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sentinel.detector.score import score
from sentinel.eval import gates
from sentinel.schemas import (
    Confusion, EvaluationReport, Rule, Scenario, Split, canonical_json, sha256_of,
)


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
    )
