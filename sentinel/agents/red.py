"""Red agent, stubbed: returns the hand-written slow-variant bypass from fixtures. No LLM."""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, model_validator

from sentinel.fixtures import load_bypass_trace
from sentinel.schemas import MAX_ACTIONS, Model, Rule, SimulationAction
from sentinel.sim.actions import MAX_OPENED_ACCOUNTS
from sentinel.sim.clock import HOUR, MINUTE, rand_time
from sentinel.sim.fraud import CASHOUT, SOURCE, Plan

FORWARD_PCT = 95   # each mule forwards this much of what it received and keeps the rest


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
    n_mules: int = Field(ge=1, le=MAX_OPENED_ACCOUNTS)   # mule accounts the money passes through
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


def recipe_to_candidate(recipe: Recipe, rng: random.Random) -> RedCandidate:
    """SRC -> M1 -> ... -> Mn -> cash-out; every hop holds hold_hours, then sends n_splits transfers."""
    # Same start_ts draw as fraud.start(), which slow_chain_3 uses; the funding comes from the recipe.
    plan = Plan(start_ts=rand_time(rng, rng.randint(2, 18), 0, 23), funding_cents=recipe.funding_cents)
    mules = [f"M{i + 1}" for i in range(recipe.n_mules)]
    for m in mules:
        plan.open(plan.start_ts, m)
    if recipe.new_device:
        plan.change_device(plan.start_ts, SOURCE, f"{SOURCE}-d1")  # same time as the opens, added after them

    path = [SOURCE, *mules, CASHOUT]
    t, amount = plan.start_ts, recipe.funding_cents
    for i in range(len(path) - 1):
        t += recipe.hold_hours * HOUR             # hold counts from the last transfer that arrived
        amount = amount * FORWARD_PCT // 100
        parts = [amount // recipe.n_splits] * recipe.n_splits
        parts[-1] += amount % recipe.n_splits     # the remainder rides on the last split
        for j, part in enumerate(parts):
            if j:
                t += rng.randint(2, 10) * MINUTE
            plan.transfer(t, path[i], path[i + 1], part)

    return RedCandidate(
        template_id="recipe", start_ts=plan.start_ts, source_account_id=SOURCE,
        funding_cents=plan.funding_cents, actions=plan.actions(),
        rationale=(f"{recipe.n_mules} mules, {recipe.hold_hours}h holds, {recipe.n_splits} splits per hop"
                   + (", SRC on a new device" if recipe.new_device else "")),
    )


def propose(objective_cents: int, rules: Sequence[Rule], turn: int) -> list[RedCandidate]:
    """Same candidate every turn. The real agent would use the rules and its search history."""
    trace = load_bypass_trace()
    s = trace.scenario
    return [RedCandidate(template_id=s.template_id, start_ts=s.start_ts, source_account_id=s.source_account_id,
                         funding_cents=s.funding_cents, actions=list(s.actions), rationale=trace.rationale)]
