"""The demo's riskiest assumption, as a test: the golden patch passes every gate (review 5.2)."""
from sentinel.detector.baseline import BASELINE_V1
from sentinel.detector.patches import apply_patch
from sentinel.detector.score import score
from sentinel.eval import gates
from sentinel.eval.evaluator import evaluate
from sentinel.fixtures import load_golden, load_golden_patch
from sentinel.scenarios.factory import final_holdout
from sentinel.schemas import Split


def test_golden_patch_passes_gates(fixture_splits, candidate_rules):
    report = evaluate(report_id="r1", run_id="run1", patch_id=load_golden_patch().patch_id, splits=fixture_splits,
                      baseline_rules=BASELINE_V1, baseline_version=1, candidate_rules=candidate_rules)
    failed = [g for g in report.gate_results if not g.passed]
    assert not failed, failed
    assert report.eligible_for_approval
    assert report.recall_after > report.recall_before
    hold = report.candidate_confusion[Split.FINAL_HOLDOUT]
    assert hold.tp + hold.fn == report.attack_n and hold.fp + hold.tn == report.benign_n


def test_golden_patch_passes_fpr_gate_on_full_size_holdout(candidate_rules):
    """500 households / 48 attacks, the size design-v2 §10 settles on."""
    scenarios = final_holdout(7, 500, 8)
    benign = [s for s in scenarios if not s.malicious_label]
    attacks = [s for s in scenarios if s.malicious_label]
    base_fp = sum(score(s, BASELINE_V1).alert for s in benign)
    cand_fp = sum(score(s, candidate_rules).alert for s in benign)
    base_tp = sum(score(s, BASELINE_V1).alert for s in attacks)
    cand_tp = sum(score(s, candidate_rules).alert for s in attacks)
    assert gates.fpr_budget(base_fp, cand_fp, len(benign)).passed
    assert gates.holdout_recall_gain(base_tp, cand_tp, len(attacks)).passed
    assert base_fp * 100 < 15 * len(benign)  # baseline v1 flags under 15% of benign households


def test_golden_story():
    rules = apply_patch(BASELINE_V1, load_golden_patch())
    caught, d = load_golden("caught_fraud")
    assert d.alert and "R1" in d.triggered_rule_ids
    slow, d = load_golden("missed_fraud_slow_variant")
    assert not d.alert and score(slow, rules).alert
    legit, d = load_golden("legit_lookalike")
    assert not d.alert and not score(legit, rules).alert


def test_a_patch_that_flags_everything_fails_the_fpr_gate(fixture_splits):
    from sentinel.schemas import Condition, PatchOperation, RulePatch
    greedy = RulePatch(patch_id="greedy", base_version=1, operation=PatchOperation.ADD,
                       all_of=[Condition(feature_key="transfer_amount", operator=">=", threshold=1)])
    report = evaluate(report_id="r2", run_id="run1", patch_id="greedy", splits=fixture_splits,
                      baseline_rules=BASELINE_V1, baseline_version=1,
                      candidate_rules=apply_patch(BASELINE_V1, greedy))
    by_name = {g.name: g for g in report.gate_results}
    assert not by_name["fpr_budget"].passed
    assert not report.eligible_for_approval
