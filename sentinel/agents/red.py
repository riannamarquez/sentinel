"""Red agent, stubbed: returns the hand-written slow-variant bypass from fixtures. No LLM."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from sentinel.fixtures import load_bypass_trace
from sentinel.schemas import MAX_ACTIONS, Model, Rule, SimulationAction


@dataclass(frozen=True)
class RedCandidate:
    """What Red proposes: allowlisted actions plus the scenario frame they run in."""
    template_id: str
    start_ts: int
    source_account_id: str
    funding_cents: int
    actions: list[SimulationAction]
    rationale: str


# create bounds so that a scenario doesn't get overwhelmed with > 30 actions
class Recipe(Model):
    """The knobs Red turns to build a hop-chain attack; frozen, so a tweak is a model_copy."""
    n_mules: int = Field(ge=1, le=MAX_ACTIONS)    # mule accounts the money passes through
    hold_hours: int = Field(ge=0, le=168)          # how long each mule holds before forwarding
    n_splits: int = Field(ge=1, le=MAX_ACTIONS)   # transfers per hop, all to the same next account
    new_device: bool                               # send from a newly added device (what R3 looks for)
    funding_cents: int = Field(ge=400_000, le=900_000)   # stolen amount deposited into SRC; fraud.start()'s range

    @property
    def n_actions(self) -> int:
        """One open per mule, n_splits transfers on each of the n_mules + 1 hops, one device change."""
        return self.n_mules + self.n_splits * (self.n_mules + 1) + int(self.new_device)

    @model_validator(mode="after")
    def _check(self) -> Recipe:
        if self.n_actions > MAX_ACTIONS:
            raise ValueError(f"recipe needs {self.n_actions} actions; a scenario allows at most {MAX_ACTIONS}")
        return self


def propose(objective_cents: int, rules: Sequence[Rule], turn: int) -> list[RedCandidate]:
    """Same candidate every turn. The real agent would use the rules and its search history."""
    trace = load_bypass_trace()
    s = trace.scenario
    return [RedCandidate(template_id=s.template_id, start_ts=s.start_ts, source_account_id=s.source_account_id,
                         funding_cents=s.funding_cents, actions=list(s.actions), rationale=trace.rationale)]
