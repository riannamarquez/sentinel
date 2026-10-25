"""HeuristicRedPolicy: no-op fixes fall through to the next condition, and tried recipes never repeat."""
from sentinel.agents.red import NAIVE, Attempt, HeuristicRedPolicy
from sentinel.detector.baseline import BASELINE_V1
from sentinel.fixtures import OBJECTIVE_CENTS
from sentinel.schemas import Condition, Rule


def propose(rules, history, turn=2):
    candidates = HeuristicRedPolicy().propose(objective_cents=OBJECTIVE_CENTS, rules=rules, turn=turn,
                                              history=history, seed=7, run_id="run-000001")
    return [c.recipe for c in candidates]


def test_a_no_op_fix_falls_through_to_the_next_condition():
    # NAIVE already has n_splits=1, so fixing velocity_out_count changes nothing; pass_through_ratio must be used.
    rules = [Rule(rule_id="R9", all_of=[
        Condition(feature_key="velocity_out_count", operator=">=", threshold=5, window_hours=1),
        Condition(feature_key="pass_through_ratio", operator=">=", threshold=0.9, window_hours=6),
    ])]
    history = [Attempt(turn=1, recipe=NAIVE, rules_fired=["R9"], moved_cents=685_900)]
    first = propose(rules, history)[0]
    assert first == NAIVE.tweak(hold_hours=7)


def test_propose_never_returns_a_recipe_already_in_history():
    # The best attempt (latest turn) already holds 7h, so R2's fixes are all no-ops and the "fixed"
    # recipe is the one just tried; it and its variants that were tried must not come back.
    held = NAIVE.tweak(hold_hours=7)
    history = [
        Attempt(turn=1, recipe=NAIVE, rules_fired=["R2"], moved_cents=685_900),
        Attempt(turn=2, recipe=held, rules_fired=["R2"], moved_cents=685_900),
        Attempt(turn=2, recipe=held.tweak(hold_hours=13), rules_fired=["R2"], moved_cents=685_900),
    ]
    proposed = propose(BASELINE_V1, history, turn=3)
    assert proposed, "there are untried variants left"
    assert not {a.recipe for a in history} & set(proposed)
