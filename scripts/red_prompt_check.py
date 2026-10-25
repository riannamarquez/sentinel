"""Hand-test Red's LLM prompt (Step 4) without wiring anything up.

1. uv run python scripts/red_prompt_check.py prompt [--version 2]
   Plays the naive turn 1 against the detector, then writes red_prompt_turn2.txt:
   the prompt, turn 2's real inputs, and the response schema. Paste it into Gemini or another chat.
2. Save the model's JSON reply to a file, e.g. red_reply.json, then:
   uv run python scripts/red_prompt_check.py check red_reply.json [--version 2]
   Validates the reply against RedProposal and simulates every recipe against the same detector.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from sentinel.agents.red import (NAIVE, Attempt, RedProposal, _reaches_objective, recipe_to_candidate,
                                 red_prompt_inputs)
from sentinel.detector.baseline import BASELINE_V1, hop_count_rule
from sentinel.detector.explain import describe, near_misses
from sentinel.detector.score import rules_fired, score
from sentinel.fixtures import OBJECTIVE_CENTS
from sentinel.schemas import Split
from sentinel.sim.actions import ActionError, apply_actions, moved_out_cents
from sentinel.sim.rng import rng_for

PROMPT = Path(__file__).resolve().parent.parent / "sentinel" / "llm" / "prompts" / "red_v1.md"
SEED, RUN_ID = 7, "run-handtest"


def rules_for(version: int):
    return BASELINE_V1 if version == 1 else BASELINE_V1 + [hop_count_rule()]


def simulate(recipe, rules, turn, i):
    c = recipe_to_candidate(recipe, rng_for(SEED, RUN_ID, "red", turn, i))
    return apply_actions(scenario_id=f"{RUN_ID}.t{turn}.c{i}", template_id=c.template_id, seed=SEED,
                         split=Split.SEARCH, start_ts=c.start_ts, source_account_id=c.source_account_id,
                         funding_cents=c.funding_cents, actions=c.actions)


def turn_one(rules) -> list[Attempt]:
    s = simulate(NAIVE, rules, 1, 0)
    return [Attempt(turn=1, recipe=NAIVE, rules_fired=sorted(rules_fired(s, rules)),
                    moved_cents=moved_out_cents(s), near_misses=near_misses(s, rules))]


def cmd_prompt(version: int) -> None:
    rules = rules_for(version)
    history = turn_one(rules)
    print(f"Turn 1 (naive) on v{version}: caught by {history[0].rules_fired}")
    for nm in history[0].near_misses:
        print(f"  near miss {nm.rule_id}: {describe(nm)}")
    text = (PROMPT.read_text().strip()
            + "\n\nInputs:\n" + json.dumps(red_prompt_inputs(OBJECTIVE_CENTS, rules, 2, history), indent=1)
            + "\n\nResponse schema:\n" + json.dumps(RedProposal.model_json_schema(), indent=1))
    out = Path("red_prompt_turn2.txt")
    out.write_text(text, encoding="utf-8")
    print(f"\nWrote {out} ({len(text):,} characters). Paste all of it into the chat.")


def cmd_check(path: str, version: int) -> None:
    rules = rules_for(version)
    raw = Path(path).read_text(encoding="utf-8").strip().removeprefix("```json").removesuffix("```").strip()
    try:
        proposal = RedProposal.model_validate_json(raw)
    except ValidationError as e:
        print("INVALID reply. The adapter would retry, then fall back to the heuristic:\n", e)
        return
    tried = {a.recipe for a in turn_one(rules)}
    print(f"Valid: {len(proposal.recipes)} recipe(s), checked against v{version}\n")
    for i, r in enumerate(proposal.recipes):
        knobs = f"{r.n_mules} mules, {r.hold_hours}h holds, {r.n_splits} splits, new_device={r.new_device}, ${r.funding_cents / 100:,.0f}"
        if r in tried:
            print(f"{i + 1}. {knobs}\n   SKIPPED: repeats turn 1")
            continue
        if not _reaches_objective(r, OBJECTIVE_CENTS):
            print(f"{i + 1}. {knobs}\n   SKIPPED: can't reach the objective after mule cuts")
            continue
        try:
            s = simulate(r, rules, 2, i)
        except ActionError as e:
            print(f"{i + 1}. {knobs}\n   DROPPED by the simulator: {e}")
            continue
        alert, moved = score(s, rules).alert, moved_out_cents(s)
        verdict = "BYPASS" if not alert and moved >= OBJECTIVE_CENTS else "caught" if alert else "too little moved"
        print(f"{i + 1}. {knobs}\n   {verdict}: rules fired {sorted(rules_fired(s, rules))}, moved ${moved / 100:,.0f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["prompt", "check"])
    p.add_argument("reply", nargs="?", help="file with the model's JSON reply (for check)")
    p.add_argument("--version", type=int, choices=[1, 2], default=1, help="detector v1, or v2 (v1 + R4)")
    a = p.parse_args()
    if a.command == "prompt":
        cmd_prompt(a.version)
    elif not a.reply:
        p.error("check needs the reply file")
    else:
        cmd_check(a.reply, a.version)