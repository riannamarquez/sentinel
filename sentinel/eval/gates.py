"""The hackathon gate (design-v2 §1, §6.2), one function per gate, integer arithmetic only."""
from __future__ import annotations

from sentinel.schemas import GateResult, Split

FPR_BUDGET_BP = 50      # FPR increase <= 0.5 percentage points = 50 basis points


def fp_budget(benign_n: int, budget_bp: int = FPR_BUDGET_BP) -> int:
    return benign_n * budget_bp // 10_000


def schema_valid(ok: bool, detail: str = "") -> GateResult:
    return GateResult(name="schema_valid", split=None, numerator=int(ok), denominator=1, threshold=1,
                      passed=ok, detail=detail)


def fpr_budget(base_fp: int, cand_fp: int, benign_n: int, budget_bp: int = FPR_BUDGET_BP) -> GateResult:
    new_fp, budget = cand_fp - base_fp, fp_budget(benign_n, budget_bp)
    return GateResult(name="fpr_budget", split=Split.FINAL_HOLDOUT, numerator=new_fp, denominator=benign_n,
                      threshold=budget, passed=new_fp <= budget,
                      detail=f"{new_fp:+d} false positives, budget {budget} ({budget_bp / 100:.1f} pp)")


def regression_no_loss(base_caught: set[str], cand_caught: set[str]) -> GateResult:
    kept = base_caught & cand_caught
    return GateResult(name="regression_no_loss", split=Split.REGRESSION, numerator=len(kept),
                      denominator=len(base_caught), threshold=len(base_caught), passed=base_caught <= cand_caught,
                      detail=f"{len(kept)}/{len(base_caught)} previously caught attacks still caught")


def regression_benign(base_fp: int, cand_fp: int, benign_n: int) -> GateResult:
    return GateResult(name="regression_benign", split=Split.REGRESSION, numerator=cand_fp, denominator=benign_n,
                      threshold=base_fp, passed=cand_fp <= base_fp,
                      detail=f"lookalikes flagged {base_fp} -> {cand_fp}")


def holdout_recall_gain(base_tp: int, cand_tp: int, attack_n: int, min_gain: int = 1) -> GateResult:
    saturated = base_tp == attack_n
    return GateResult(name="holdout_recall_gain", split=Split.FINAL_HOLDOUT, numerator=cand_tp - base_tp,
                      denominator=attack_n, threshold=min_gain,
                      passed=saturated or cand_tp - base_tp >= min_gain,
                      detail="n/a: baseline already catches every holdout attack" if saturated
                      else f"{base_tp} -> {cand_tp} of {attack_n} caught")
