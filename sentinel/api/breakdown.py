""""What Blue missed": one evaluation report broken down by attack pattern and benign customer type.

Analyst-facing, so it may use ground-truth labels and template ids (Red and Blue never see this).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pydantic import model_validator

from sentinel.detector.explain import describe, near_misses
from sentinel.detector.score import score
from sentinel.schemas import Count, Id, Model, Rule, Scenario, Version

NO_NEAR_MISS = ("-", "no rule came close")

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


def build_breakdown(scenarios: Sequence[Scenario], baseline_rules: Sequence[Rule], candidate_rules: Sequence[Rule],
                    *, report_id: str, run_id: str, baseline_version: int, candidate_version: int) -> Breakdown:
    """Pure: score every final-holdout scenario against both rule sets and group by template. No I/O."""
    attacks: dict[str, list[Scenario]] = {}
    benign: dict[str, list[Scenario]] = {}
    for s in scenarios:
        (attacks if s.malicious_label else benign).setdefault(s.template_id, []).append(s)

    patterns = []
    for template_id, group in attacks.items():
        caught_before = sum(score(s, baseline_rules).alert for s in group)
        missed = [s for s in group if not score(s, candidate_rules).alert]
        why = Counter()
        for s in missed:
            misses = near_misses(s, candidate_rules)
            nearest = min(misses, key=lambda nm: nm.gap) if misses else None
            why[(nearest.rule_id, describe(nearest)) if nearest else NO_NEAR_MISS] += 1
        patterns.append(PatternResult(
            pattern=template_id, label=pattern_label(template_id), total=len(group),
            caught_before=caught_before, caught=len(group) - len(missed), missed=len(missed),
            why_missed=[WhyMissed(rule_id=r, reason=reason, count=n)
                        for (r, reason), n in sorted(why.items(), key=lambda kv: (-kv[1], kv[0]))],
        ))

    customer_types = []
    for template_id, group in benign.items():
        flagged_before = sum(score(s, baseline_rules).alert for s in group)
        by_rule, flagged = Counter(), 0
        for s in group:
            result = score(s, candidate_rules)
            if result.alert:
                flagged += 1
                by_rule.update(result.triggered_rule_ids)
        customer_types.append(CustomerTypeResult(
            segment=template_id, label=segment_label(template_id), total=len(group),
            flagged_before=flagged_before, flagged=flagged, by_rule=dict(sorted(by_rule.items())),
        ))
    customer_types.sort(key=lambda c: -c.flagged)   # stable: ties keep holdout order

    return Breakdown(
        report_id=report_id, run_id=run_id, baseline_version=baseline_version, candidate_version=candidate_version,
        attacks=AttackTotals(total=sum(p.total for p in patterns), caught_before=sum(p.caught_before for p in patterns),
                             caught=sum(p.caught for p in patterns), missed=sum(p.missed for p in patterns)),
        patterns=patterns,
        false_alarms=FalseAlarms(
            benign_total=sum(c.total for c in customer_types),
            flagged_before=sum(c.flagged_before for c in customer_types),
            flagged=sum(c.flagged for c in customer_types), by_customer_type=customer_types),
    )
