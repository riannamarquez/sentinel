"""2d: heuristic Red end to end. It starts naive, gets caught, adapts, and slips through."""
from fastapi.testclient import TestClient

from sentinel.agents.red import HeuristicRedPolicy
from sentinel.api.app import create_app
from sentinel.detector.baseline import BASELINE_V1, hop_count_rule
from sentinel.detector.score import rules_fired, score
from sentinel.fixtures import OBJECTIVE_CENTS
from sentinel.schemas import Split
from sentinel.sim.actions import ActionError, apply_actions, moved_out_cents

CONFIG = {"seed": 7, "account_count": 40, "holdout_benign_n": 40, "holdout_attack_copies": 2}


def client_for(tmp_path, name="app.db"):
    return TestClient(create_app(str(tmp_path / name), red_policy=HeuristicRedPolicy()))


def red_run(client, lab):
    response = client.post(f"/labs/{lab}/red-runs", json={})
    assert response.status_code == 201, response.text
    return response.json()


def assert_adapted_and_bypassed(run):
    assert run["bypass"] is not None, run["history"]
    assert run["turns"] <= 4
    turn1 = [a for a in run["history"] if a["turn"] == 1]
    assert turn1 and all(a["rules_fired"] for a in turn1)       # turn 1 is always caught
    assert run["turns"] >= 2                                     # so the bypass came from adapting
    assert run["bypass"]["moved_cents"] >= OBJECTIVE_CENTS


def approve_round(client, lab, run):
    """Blue (stub: golden R4 patch) -> evaluate -> approve, so the lab moves to v2."""
    patches = client.post(f"/labs/{lab}/patches",
                          json={"run_id": run["run_id"], "bypass_id": run["bypass"]["bypass_id"]}).json()
    patch_id = next(p["patch"]["patch_id"] for p in patches["patches"] if p["valid"])
    report = client.post(f"/labs/{lab}/evaluations", json={"run_id": run["run_id"], "patch_id": patch_id}).json()
    decision = client.post(f"/labs/{lab}/approvals", json={"report_id": report["report_id"], "decision": "approve"})
    assert decision.status_code == 200, decision.text
    assert decision.json()["active_version"] == 2


def test_heuristic_red_bypasses_v1(tmp_path):
    with client_for(tmp_path) as client:
        lab = client.post("/labs", json=CONFIG).json()["lab_id"]
        assert_adapted_and_bypassed(red_run(client, lab))


def test_heuristic_red_bypasses_v2_after_blue_patch(tmp_path):
    with client_for(tmp_path) as client:
        lab = client.post("/labs", json=CONFIG).json()["lab_id"]
        approve_round(client, lab, red_run(client, lab))
        second = red_run(client, lab)
        assert_adapted_and_bypassed(second)
        assert "R4" in second["history"][0]["rules_fired"]      # v2's new rule is part of what it learned from


def test_same_seed_gives_identical_history(tmp_path):
    histories = []
    for name in ("a.db", "b.db"):
        with client_for(tmp_path, name) as client:
            lab = client.post("/labs", json=CONFIG).json()["lab_id"]
            histories.append(red_run(client, lab)["history"])
    assert histories[0] == histories[1]


def play(rules, max_turns=4):
    """The red-run loop without the API, for rule sets the API can't easily build."""
    policy, history = HeuristicRedPolicy(), []
    from sentinel.agents.red import Attempt
    from sentinel.detector.explain import near_misses
    for turn in range(1, max_turns + 1):
        for i, c in enumerate(policy.propose(objective_cents=OBJECTIVE_CENTS, rules=rules, turn=turn,
                                             history=history, seed=7, run_id="run-e2e")):
            try:
                s = apply_actions(scenario_id=f"e2e.t{turn}.c{i}", template_id=c.template_id, seed=7,
                                  split=Split.SEARCH, start_ts=c.start_ts, source_account_id=c.source_account_id,
                                  funding_cents=c.funding_cents, actions=c.actions)
            except ActionError:
                continue
            if not score(s, rules).alert and moved_out_cents(s) >= OBJECTIVE_CENTS:
                return turn
            history.append(Attempt(turn=turn, recipe=c.recipe, rules_fired=sorted(rules_fired(s, rules)),
                                   moved_cents=moved_out_cents(s), near_misses=near_misses(s, rules)))
    return None


def test_red_reacts_to_features_not_rule_names():
    """Blue will add rules with new ids. Renaming R4 to R9 must not stop Red from getting around it."""
    renamed = BASELINE_V1 + [hop_count_rule(rule_id="R9")]
    assert play(BASELINE_V1 + [hop_count_rule()]) is not None
    turn = play(renamed)
    assert turn is not None and 2 <= turn <= 4