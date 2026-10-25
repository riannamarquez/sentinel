"""Pre-demo check: play one round against a running server exactly as the frontend does, and say
whether Red and Blue really used the LLM.

    uv run python scripts/demo_check.py [--base http://127.0.0.1:8000] [--seed 7] [--accounts 200]

Calls, in the frontend's order: POST /labs, /baseline, /red-runs {}, /patches (Blue), then
/evaluations on Blue's first valid patch. Prints Red's turns, Blue's rule, the scorecard and the
timings, then PASS or WARN. Exit codes: 0 PASS, 1 WARN, 2 the round could not finish.
Standard library only; the API key never passes through this script.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

SLOW_SECONDS = 60


def fail(message: str):
    print("FAIL: " + message, file=sys.stderr)
    sys.exit(2)


def call(base: str, path: str, body: dict | None = None):
    request = urllib.request.Request(
        base + path, method="GET" if body is None else "POST",
        data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        fail(f"{path} returned HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        fail(f"can't reach {base} ({e.reason}). Is the server running?")


def timed(fn):
    start = time.monotonic()
    result = fn()
    return result, time.monotonic() - start


def dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--accounts", type=int, default=200)
    args = parser.parse_args()
    base, warnings = args.base.rstrip("/"), []

    health = call(base, "/healthz")
    print(f"Server: llm={health['llm']}  red_policy={health.get('red_policy', '?')}  "
          f"blue_source={health.get('blue_source', '?')}  model={health.get('llm_model')}")

    lab = call(base, "/labs", {"seed": args.seed, "account_count": args.accounts})["lab_id"]
    call(base, f"/labs/{lab}/baseline", {})

    red, red_s = timed(lambda: call(base, f"/labs/{lab}/red-runs", {}))
    print(f"\nRed run {red['run_id']}: {red['turns']} turn(s) in {red_s:.1f}s, "
          f"{'bypass found' if red['bypass'] else 'no bypass'}")
    objective = red["bypass"]["objective_cents"] if red["bypass"] else None
    sources = {s["turn"]: s for s in red.get("turn_sources", [])}
    if not sources:
        warnings.append("server did not report Red's policy per turn")
    for turn in range(1, red["turns"] + 1):
        source = sources.get(turn, {"policy": "unknown"})
        line = f"  Turn {turn}: policy={source['policy']}"
        if source["policy"] == "heuristic_fallback":
            line += f"  reason={source.get('reason')} ({source.get('detail')})"
            warnings.append(f"Red turn {turn} fell back to the heuristic ({source.get('reason')})")
        elif source["policy"] != "llm":
            warnings.append(f"Red turn {turn} used the {source['policy']} policy, not the LLM")
        print(line)
        for a in (a for a in red["history"] if a["turn"] == turn):
            r = a["recipe"]
            bypassed = not a["rules_fired"] and (objective is None or a["moved_cents"] >= objective)
            print(f"    {r['n_mules']} mules, {r['hold_hours']}h holds, {r['n_splits']} splits, "
                  f"new_device={r['new_device']}, funding {dollars(r['funding_cents'])} -> "
                  f"moved {dollars(a['moved_cents'])}, "
                  + ("BYPASSED" if bypassed else f"caught by {', '.join(a['rules_fired']) or 'none'}"))
    if not red["bypass"]:
        warnings.append("Red found no bypass, so Blue was not asked")
        return finish(warnings, red_s, None)
    print(f"  Bypass: moved {dollars(red['bypass']['moved_cents'])} "
          f"(goal {dollars(objective)}): {red['bypass']['rationale']}")

    patches, blue_s = timed(lambda: call(base, f"/labs/{lab}/patches",
                                         {"run_id": red["run_id"], "bypass_id": red["bypass"]["bypass_id"]}))
    source = patches.get("source", "unknown")
    print(f"\nBlue: source={source}, {len(patches['patches'])} proposal(s) in {blue_s:.1f}s")
    if source not in ("llm_live", "llm_replay"):
        warnings.append(f"Blue's proposal came from {source}, not the LLM")
    for p in patches["patches"]:
        print(f"  {p['patch']['patch_id']}: {'valid' if p['valid'] else 'REJECTED: ' + str(p['error'])}")
        print("    " + json.dumps(p["patch"], sort_keys=True))
    valid = next((p["patch"]["patch_id"] for p in patches["patches"] if p["valid"]), None)
    if valid is None:
        warnings.append("Blue proposed no valid patch")
        return finish(warnings, red_s, blue_s)

    report = call(base, f"/labs/{lab}/evaluations", {"run_id": red["run_id"], "patch_id": valid})
    before, after = report["baseline_confusion"]["final_holdout"], report["candidate_confusion"]["final_holdout"]
    n_attack, n_benign = report["attack_n"], report["benign_n"]
    print(f"\nScorecard for {valid} (held-out data):")
    print(f"  Attacks caught:  {before['tp']}/{n_attack} -> {after['tp']}/{n_attack}")
    print(f"  False alarms:    {before['fp']}/{n_benign} -> {after['fp']}/{n_benign}")
    print(f"  Still missed:    {n_attack - after['tp']}/{n_attack}"
          + "".join(f"\n    {m['count']} x {m['label']}" for m in report.get("missed_breakdown") or []))
    print("  Safety checks:")
    for g in report["gate_results"]:
        detail = g["detail"] or f"{g['numerator']}/{g['denominator']}"
        print(f"    {'PASS' if g['passed'] else 'FAIL'}  {g['name']}: {detail}")
        if not g["passed"]:
            warnings.append(f"safety check {g['name']} failed")
    return finish(warnings, red_s, blue_s)


def finish(warnings: list[str], red_s: float, blue_s: float | None) -> int:
    print(f"\nTiming: Red run {red_s:.1f}s, Blue proposal " + ("not run" if blue_s is None else f"{blue_s:.1f}s"))
    for name, seconds in (("Red run", red_s), ("Blue proposal", blue_s)):
        if seconds is not None and seconds > SLOW_SECONDS:
            warnings.append(f"{name} took {seconds:.0f}s (over {SLOW_SECONDS}s)")
    if warnings:
        print("WARN: " + "; ".join(warnings))
        return 1
    print("PASS: every Red turn and Blue's proposal came from the LLM, all safety checks passed, both steps under "
          f"{SLOW_SECONDS}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
