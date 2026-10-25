"""Red agent. Recipe + recipe_to_candidate build hop-chain attacks from a few knobs. Two policies, no LLM:
FixtureRedPolicy replays the hand-written slow-variant bypass; HeuristicRedPolicy reacts to which rules
caught its earlier attempts by breaking one condition of each, chosen by feature."""
from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, ValidationError, model_validator

from sentinel.detector.explain import NearMiss
from sentinel.fixtures import load_bypass_trace
from sentinel.features.registry import resolved_params
from sentinel.schemas import MAX_ACTIONS, Cents, Condition, Model, Rule, SimulationAction
from sentinel.sim.actions import HORIZON_S, MAX_OPENED_ACCOUNTS
from sentinel.sim.clock import HOUR, MINUTE, rand_time
from sentinel.sim.fraud import CASHOUT, SOURCE, Plan
from sentinel.sim.rng import rng_for

FORWARD_PCT = 95   # each mule forwards this much of what it received and keeps the rest
MAX_SPLIT_GAP_MINUTES = 10   # recipe_to_candidate spaces a hop's splits 2-10 minutes apart


@dataclass(frozen=True)
class RedCandidate:
    """What Red proposes: allowlisted actions plus the scenario frame they run in."""
    template_id: str
    start_ts: int
    source_account_id: str
    funding_cents: int
    actions: list[SimulationAction]
    rationale: str
    recipe: Recipe | None = None   # set by recipe_to_candidate; None for the fixture bypass


# create bounds so that a scenario doesn't get overwhelmed with > 30 actions
class Recipe(Model):
    """The knobs Red turns to build a hop-chain attack; frozen, so tweak() builds a new, re-validated Recipe."""
    n_mules: int = Field(ge=1, le=MAX_OPENED_ACCOUNTS)   # mule accounts the money passes through
    hold_hours: int = Field(ge=0, le=168)          # how long each mule holds before forwarding
    n_splits: int = Field(ge=1, le=MAX_ACTIONS)   # transfers per hop, all to the same next account
    new_device: bool                               # send from a newly added device (what R3 looks for)
    funding_cents: int = Field(ge=400_000, le=900_000)   # stolen amount deposited into SRC; fraud.start()'s range

    @property
    def n_actions(self) -> int:
        """One open per mule, n_splits transfers on each of the n_mules + 1 hops, one device change."""
        return self.n_mules + self.n_splits * (self.n_mules + 1) + int(self.new_device)

    @property
    def duration_seconds(self) -> int:
        """Worst case from start_ts to the last transfer: each of the n_mules + 1 hops holds, then
        sends n_splits transfers up to MAX_SPLIT_GAP_MINUTES apart."""
        hop = self.hold_hours * HOUR + (self.n_splits - 1) * MAX_SPLIT_GAP_MINUTES * MINUTE
        return (self.n_mules + 1) * hop

    def tweak(self, **changes) -> Recipe:
        """A new Recipe with these fields changed, re-validated (model_copy(update=...) would skip that)."""
        return type(self).model_validate(self.model_dump() | changes)

    @model_validator(mode="after")
    def _check(self) -> Recipe:
        if self.n_actions > MAX_ACTIONS:
            raise ValueError(f"recipe needs {self.n_actions} actions; a scenario allows at most {MAX_ACTIONS}")
        if self.duration_seconds > HORIZON_S:
            raise ValueError(f"recipe can take {self.duration_seconds / HOUR:g}h; a scenario must finish within "
                             f"{HORIZON_S // HOUR}h of start_ts")
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
        recipe=recipe,
    )


class Attempt(Model):
    """One valid candidate Red already tried this run, and what the detector made of it."""
    turn: int
    recipe: Recipe
    rules_fired: list[str]
    moved_cents: Cents
    near_misses: list[NearMiss] = Field(default_factory=list)


class FixtureRedPolicy:
    """Same candidate every turn: the hand-written bypass from fixtures. Ignores its inputs."""

    def propose(self, *, objective_cents: int, rules: Sequence[Rule], turn: int, history: Sequence[Attempt],
                seed: int, run_id: str) -> list[RedCandidate]:
        trace = load_bypass_trace()
        s = trace.scenario
        return [RedCandidate(template_id=s.template_id, start_ts=s.start_ts, source_account_id=s.source_account_id,
                             funding_cents=s.funding_cents, actions=list(s.actions), rationale=trace.rationale)]


NAIVE = Recipe(n_mules=2, hold_hours=1, n_splits=1, new_device=False, funding_cents=800_000)
VARIANTS = ({"hold_hours": 6}, {"n_mules": -1}, {"n_mules": -1, "hold_hours": 6}, {"hold_hours": 12})  # deltas
MAX_CANDIDATES = 5


def _fix(recipe: Recipe, cond: Condition) -> dict | None:
    """Knob changes that stop this one condition from holding, or None when no knob reaches its feature."""
    key, op, threshold = cond.feature_key, cond.operator, cond.threshold
    if key == "velocity_out_count":
        return {"n_splits": 1}
    if key in ("pass_through_ratio", "velocity_in_amount"):        # look back window_hours from each send
        return {"hold_hours": max(recipe.hold_hours, cond.window_hours + 1)}
    if key == "new_device_before_transfer":
        return {"new_device": False}
    if key == "short_hold_hop_count":                               # a hop counts if sent < hold_hours after arrival
        return {"hold_hours": max(recipe.hold_hours, resolved_params(cond)["hold_hours"] + 1)}
    if key == "min_hold_hours":                                     # each send goes hold_hours after the last arrival
        if op == "<":
            return {"hold_hours": max(recipe.hold_hours, math.ceil(threshold))}
        if op == "<=":
            return {"hold_hours": max(recipe.hold_hours, math.floor(threshold) + 1)}
        if op == ">":
            return {"hold_hours": min(recipe.hold_hours, math.floor(threshold))}
        return {"hold_hours": min(recipe.hold_hours, math.ceil(threshold) - 1)}
    return None


def _reaches_objective(recipe: Recipe, objective_cents: int) -> bool:
    """funding * (FORWARD_PCT/100)^hops >= objective, in integers; every hop keeps a cut."""
    hops = recipe.n_mules + 1
    return recipe.funding_cents * FORWARD_PCT ** hops >= objective_cents * 100 ** hops


class HeuristicRedPolicy:
    """Starts naive, then from its best attempt so far breaks one condition of every rule that fired.

    Fixes are chosen by feature, never by rule id, so rules Blue adds later are handled the same way.
    Which recipes it proposes is deterministic; only the start times come from rng_for.
    """

    def propose(self, *, objective_cents: int, rules: Sequence[Rule], turn: int, history: Sequence[Attempt],
                seed: int, run_id: str) -> list[RedCandidate]:
        tried = {a.recipe for a in history}
        recipes = [NAIVE] if not history else [r for r in self._next_recipes(rules, history) if r not in tried]
        recipes = [r for r in recipes if _reaches_objective(r, objective_cents)][:MAX_CANDIDATES]
        return [recipe_to_candidate(r, rng_for(seed, run_id, "red", turn, i)) for i, r in enumerate(recipes)]

    def _next_recipes(self, rules: Sequence[Rule], history: Sequence[Attempt]) -> list[Recipe]:
        # Best so far: fewest rules fired, then most money moved, then the latest turn.
        best = min(history, key=lambda a: (len(a.rules_fired), -a.moved_cents, -a.turn))
        by_id = {r.rule_id: r for r in rules}
        fixed = best.recipe
        for rule_id in best.rules_fired:       # fixes stack: each one starts from the previous result
            rule = by_id.get(rule_id)
            if rule is None:
                continue
            for cond in rule.all_of:           # a rule is an AND, so breaking one condition is enough
                changes = _fix(fixed, cond)
                if changes is None:
                    continue
                try:
                    tweaked = fixed.tweak(**changes)
                except ValidationError:
                    continue
                if tweaked != fixed:           # a fix that changes nothing didn't break this condition
                    fixed = tweaked
                    break

        out = [fixed]
        for delta in VARIANTS:
            try:
                out.append(fixed.tweak(**{k: getattr(fixed, k) + v for k, v in delta.items()}))
            except ValidationError:
                pass
        return list(dict.fromkeys(out))        # drop duplicates, keep order (frozen models are hashable)
