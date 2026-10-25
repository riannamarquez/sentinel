""""What Blue missed": one evaluation report broken down by attack pattern and benign customer type.

Analyst-facing, so it may use ground-truth labels and template ids (Red and Blue never see this).
"""
from __future__ import annotations

from pydantic import model_validator

from sentinel.schemas import Count, Id, Model, Version

PATTERN_LABELS: dict[str, str] = {        # attack templates in sentinel/sim/fraud.py
    "fast_ring": "Fast mule ring",
    "slow_chain_3": "Slow three-mule chain",
    "slow_split": "Split into two branches",
    "slow_small_new_device": "Small sums, new device",
    "slow_long_hold": "Long hold at one mule",
    "short_chain": "Single-mule chain",
}

SEGMENT_LABELS: dict[str, str] = {        # benign templates in sentinel/sim/benign.py
    "salaried": "Salaried workers",
    "gig": "Gig workers",
    "student": "Students",
    "small_business": "Small businesses",
    "salaried_relay": "Salaried, passes money on",
}


def pattern_label(template_id: str) -> str:
    return PATTERN_LABELS.get(template_id, template_id)


def segment_label(template_id: str) -> str:
    return SEGMENT_LABELS.get(template_id, template_id)


class WhyMissed(Model):
    rule_id: Id                          # "-" when no rule came close
    reason: str                          # describe() text
    count: Count


class PatternResult(Model):
    pattern: Id                          # attack template id
    label: str
    total: Count
    caught_before: Count                 # by the baseline rules
    caught: Count                        # by the candidate rules
    missed: Count
    why_missed: list[WhyMissed]          # most common first; empty when nothing was missed

    @model_validator(mode="after")
    def _check(self) -> PatternResult:
        if self.caught + self.missed != self.total:
            raise ValueError(f"{self.pattern}: caught + missed must equal total")
        if self.caught_before > self.total:
            raise ValueError(f"{self.pattern}: caught_before cannot exceed total")
        return self


class CustomerTypeResult(Model):
    segment: Id                          # benign template id
    label: str
    total: Count
    flagged_before: Count
    flagged: Count
    by_rule: dict[str, Count]            # candidate rules that fired on the flagged scenarios

    @model_validator(mode="after")
    def _check(self) -> CustomerTypeResult:
        if self.flagged > self.total or self.flagged_before > self.total:
            raise ValueError(f"{self.segment}: flagged cannot exceed total")
        return self


class FalseAlarms(Model):
    benign_total: Count
    flagged_before: Count
    flagged: Count
    by_customer_type: list[CustomerTypeResult]   # most flagged first

    @model_validator(mode="after")
    def _check(self) -> FalseAlarms:
        if self.flagged > self.benign_total or self.flagged_before > self.benign_total:
            raise ValueError("flagged cannot exceed benign_total")
        return self


class AttackTotals(Model):
    total: Count
    caught_before: Count
    caught: Count
    missed: Count


class Breakdown(Model):
    report_id: Id
    run_id: Id
    baseline_version: Version
    candidate_version: Version
    attacks: AttackTotals
    patterns: list[PatternResult]
    false_alarms: FalseAlarms

    @model_validator(mode="after")
    def _check(self) -> Breakdown:
        for field in ("total", "caught_before", "caught", "missed"):
            if getattr(self.attacks, field) != sum(getattr(p, field) for p in self.patterns):
                raise ValueError(f"attacks.{field} must equal the sum over patterns")
        return self
