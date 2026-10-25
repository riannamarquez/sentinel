"""POST /labs/{lab_id}/runs/{run_id}/replay-bypass: Red's bypass re-scored under base, candidate and active rules."""
import pytest
from fastapi.testclient import TestClient

from sentinel.agents.red import FixtureRedPolicy, HeuristicRedPolicy
from sentinel.api.app import create_app

CONFIG = {"seed": 7, "account_count": 40, "holdout_benign_n": 40, "holdout_attack_copies": 2}


class NoBypassRed:
    """A Red that never proposes anything, so its run ends without a bypass."""
    def propose(self, **_):
        return []


def make_client(tmp_path, policy, db_name="sentinel.db"):
    return TestClient(create_app(str(tmp_path / db_name), red_policy=policy))


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def replay(client, lab_id, run_id, **body):
    return client.post(f"/labs/{lab_id}/runs/{run_id}/replay-bypass", json=body)


def red_and_patch(client):
    lab_id = ok(client.post("/labs", json=CONFIG), 201)["lab_id"]
    red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
    run_id, bypass = red["run_id"], red["bypass"]
    patches = ok(client.post(f"/labs/{lab_id}/patches", json={"run_id": run_id, "bypass_id": bypass["bypass_id"]}), 201)
    return lab_id, run_id, bypass, patches["patches"][0]["patch"]["patch_id"]


@pytest.mark.parametrize("policy", [FixtureRedPolicy, HeuristicRedPolicy], ids=["fixture_red", "adaptive_red"])
def test_seed_7_bypass_slips_past_base_and_is_caught_by_candidate_r4(tmp_path, policy):
    with make_client(tmp_path, policy()) as client:
        lab_id, run_id, bypass, patch_id = red_and_patch(client)
        txn_ids = [t["transaction_id"] for t in bypass["scenario"]["transactions"]]

        base = ok(replay(client, lab_id, run_id, rules="base"))
        assert base["alert"] is False and base["detector_version"] == 1 and base["detector_label"] == "Detector v1"
        assert base["alert_hop_index"] is None and base["alert_transaction_id"] is None
        assert [h["transaction_id"] for h in base["per_hop"]] == txn_ids
        assert not any(h["alerted"] for h in base["per_hop"])
        assert base["per_hop"][0]["scored"] is False      # money arriving from outside is never scored

        candidate = ok(replay(client, lab_id, run_id, rules="candidate"))
        assert candidate["alert"] is True and "R4" in candidate["triggered_rule_ids"]
        assert candidate["patch_id"] == patch_id and candidate["detector_version"] is None
        hop = candidate["alert_hop_index"]
        assert txn_ids[hop - 1] == candidate["alert_transaction_id"]
        assert candidate["per_hop"][hop - 1]["alerted"] and "R4" in candidate["per_hop"][hop - 1]["rule_ids"]
        assert not any(h["alerted"] for h in candidate["per_hop"][:hop - 1])   # nothing fires before the alert

        # Deterministic: repeated calls return identical bodies.
        for rules in ("base", "candidate", "active"):
            first = replay(client, lab_id, run_id, rules=rules).json()
            assert all(replay(client, lab_id, run_id, rules=rules).json() == first for _ in range(3))


def test_candidate_takes_the_approved_version_and_matches_active(tmp_path):
    with make_client(tmp_path, FixtureRedPolicy()) as client:
        lab_id, run_id, _, patch_id = red_and_patch(client)
        report = ok(client.post(f"/labs/{lab_id}/evaluations", json={"run_id": run_id, "patch_id": patch_id}), 201)
        before = ok(replay(client, lab_id, run_id, rules="active"))
        assert before["alert"] is False and before["detector_version"] == 1

        ok(client.post(f"/labs/{lab_id}/approvals", json={"report_id": report["report_id"], "decision": "approve"}))
        candidate = ok(replay(client, lab_id, run_id, rules="candidate"))
        active = ok(replay(client, lab_id, run_id, rules="active"))
        assert candidate["detector_version"] == 2 and candidate["detector_label"] == "Detector v2"
        assert active["detector_version"] == 2
        assert {k: v for k, v in candidate.items() if k not in ("rules", "patch_id")} == \
               {k: v for k, v in active.items() if k not in ("rules", "patch_id")}


def test_replay_errors_have_clear_codes(tmp_path):
    with make_client(tmp_path, FixtureRedPolicy()) as client:
        lab_id = ok(client.post("/labs", json=CONFIG), 201)["lab_id"]
        red = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)
        run_id = red["run_id"]

        missing_run = replay(client, lab_id, "run-999999", rules="base")
        assert missing_run.status_code == 404 and missing_run.json()["reason"] == "not_found"
        other_lab = ok(client.post("/labs", json=CONFIG), 201)["lab_id"]
        assert replay(client, other_lab, run_id, rules="base").status_code == 404   # run belongs to another lab

        no_patch = replay(client, lab_id, run_id, rules="candidate")
        assert no_patch.status_code == 409 and no_patch.json()["reason"] == "no_valid_patch"
        assert replay(client, lab_id, run_id, rules="candidate", patch_id="nope").status_code == 404
        assert replay(client, lab_id, run_id, rules="sideways").status_code == 422

    with make_client(tmp_path, NoBypassRed(), "no-bypass.db") as client:
        lab_id = ok(client.post("/labs", json=CONFIG), 201)["lab_id"]
        run_id = ok(client.post(f"/labs/{lab_id}/red-runs", json={}), 201)["run_id"]
        no_bypass = replay(client, lab_id, run_id, rules="base")
        assert no_bypass.status_code == 409 and no_bypass.json()["reason"] == "no_bypass"
