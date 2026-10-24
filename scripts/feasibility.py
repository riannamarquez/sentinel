#!/usr/bin/env python3
"""No-LLM feasibility check for Sentinel's demo fix (design-v2 §10).

Builds the scenario factory's final holdout (seeded benign households plus hand-written hop-chain
fraud), scores it with baseline detector v1 and with v1 plus the short_hold_hop_count rule, and
checks the result against the hackathon gate. Uses the same sentinel package code as the app.

    make feasibility
    uv run python scripts/feasibility.py [--seed 7] [--k 4] [--benign 500] [--attack-copies 8]

Exit code 0 if the candidate passes the gate on --seed, 1 if it fails.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.detector.baseline import BASELINE_V1, hop_count_condition, hop_count_rule  # noqa: E402
from sentinel.detector.score import max_value, rules_fired, score  # noqa: E402
from sentinel.eval import gates  # noqa: E402
from sentinel.eval.evaluator import dataset_hash  # noqa: E402
from sentinel.scenarios.factory import final_holdout  # noqa: E402
from sentinel.schemas import Scenario  # noqa: E402
from sentinel.sim.benign import BENIGN_TEMPLATES  # noqa: E402
from sentinel.sim.fraud import ATTACK_TEMPLATES  # noqa: E402


def check_no_lookahead(s: Scenario, rules) -> None:
    """Cutting the trace at the alert time must not change the alert."""
    d = score(s, rules)
    if not d.alert:
        return
    cut = s.model_copy(update={"transactions": [t for t in s.transactions if t.timestamp <= d.first_alert_time]})
    assert score(cut, rules) == d, f"lookahead detected in {s.scenario_id}"


class Run:
    """One seed: baseline flags plus each scenario's max hop count, so any k is a set lookup."""

    def __init__(self, seed: int, benign: int, copies: int, k: int, verify: bool):
        self.scenarios = final_holdout(seed, benign, copies)
        self.base = {s.scenario_id for s in self.scenarios if score(s, BASELINE_V1).alert}
        hop = hop_count_condition()
        self.hops = {s.scenario_id: max_value(s, hop) for s in self.scenarios}
        self.attack = {s.scenario_id for s in self.scenarios if s.malicious_label}
        self.benign = {s.scenario_id for s in self.scenarios if not s.malicious_label}
        if verify:
            candidate = [*BASELINE_V1, hop_count_rule(k)]
            for s in self.scenarios:
                # The real detector run with the rule must agree with the max-hop shortcut.
                assert score(s, candidate).alert == (s.scenario_id in self.base or self.hops[s.scenario_id] >= k)
                check_no_lookahead(s, candidate)

    def candidate(self, k: int) -> set[str]:
        return self.base | {sid for sid, h in self.hops.items() if h >= k}

    def gate_results(self, k: int):
        cand = self.candidate(k)
        return [
            gates.fpr_budget(len(self.base & self.benign), len(cand & self.benign), len(self.benign)),
            gates.regression_no_loss(self.base & self.attack, cand & self.attack),
            gates.holdout_recall_gain(len(self.base & self.attack), len(cand & self.attack), len(self.attack)),
            gates.schema_valid(True, "hand-coded rule from the feature registry"),
        ]

    def passed(self, k: int) -> bool:
        return all(g.passed for g in self.gate_results(k))


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--k", type=int, default=4, help="short_hold_hop_count threshold for the fix")
    ap.add_argument("--benign", type=int, default=500)
    ap.add_argument("--attack-copies", type=int, default=8, help="seeded copies of each fraud template")
    ap.add_argument("--robustness-seeds", type=int, default=10)
    args = ap.parse_args()
    k = args.k
    mark = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731

    run = Run(args.seed, args.benign, args.attack_copies, k, verify=True)
    cand = run.candidate(k)
    by_id = {s.scenario_id: s for s in run.scenarios}

    print("Sentinel feasibility check (no LLM)")
    print(f"seed={args.seed}  benign={len(run.benign)}  attack={len(run.attack)}  "
          f"dataset sha256={dataset_hash(run.scenarios)[:16]}")
    print(f"Fix under test: R4 = short_hold_hop_count >= {k} (window 72h, each hold < 24h, "
          f"each hop forwards >= 40%), OR'ed onto v1")
    print("Lookahead check: passed (every alert reproduces with the trace cut at the alert time)\n")

    print(f"{'':22}{'baseline v1':>18}{'v1 + R4':>18}")
    print(f"{'attack recall':22}{pct(len(run.base & run.attack), len(run.attack)):>18}"
          f"{pct(len(cand & run.attack), len(run.attack)):>18}")
    print(f"{'benign FPR':22}{pct(len(run.base & run.benign), len(run.benign)):>18}"
          f"{pct(len(cand & run.benign), len(run.benign)):>18}\n")

    for title, templates, ids in (("Attack recall by template", ATTACK_TEMPLATES, run.attack),
                                  ("Benign FPR by template", BENIGN_TEMPLATES, run.benign)):
        print(title)
        for name in templates:
            group = {sid for sid in ids if by_id[sid].template_id == name}
            print(f"  {name:26} baseline {len(group & run.base)}/{len(group)}   v1+R4 {len(group & cand)}/{len(group)}")

    per_rule = defaultdict(int)
    for sid in run.benign:
        for rid in rules_fired(by_id[sid], BASELINE_V1):
            per_rule[rid] += 1
    r4_alone = {sid for sid in run.benign if run.hops[sid] >= k}
    print("Benign scenarios each rule flags on its own (rules overlap)")
    for r in BASELINE_V1:
        print(f"  {r.rule_id} {r.all_of[0].feature_key:26} {pct(per_rule[r.rule_id], len(run.benign))}")
    print(f"  R4 short_hold_hop_count     {pct(len(r4_alone), len(run.benign))}"
          f"  ({len(r4_alone & run.base)} of these were already flagged by v1, so the gate never sees them)\n")

    print("Gate (design §1 defaults)")
    for g in run.gate_results(k):
        print(f"  {g.name:22} {g.detail:58} {mark(g.passed)}")
    ok = run.passed(k)
    print(f"\nRESULT: {mark(ok)}")

    print("\nThreshold sweep, same data")
    print(f"  {'k':>3}  {'new FPs':>8}  {'recall':>16}  gate")
    for kk in range(2, 7):
        c = run.candidate(kk)
        print(f"  {kk:>3}  {len((c - run.base) & run.benign):>8}  {pct(len(c & run.attack), len(run.attack)):>16}  "
              f"{mark(run.passed(kk))}")

    seeds = [args.seed, *range(1000, 1000 + args.robustness_seeds)]
    print(f"\nAll seeds, k={k}")
    print(f"  {'seed':>5}  {'v1 benign flagged':>18}  {'fix new FPs':>11}  {'budget':>6}  "
          f"{'fraud caught v1 -> v1+R4':>24}  gate")
    results = []
    for seed in seeds:
        r = run if seed == args.seed else Run(seed, args.benign, args.attack_copies, k, verify=False)
        c = r.candidate(k)
        results.append(r.passed(k))
        caught = f"{len(r.base & r.attack)}/{len(r.attack)} -> {len(c & r.attack)}/{len(r.attack)}"
        print(f"  {seed:>5}  {pct(len(r.base & r.benign), len(r.benign)):>18}  {len((c - r.base) & r.benign):>11}  "
              f"{gates.fp_budget(len(r.benign)):>6}  {caught:>24}  {mark(results[-1])}")
    print(f"  passed on {sum(results)}/{len(results)} seeds")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
