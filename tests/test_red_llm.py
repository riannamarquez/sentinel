"""Step 5: what LLM Red is allowed to see, and that it degrades safely (no API key needed)."""
import json

from fastapi.testclient import TestClient

from sentinel.agents.red import HeuristicRedPolicy, LLMRedPolicy, red_prompt_inputs
from sentinel.api.app import create_app
from sentinel.detector.baseline import BASELINE_V1, hop_count_rule
from sentinel.fixtures import OBJECTIVE_CENTS
from sentinel.llm.adapter import Adapter, ResponseStore

CONFIG = {"seed": 7, "account_count": 40, "holdout_benign_n": 40, "holdout_attack_copies": 2}
V2 = BASELINE_V1 + [hop_count_rule()]

# Allowlists: anything new that reaches the LLM has to be added here on purpose.
INPUT_KEYS = {"objective_cents", "turn", "max_turns", "forward_pct", "rules", "history", "knobs", "constraints"}
ATTEMPT_KEYS = {"turn", "recipe", "rules_fired", "moved_cents", "near_misses"}
NEAR_MISS_KEYS = {"rule_id", "feature_key", "operator", "threshold", "closest_value", "gap", "window_hours"}
# Backstop: words that only appear if labels, splits, IDs, seeds or holdout data slipped in.
FORBIDDEN = ["ground_truth", "malicious", "benign", "final_holdout", "regression", "search",
             "scenario", "template", "seed", "lab-", "run-", "holdout"]   # not "split": the n_splits knob is fine


def recipe(**knobs):
    return {"n_mules": 2, "hold_hours": 25, "n_splits": 1, "new_device": False, "funding_cents": 450_000, **knobs}


def recording_adapter(tmp_path, reply):
    """A fake LLM: records every request and answers with reply(request)."""
    sent = []
    def transport(request):
        sent.append(request)
        return reply(request)
    return Adapter(transport, ResponseStore(tmp_path / "llm.db"), sleep=lambda _: None), sent


def red_run(tmp_path, policy, name="app.db"):
    with TestClient(create_app(str(tmp_path / name), red_policy=policy)) as client:
        lab = client.post("/labs", json=CONFIG).json()["lab_id"]
        response = client.post(f"/labs/{lab}/red-runs", json={})
        assert response.status_code == 201, response.text
        return response.json()


def real_history(tmp_path):
    """Turn-1 attempts from a real heuristic run, rebuilt the way the policy receives them."""
    from sentinel.agents.red import Attempt
    run = red_run(tmp_path, HeuristicRedPolicy(), "history.db")
    return [Attempt.model_validate(a) for a in run["history"] if a["turn"] == 1]


def test_inputs_are_exactly_the_allowlisted_fields(tmp_path):
    inputs = red_prompt_inputs(OBJECTIVE_CENTS, V2, 2, real_history(tmp_path))
    assert set(inputs) == INPUT_KEYS
    assert inputs["history"], "the check is only meaningful with real history in it"
    for attempt in inputs["history"]:
        assert set(attempt) == ATTEMPT_KEYS
        for nm in attempt["near_misses"]:
            assert set(nm) == NEAR_MISS_KEYS


def test_inputs_contain_no_labels_splits_ids_or_seeds(tmp_path):
    text = json.dumps(red_prompt_inputs(OBJECTIVE_CENTS, V2, 2, real_history(tmp_path))).lower()
    assert [w for w in FORBIDDEN if w in text] == []


def test_every_knob_explains_itself():
    knobs = red_prompt_inputs(OBJECTIVE_CENTS, V2, 1, [])["knobs"]
    assert all(k.get("meaning") for k in knobs.values())


def test_what_reaches_the_llm_is_red_prompt_plus_safe_inputs(tmp_path):
    adapter, sent = recording_adapter(tmp_path, lambda r: {"recipes": [recipe()]})
    red_run(tmp_path, LLMRedPolicy(adapter))
    assert sent, "the LLM was never called"
    for request in sent:
        assert request["role"] == "red"
        assert request["instructions"].startswith("You are Red")
        assert set(request["inputs"]) == INPUT_KEYS
        text = json.dumps(request["inputs"]).lower()
        assert [w for w in FORBIDDEN if w in text] == []


def test_llm_recipe_can_bypass(tmp_path):
    adapter, _ = recording_adapter(tmp_path, lambda r: {"recipes": [recipe()]})
    run = red_run(tmp_path, LLMRedPolicy(adapter))
    assert run["bypass"] is not None and run["turns"] == 1


def test_broken_llm_falls_back_to_heuristic(tmp_path):
    def down(request):
        raise OSError("provider unreachable")
    run = red_run(tmp_path, LLMRedPolicy(Adapter(down, ResponseStore(tmp_path / "llm.db"), sleep=lambda _: None)))
    assert run["bypass"] is not None          # the heuristic still finds one
    assert run["history"][0]["recipe"]["hold_hours"] == 1   # turn 1 was the heuristic's naive recipe


def test_invalid_llm_output_falls_back_to_heuristic(tmp_path):
    adapter, sent = recording_adapter(tmp_path, lambda r: {"recipes": [recipe(n_mules=99)]})
    run = red_run(tmp_path, LLMRedPolicy(adapter))
    assert run["bypass"] is not None
    assert len(sent) >= 3                     # the adapter retried before giving up


def test_llm_repeating_history_falls_back(tmp_path):
    naive = recipe(hold_hours=1, funding_cents=800_000)   # caught on turn 1, then repeated forever
    adapter, _ = recording_adapter(tmp_path, lambda r: {"recipes": [naive]})
    run = red_run(tmp_path, LLMRedPolicy(adapter))
    assert run["bypass"] is not None
    assert run["history"][-1]["recipe"] != naive