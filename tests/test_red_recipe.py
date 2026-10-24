"""Red's recipe builder: each knob maps to the rule it should (or should not) trip."""
import pytest
from pydantic import ValidationError

from sentinel.agents.red import Recipe, recipe_to_candidate
from sentinel.detector.baseline import BASELINE_V1
from sentinel.detector.score import score
from sentinel.fixtures import OBJECTIVE_CENTS
from sentinel.schemas import Split
from sentinel.sim.actions import HORIZON_S, apply_actions, moved_out_cents
from sentinel.sim.rng import rng_for


def recipe(**kw) -> Recipe:
    return Recipe(**{"funding_cents": 800_000, "new_device": False, **kw})


def candidate(r: Recipe, seed: int = 7):
    return recipe_to_candidate(r, rng_for(seed, "red", 1, 0))


def scenario(r: Recipe, seed: int = 7):
    c = candidate(r, seed)
    return apply_actions(scenario_id="t", template_id=c.template_id, seed=1, split=Split.SEARCH,
                         start_ts=c.start_ts, source_account_id=c.source_account_id,
                         funding_cents=c.funding_cents, actions=c.actions)


TABLE = [
    (dict(n_mules=2, hold_hours=1, n_splits=1), ["R2"], ["R2"]),
    (dict(n_mules=2, hold_hours=1, n_splits=6), ["R1"], ["R1"]),
    (dict(n_mules=2, hold_hours=12, n_splits=1), [], ["R4"]),
    (dict(n_mules=3, hold_hours=12, n_splits=1, new_device=True), ["R3"], ["R3"]),
    (dict(n_mules=1, hold_hours=12, n_splits=1), [], []),
    (dict(n_mules=2, hold_hours=25, n_splits=1), [], []),
]


@pytest.mark.parametrize("knobs, v1, v2", TABLE)
def test_recipe_trips_the_expected_rules(knobs, v1, v2, candidate_rules):
    s = scenario(recipe(**knobs))
    assert score(s, BASELINE_V1).triggered_rule_ids == v1
    assert score(s, candidate_rules).triggered_rule_ids == v2


@pytest.mark.parametrize("knobs", [k for k, _, _ in TABLE])
def test_recipe_meets_the_objective(knobs):
    assert moved_out_cents(scenario(recipe(**knobs))) >= OBJECTIVE_CENTS


def test_recipe_is_deterministic():
    r = recipe(n_mules=3, hold_hours=12, n_splits=3, new_device=True)
    assert candidate(r) == candidate(r)


def test_too_many_actions_is_rejected():
    with pytest.raises(ValidationError, match="actions"):
        recipe(n_mules=6, hold_hours=1, n_splits=4, new_device=True)


def test_too_long_is_rejected():
    with pytest.raises(ValidationError, match="within"):
        recipe(n_mules=6, hold_hours=168, n_splits=1)


@pytest.mark.parametrize("n_mules, n_splits", [(6, 1), (3, 4)])
def test_longest_accepted_recipe_fits_the_horizon(n_mules, n_splits):
    longest = max(h for h in range(169) if recipe(n_mules=n_mules, hold_hours=0, n_splits=n_splits)
                  .duration_seconds + (n_mules + 1) * h * 3600 <= HORIZON_S)
    r = recipe(n_mules=n_mules, hold_hours=longest, n_splits=n_splits)
    with pytest.raises(ValidationError):
        r.tweak(hold_hours=longest + 1)
    for seed in range(20):   # split gaps are random; none may push past the horizon
        scenario(r, seed)


def test_tweak_revalidates_and_does_not_mutate():
    r = recipe(n_mules=2, hold_hours=12, n_splits=1)
    t = r.tweak(hold_hours=13)
    assert t is not r and t.hold_hours == 13 and r.hold_hours == 12
    assert t.model_dump() == r.model_dump() | {"hold_hours": 13}
    with pytest.raises(ValidationError):
        r.tweak(hold_hours=9999)
    with pytest.raises(ValidationError):
        r.tweak(n_mules=6, n_splits=4, new_device=True)   # _check still applies
