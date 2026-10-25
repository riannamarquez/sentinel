""""What Blue missed" breakdown: contract fixture, route, and the pure builder."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sentinel.agents import blue
from sentinel.agents.red import FixtureRedPolicy
from sentinel.api.app import create_app
from sentinel.api.breakdown import (
    PATTERN_LABELS, SEGMENT_LABELS, Breakdown, PatternResult, build_breakdown, pattern_label, segment_label,
)
from sentinel.detector.baseline import BASELINE_V1, hop_count_rule
from sentinel.fixtures import FIXTURE_DIR, load_golden_patch
from sentinel.scenarios import factory
from sentinel.schemas import Split

EXAMPLE = FIXTURE_DIR / "breakdown_example.json"
V2 = BASELINE_V1 + [hop_count_rule()]


@pytest.fixture(scope="module")
def holdout():
    return factory.build_splits(7, 500, 8)[Split.FINAL_HOLDOUT]   # default BankConfig sizes, seed 7


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_MODE", "fixture")
    monkeypatch.setattr(blue, "propose", lambda bypass, rules, base_version, **kw:
                        [load_golden_patch().model_copy(update={"base_version": base_version})])
    with TestClient(create_app(str(tmp_path / "app.db"), red_policy=FixtureRedPolicy())) as c:
        yield c


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def evaluated_round(client) -> tuple[str, str]:
    """One round to a report on a default lab (seed 7), Blue stubbed to the golden R4 patch."""
    lab_id = ok(client.post("/labs", json={"seed": 7}), 201)["lab_id"]
    red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
    patches = ok(client.post(f"/labs/{lab_id}/patches",
                             json={"run_id": red["run_id"], "bypass_id": red["bypass"]["bypass_id"]}), 201)
    report = ok(client.post(f"/labs/{lab_id}/evaluations",
                            json={"run_id": red["run_id"], "patch_id": patches["patches"][0]["patch"]["patch_id"]}),
                201)
    return lab_id, report["report_id"]


def test_example_fixture_validates():
    Breakdown.model_validate_json(EXAMPLE.read_text())


def test_route_matches_the_example(client):
    lab_id, report_id = evaluated_round(client)
    assert ok(client.get(f"/labs/{lab_id}/reports/{report_id}/breakdown")) == json.loads(EXAMPLE.read_text())


def test_route_404s(client):
    lab_id, report_id = evaluated_round(client)
    other_lab = ok(client.post("/labs", json={"seed": 7}), 201)["lab_id"]
    assert client.get(f"/labs/{other_lab}/reports/{report_id}/breakdown").status_code == 404
    assert client.get(f"/labs/{lab_id}/reports/rep-999999/breakdown").status_code == 404


def test_builder_on_a_hand_picked_holdout(holdout):
    pick = [next(s for s in holdout if s.template_id == t) for t in ("fast_ring", "slow_long_hold", "salaried")]
    b = build_breakdown(pick, BASELINE_V1, V2, report_id="rep-x", run_id="run-x",
                        baseline_version=1, candidate_version=2)
    assert (b.attacks.total, b.attacks.caught_before, b.attacks.caught, b.attacks.missed) == (2, 1, 1, 1)
    ring, hold = b.patterns
    assert (ring.pattern, ring.caught, ring.missed, ring.why_missed) == ("fast_ring", 1, 0, [])
    assert (hold.pattern, hold.caught, hold.missed) == ("slow_long_hold", 0, 1)
    assert [(w.rule_id, w.reason, w.count) for w in hold.why_missed] == [
        ("R4", "hop count reached 3; rule needs ≥ 4", 1)]
    fa = b.false_alarms
    assert (fa.benign_total, fa.flagged_before, fa.flagged) == (1, 0, 0)
    assert [(c.segment, c.total, c.flagged, c.by_rule) for c in fa.by_customer_type] == [("salaried", 1, 0, {})]


def test_every_holdout_template_has_a_label(holdout):
    assert {s.template_id for s in holdout if s.malicious_label} <= set(PATTERN_LABELS)
    assert {s.template_id for s in holdout if not s.malicious_label} <= set(SEGMENT_LABELS)
    assert pattern_label("brand_new") == "brand_new" and segment_label("brand_new") == "brand_new"


def test_counts_must_add_up():
    with pytest.raises(ValidationError, match="caught \\+ missed"):
        PatternResult(pattern="p", label="p", total=3, caught_before=0, caught=1, missed=1, why_missed=[])
