"""Balance never below 0 (design-v2 §4: Account)."""
import pytest

from sentinel.fixtures import load_golden
from sentinel.scenarios.factory import build_splits
from sentinel.schemas import BankConfig, SimulationAction
from sentinel.sim.actions import ActionError, apply_actions, is_external
from sentinel.sim.world import generate_world
from sentinel.schemas import Split


def assert_never_negative(opening: dict[str, int], txns) -> None:
    balance = dict(opening)
    for t in txns:
        if t.from_id in balance:
            balance[t.from_id] -= t.amount_cents
            assert balance[t.from_id] >= 0, f"{t.from_id} below 0 at {t.transaction_id}"
        elif not is_external(t.from_id):
            raise AssertionError(f"{t.transaction_id} spends from unknown account {t.from_id}")
        if t.to_id in balance:
            balance[t.to_id] += t.amount_cents


def test_every_factory_scenario_keeps_balances_non_negative():
    splits = build_splits(7, benign_n=120, attack_copies=3)
    for scenarios in splits.values():
        for s in scenarios:
            assert_never_negative(s.opening_balances_cents, s.transactions)


def test_fixture_scenarios_keep_balances_non_negative(fixture_splits):
    for scenarios in fixture_splits.values():
        for s in scenarios:
            assert_never_negative(s.opening_balances_cents, s.transactions)
    for name in ("caught_fraud", "missed_fraud_slow_variant", "legit_lookalike"):
        s, _ = load_golden(name)
        assert_never_negative(s.opening_balances_cents, s.transactions)


def test_world_keeps_balances_non_negative():
    world = generate_world(BankConfig(seed=11, account_count=80))
    assert_never_negative({a.account_id: a.balance_cents for a in world.accounts}, world.transactions)


def _attack(actions, funding=10_000):
    return apply_actions(scenario_id="t.attack.0000", template_id="t", seed=0, split=Split.SEARCH, start_ts=0,
                         source_account_id="SRC", funding_cents=funding, actions=actions)


def test_red_cannot_overdraw():
    ok = [SimulationAction(type="open_synthetic_account", timestamp_offset=0, target_id="M1"),
          SimulationAction(type="simulated_transfer", timestamp_offset=60, source_id="SRC", target_id="M1",
                           amount_cents=10_000)]
    assert len(_attack(ok).transactions) == 2
    too_much = [*ok, SimulationAction(type="simulated_transfer", timestamp_offset=60, source_id="M1",
                                      target_id="EXT-cashout", amount_cents=10_001)]
    with pytest.raises(ActionError, match="needs 10001"):
        _attack(too_much)


@pytest.mark.parametrize("bad, reason", [
    (SimulationAction(type="simulated_transfer", timestamp_offset=0, source_id="SRC", target_id="M9",
                      amount_cents=1), "does not exist"),
    (SimulationAction(type="simulated_transfer", timestamp_offset=0, source_id="EXT-bank", target_id="SRC",
                      amount_cents=1), "not an account this scenario controls"),
    (SimulationAction(type="open_synthetic_account", timestamp_offset=0, target_id="SRC"), "cannot open"),
])
def test_invalid_actions_reject_the_scenario(bad, reason):
    with pytest.raises(ActionError, match=reason):
        _attack([bad])


def test_actions_cannot_run_past_the_horizon():
    wait = SimulationAction(type="wait", timestamp_offset=8 * 86400)
    with pytest.raises(ActionError, match="horizon"):
        _attack([wait, wait])
