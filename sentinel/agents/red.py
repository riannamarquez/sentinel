"""Red agent, stubbed: returns the hand-written slow-variant bypass from fixtures. No LLM."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sentinel.fixtures import load_bypass_trace
from sentinel.schemas import Rule, SimulationAction


@dataclass(frozen=True)
class RedCandidate:
    """What Red proposes: allowlisted actions plus the scenario frame they run in."""
    template_id: str
    start_ts: int
    source_account_id: str
    funding_cents: int
    actions: list[SimulationAction]
    rationale: str


def propose(objective_cents: int, rules: Sequence[Rule], turn: int) -> list[RedCandidate]:
    """Same candidate every turn. The real agent would use the rules and its search history."""
    trace = load_bypass_trace()
    s = trace.scenario
    return [RedCandidate(template_id=s.template_id, start_ts=s.start_ts, source_account_id=s.source_account_id,
                         funding_cents=s.funding_cents, actions=list(s.actions), rationale=trace.rationale)]
