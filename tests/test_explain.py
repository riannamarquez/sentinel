"""Near misses (2c): how close each rule that did not fire came, and the sentence Red and analysts see."""
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from sentinel.agents.red import HeuristicRedPolicy
from sentinel.api.app import create_app
from sentinel.detector.baseline import BASELINE_V1, hop_count_condition, hop_count_rule
from sentinel.detector.explain import FEATURE_KIND, FEATURE_LABELS, NearMiss, describe, gap, near_misses
from sentinel.detector.score import diagnose
from sentinel.scenarios import factory
from sentinel.schemas import Condition, FeatureKey, Rule, Split

V2 = BASELINE_V1 + [hop_count_rule()]


@pytest.fixture(scope="module")
def holdout():
    return factory.build_splits(7, 500, 8)[Split.FINAL_HOLDOUT]


def first(holdout, template_id):
    return next(s for s in holdout if s.template_id == template_id)


def test_gap():
    assert gap(">=", 4, 3) == 0.25
    assert gap(">=", 4, 5) == 0
    assert gap("<", 2, 3) == 0.5
    assert gap("<", 2, 1) == 0
    assert gap(">", 4, 4) > 0          # exactly on a strict threshold still misses
    assert gap("<", 0, 3) == 3         # threshold 0 falls back to the raw distance


@pytest.mark.parametrize("template_id", ["slow_long_hold", "short_chain"])
def test_r4_is_the_nearest_miss(holdout, template_id):
    misses = near_misses(first(holdout, template_id), V2)
    r4 = next(nm for nm in misses if nm.rule_id == "R4")
    assert (r4.closest_value, r4.threshold, r4.gap) == (3, 4, 0.25)
    assert min(misses, key=lambda nm: nm.gap) == r4


def test_rules_that_fired_are_excluded(holdout):
    assert "R4" not in {nm.rule_id for nm in near_misses(first(holdout, "slow_chain_3"), V2)}


def test_describe(holdout):
    assert [(nm.rule_id, describe(nm)) for nm in near_misses(first(holdout, "slow_long_hold"), V2)] == [
        ("R1", "transfers sent within 1h reached 1; rule needs ≥ 5"),
        ("R2", "share of incoming money passed on within 6h reached 0%; rule needs ≥ 90%"),
        ("R3", "sent from a new device: no; rule needs yes"),
        ("R4", "hop count reached 3; rule needs ≥ 4"),
    ]
    for key in get_args(FeatureKey):
        assert key in FEATURE_LABELS and key in FEATURE_KIND


def test_only_a_condition_that_never_fired_is_the_near_miss(holdout):
    s = first(holdout, "slow_long_hold")
    rule = Rule(rule_id="R9", all_of=[Condition(feature_key="transfer_amount", operator=">=", threshold=100_000),
                                      hop_count_condition(4)])
    fires, blocks = diagnose(s, [rule])[0].conditions
    assert not fires.held and blocks.held           # the amount condition fired; the hop count never did
    assert gap(fires.operator, fires.threshold, fires.closest_value) == 0
    [nm] = near_misses(s, [rule])
    assert nm.feature_key == "short_hold_hop_count" and nm.gap == 0.25


def test_near_miss_carries_no_ground_truth():
    leaks = {"ground_truth_label", "malicious_label", "split", "scenario_id", "template_id"}
    assert not leaks & set(NearMiss.model_fields)


def test_red_history_carries_near_misses(tmp_path):
    config = {"seed": 7, "account_count": 40, "holdout_benign_n": 40, "holdout_attack_copies": 2}
    with TestClient(create_app(str(tmp_path / "sentinel.db"), red_policy=HeuristicRedPolicy())) as client:
        lab_id = client.post("/labs", json=config).json()["lab_id"]
        red = client.post(f"/labs/{lab_id}/red-runs", json={})
        assert red.status_code == 201, red.text
    rule_ids = {nm["rule_id"] for nm in red.json()["history"][0]["near_misses"]}
    assert {"R1", "R3"} <= rule_ids and "R2" not in rule_ids   # turn 1 is caught by R2 on v1
