"""Walking skeleton: a full round through the API, plus the 409 paths (design-v2 §3, §7)."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from sentinel.agents import blue
from sentinel.api.app import create_app
from sentinel.api.states import ALLOWED_TRANSITIONS, TERMINAL, RunState
from sentinel.schemas import Condition, PatchOperation, RulePatch

CONFIG = {"seed": 7, "account_count": 40, "holdout_benign_n": 40, "holdout_attack_copies": 2}
ROUND_STATES = [
    "initialize_lab", "generate_world", "baseline_score", "red_proposes", "validate_actions", "run_simulation",
    "measure_outcome", "blue_proposes", "validate_patch", "evaluate_holdouts", "apply_gates", "await_human",
    "apply_new_version", "rechallenge", "complete",
]


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sentinel.db"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(str(db_path))) as c:
        yield c


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def new_lab(client) -> str:
    return ok(client.post("/labs", json=CONFIG), 201)["lab_id"]


def to_await_human(client, lab_id: str) -> tuple[str, dict]:
    red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
    assert red["state"] == "measure_outcome" and red["bypass"] is not None
    run_id = red["run_id"]
    patches = ok(client.post(f"/labs/{lab_id}/patches",
                             json={"run_id": run_id, "bypass_id": red["bypass"]["bypass_id"]}), 201)
    assert patches["state"] == "validate_patch" and patches["patches"][0]["valid"]
    report = ok(client.post(f"/labs/{lab_id}/evaluations",
                            json={"run_id": run_id, "patch_id": patches["patches"][0]["patch"]["patch_id"]}), 201)
    return run_id, report


def test_full_round_reaches_detector_v2(client):
    created = ok(client.post("/labs", json=CONFIG), 201)
    lab_id = created["lab_id"]
    assert created["active_detector_version"] == 1 and created["world"]["accounts"] >= 40

    baseline = ok(client.post(f"/labs/{lab_id}/baseline"))
    assert [r["alert"] for r in baseline["results"]] == [True, False, False]  # ring caught, slow + legit not

    run_id, report = to_await_human(client, lab_id)
    assert report["eligible_for_approval"] and report["baseline_version"] == 1
    assert {g["name"] for g in report["gate_results"]} == {
        "schema_valid", "fpr_budget", "regression_no_loss", "regression_benign", "holdout_recall_gain"}
    assert report["recall_after"] > report["recall_before"]

    decision = ok(client.post(f"/labs/{lab_id}/approvals", json={"report_id": report["report_id"],
                                                                  "decision": "approve"}))
    assert decision["version_created"] == 2 and decision["active_version"] == 2
    assert decision["rechallenge"]["alert"] is True     # a fresh slow variant is now caught

    lab = ok(client.get(f"/labs/{lab_id}"))
    assert lab["active_version"] == 2
    assert [(v["version"], v["parent_version"]) for v in lab["versions"]] == [(1, None), (2, 1)]
    assert [r["rule_id"] for r in lab["versions"][1]["rules"]] == ["R1", "R2", "R3", "R4"]

    run = ok(client.get(f"/runs/{run_id}"))
    assert run["state"] == "complete"
    entered = [e["action"].removeprefix("enter:") for e in run["events"] if e["action"].startswith("enter:")]
    assert entered == ROUND_STATES
    approve = [e for e in run["events"] if e["action"] == "approve"]
    assert len(approve) == 1 and approve[0]["actor"] == "human"
    assert (approve[0]["version_before"], approve[0]["version_after"]) == (1, 2)

    # The next round attacks v2: the same slow variant is now caught, so Red finds no bypass.
    again = ok(client.post(f"/labs/{lab_id}/red-runs", json={"max_turns": 2}), 201)
    assert again["state"] == "no_bypass_found" and again["bypass"] is None


def test_approving_a_stale_report_returns_409(client):
    lab_id = new_lab(client)
    _, first = to_await_human(client, lab_id)
    run2, second = to_await_human(client, lab_id)          # both evaluated against v1
    ok(client.post(f"/labs/{lab_id}/approvals", json={"report_id": first["report_id"], "decision": "approve"}))
    stale = client.post(f"/labs/{lab_id}/approvals", json={"report_id": second["report_id"], "decision": "approve"})
    assert stale.status_code == 409 and stale.json()["reason"] == "stale_base_version"
    assert ok(client.get(f"/labs/{lab_id}"))["active_version"] == 2
    assert ok(client.get(f"/runs/{run2}"))["state"] == "await_human"   # still decidable: it can be rejected
    ok(client.post(f"/labs/{lab_id}/approvals", json={"report_id": second["report_id"], "decision": "reject"}))


def test_approval_is_idempotent_and_cannot_flip(client):
    lab_id = new_lab(client)
    _, report = to_await_human(client, lab_id)
    body = {"report_id": report["report_id"], "decision": "approve"}
    first = ok(client.post(f"/labs/{lab_id}/approvals", json=body))
    again = ok(client.post(f"/labs/{lab_id}/approvals", json=body))
    assert again["version_created"] == first["version_created"] == 2
    flip = client.post(f"/labs/{lab_id}/approvals", json={**body, "decision": "reject"})
    assert flip.status_code == 409 and flip.json()["reason"] == "already_decided"
    assert len(ok(client.get(f"/labs/{lab_id}"))["versions"]) == 2


def test_failed_gates_block_approval_server_side(client, monkeypatch):
    greedy = RulePatch(patch_id="greedy", base_version=1, operation=PatchOperation.ADD,
                       all_of=[Condition(feature_key="transfer_amount", operator=">=", threshold=1)])
    monkeypatch.setattr(blue, "propose", lambda bypass, rules, base_version: [greedy])
    lab_id = new_lab(client)
    run_id, report = to_await_human(client, lab_id)
    assert not report["eligible_for_approval"]
    denied = client.post(f"/labs/{lab_id}/approvals", json={"report_id": report["report_id"], "decision": "approve"})
    assert denied.status_code == 409 and denied.json()["reason"] == "gates_failed"
    assert ok(client.get(f"/labs/{lab_id}"))["active_version"] == 1
    rejected = ok(client.post(f"/labs/{lab_id}/approvals", json={"report_id": report["report_id"],
                                                                  "decision": "reject"}))
    assert rejected["version_created"] is None and rejected["rechallenge"]["alert"] is False
    assert ok(client.get(f"/runs/{run_id}"))["state"] == "complete"


def test_out_of_order_steps_return_409(client):
    lab_id = new_lab(client)
    red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
    early = client.post(f"/labs/{lab_id}/evaluations", json={"run_id": red["run_id"], "patch_id": "golden-hop-count"})
    assert early.status_code == 409 and early.json()["reason"] == "invalid_state"
    other_lab = new_lab(client)
    foreign = client.post(f"/labs/{other_lab}/patches",
                          json={"run_id": red["run_id"], "bypass_id": red["bypass"]["bypass_id"]})
    assert foreign.status_code == 404                     # a run from another lab is not visible here


def test_patch_on_the_wrong_base_version_is_rejected_before_evaluation(client, monkeypatch):
    from sentinel.fixtures import load_golden_patch
    monkeypatch.setattr(blue, "propose", lambda bypass, rules, base_version:
                        [load_golden_patch().model_copy(update={"base_version": 9})])
    lab_id = new_lab(client)
    red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
    out = ok(client.post(f"/labs/{lab_id}/patches",
                         json={"run_id": red["run_id"], "bypass_id": red["bypass"]["bypass_id"]}), 201)
    assert out["state"] == "failed" and "based on v9" in out["patches"][0]["error"]


def test_request_bounds(client):
    assert client.post("/labs", json={**CONFIG, "account_count": 0}).status_code == 422
    lab_id = new_lab(client)
    assert client.post(f"/labs/{lab_id}/red-runs", json={"max_turns": 5}).status_code == 422
    assert client.post("/labs/lab-9999/red-runs", json={}).status_code == 404


def test_store_uses_wal_and_audit_is_append_only(client, db_path):
    new_lab(client)
    assert ok(client.get("/healthz"))["journal_mode"] == "wal"
    db = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE audit_events SET actor = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM audit_events")
    with pytest.raises(sqlite3.IntegrityError, match="never updated"):
        db.execute("UPDATE detector_versions SET rules_json = '[]'")


def test_state_machine_table_is_well_formed():
    for state in RunState:
        exits = ALLOWED_TRANSITIONS[state]
        if state in TERMINAL:
            assert not exits
        else:
            assert {RunState.FAILED, RunState.CANCELLED} <= exits
    path = [RunState(s) for s in ROUND_STATES]
    for a, b in zip(path, path[1:]):
        assert b in ALLOWED_TRANSITIONS[a], (a, b)
    assert len([s for s in RunState if s not in {RunState.NO_BYPASS_FOUND, RunState.FAILED, RunState.CANCELLED}]) == 16
