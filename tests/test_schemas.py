import pytest
from pydantic import ValidationError

from sentinel.detector.baseline import BASELINE_V1, hop_count_rule
from sentinel.detector.patches import PatchError, apply_patch, validate_rules
from sentinel.features.registry import validate_condition
from sentinel.schemas import (
    BankConfig, Condition, Label, PatchOperation, Rule, RulePatch, SimulationAction, Transaction,
)


def test_bank_config_bounds():
    BankConfig(seed=7)
    with pytest.raises(ValidationError):
        BankConfig(seed=7, account_count=0)
    with pytest.raises(ValidationError):
        BankConfig(seed=7, initial_balance_range_cents=(500, 100))
    with pytest.raises(ValidationError):
        BankConfig(seed=7, unknown_field=1)


def test_transaction_is_integer_cents_and_not_to_self():
    base = dict(transaction_id="t1", from_id="A", to_id="B", amount_cents=100, timestamp=0,
                scenario_id="s", ground_truth_label=Label.BENIGN)
    Transaction(**base)
    with pytest.raises(ValidationError):
        Transaction(**{**base, "amount_cents": 1.5})
    with pytest.raises(ValidationError):
        Transaction(**{**base, "amount_cents": 0})
    with pytest.raises(ValidationError):
        Transaction(**{**base, "to_id": "A"})


def test_action_fields_must_match_type():
    SimulationAction(type="wait", timestamp_offset=60)
    with pytest.raises(ValidationError):
        SimulationAction(type="simulated_transfer", timestamp_offset=0, source_id="A", target_id="B")
    with pytest.raises(ValidationError):
        SimulationAction(type="wait", timestamp_offset=0, amount_cents=5)


def test_rule_has_one_to_three_conditions():
    c = Condition(feature_key="transfer_amount", operator=">=", threshold=1)
    Rule(rule_id="R9", all_of=[c, c, c])
    with pytest.raises(ValidationError):
        Rule(rule_id="R9", all_of=[])
    with pytest.raises(ValidationError):
        Rule(rule_id="R9", all_of=[c] * 4)
    with pytest.raises(ValidationError):
        Condition(feature_key="not_a_feature", operator=">=", threshold=1)
    with pytest.raises(ValidationError):
        Condition(feature_key="transfer_amount", operator="==", threshold=1)


def test_baseline_rules_pass_registry_validation():
    validate_rules(BASELINE_V1)
    validate_rules([*BASELINE_V1, hop_count_rule()])


def test_condition_bounds_from_registry():
    with pytest.raises(ValueError):
        validate_condition(Condition(feature_key="velocity_out_count", operator=">=", threshold=5))  # no window
    with pytest.raises(ValueError):
        validate_condition(Condition(feature_key="short_hold_hop_count", operator=">=", threshold=50, window_hours=72))
    with pytest.raises(ValueError):
        validate_condition(Condition(feature_key="short_hold_hop_count", operator=">=", threshold=4, window_hours=72,
                                     params={"n_hours": 3}))


def test_patch_shapes_and_application():
    add = RulePatch(patch_id="p1", base_version=1, operation=PatchOperation.ADD, rule_id="R1",
                    all_of=hop_count_rule().all_of)
    rules = apply_patch(BASELINE_V1, add)
    assert [r.rule_id for r in rules] == ["R1", "R2", "R3", "R4"]  # server assigns the id
    rules = apply_patch(rules, RulePatch(patch_id="p2", base_version=2, operation="disable", rule_id="R2"))
    assert [r.rule_id for r in rules] == ["R1", "R3", "R4"]
    with pytest.raises(PatchError):
        apply_patch(BASELINE_V1, RulePatch(patch_id="p3", base_version=1, operation="disable", rule_id="R9"))
    with pytest.raises(ValidationError):
        RulePatch(patch_id="p4", base_version=1, operation="modify", rule_id="R1")
