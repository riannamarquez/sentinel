"""Golden fixtures: the hour-3 contract between the three workstreams (design-v2 §8).

Every fixture is generated from code here, so `make fixtures` rebuilds them byte-for-byte and a
test catches drift. The agent stubs and the API read them through the loaders below.
"""
from __future__ import annotations

import json
from pathlib import Path

from sentinel.detector.baseline import BASELINE_V1, hop_count_condition
from sentinel.detector.score import diagnose, score
from sentinel.scenarios import factory
from sentinel.schemas import (
    BypassTrace, DetectionResult, PatchOperation, RulePatch, Scenario, Split, canonical_json,
)
from sentinel.sim.actions import moved_out_cents

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
FIXTURE_SEED = 7
OBJECTIVE_CENTS = 300_000          # Red's objective: move >= $3,000 out of the source without an alert
GOLDEN_PATCH_ID = "golden-hop-count"
BYPASS_ID = "bypass-slow-chain-3"
SPLIT_SIZES = {                     # small, so tests and the frontend load them instantly
    Split.SEARCH: dict(benign=20, copies=2),
    Split.REGRESSION: dict(lookalikes=10, copies=4),
    Split.FINAL_HOLDOUT: dict(benign=40, copies=2),
}


def _pretty(obj) -> str:
    return json.dumps(json.loads(canonical_json(obj)), indent=2, sort_keys=True) + "\n"


def _golden(scenario: Scenario, note: str) -> str:
    return _pretty({"note": note, "scenario": scenario,
                    "baseline_v1": score(scenario, BASELINE_V1, detector_version=1)})


def build_splits() -> dict[Split, list[Scenario]]:
    seed, sizes = FIXTURE_SEED, SPLIT_SIZES
    s, r, h = sizes[Split.SEARCH], sizes[Split.REGRESSION], sizes[Split.FINAL_HOLDOUT]
    return {
        Split.SEARCH: (factory._benign(seed, Split.SEARCH, s["benign"], factory.BENIGN_TEMPLATES)
                       + factory._attacks(seed, Split.SEARCH, factory.SEARCH_ATTACKS, s["copies"])),
        Split.REGRESSION: (factory._benign(seed, Split.REGRESSION, r["lookalikes"], factory.LOOKALIKE_TEMPLATES)
                           + factory._attacks(seed, Split.REGRESSION, factory.REGRESSION_ATTACKS, r["copies"])),
        Split.FINAL_HOLDOUT: factory.final_holdout(seed, h["benign"], h["copies"]),
    }


def slow_variant() -> Scenario:
    return factory.attack_scenario(FIXTURE_SEED, Split.SEARCH, "slow_chain_3", 0)


def build_bypass_trace() -> BypassTrace:
    """Hand-written Red output for the slow variant: what a real Red turn would return."""
    scenario = slow_variant()
    return BypassTrace(
        bypass_id=BYPASS_ID, detector_version=1, scenario=scenario,
        moved_cents=moved_out_cents(scenario), objective_cents=OBJECTIVE_CENTS,
        why_it_worked=diagnose(scenario, BASELINE_V1),
        rationale=("Pass the money through three fresh mule accounts, holding each hop 7-20 hours: longer "
                   "than R2's 6-hour pass-through window, and one transfer at a time so R1's velocity "
                   "count never reaches 5. No new devices, so R3 never fires."),
    )


def build_golden_patch(base_version: int = 1) -> RulePatch:
    return RulePatch(
        patch_id=GOLDEN_PATCH_ID, base_version=base_version, operation=PatchOperation.ADD,
        all_of=[hop_count_condition(4)],
        rationale=("The bypass moved the stolen amount through 4+ consecutive transfers, each sent within "
                   "24 hours of the previous one arriving and forwarding most of it. Flag outgoing "
                   "transfers at the end of such a chain."),
    )


def build_fixture_files() -> dict[str, str]:
    """Relative path under fixtures/ -> exact file contents."""
    splits = build_splits()
    files = {
        "golden/caught_fraud.json": _golden(
            factory.attack_scenario(FIXTURE_SEED, Split.SEARCH, "fast_ring", 0),
            "Golden mule ring. Baseline v1 catches it with R1 (velocity)."),
        "golden/missed_fraud_slow_variant.json": _golden(
            slow_variant(), "Slow three-mule chain. Baseline v1 misses it; the golden patch catches it."),
        "golden/legit_lookalike.json": _golden(
            factory.benign_scenario(FIXTURE_SEED, Split.REGRESSION, "salaried_relay", 0),
            "Legitimate household: payday -> allowance -> sibling relay. Neither v1 nor v1 + golden patch "
            "should flag it."),
        "bypass_trace.json": _pretty(build_bypass_trace()),
        "golden_patch.json": _pretty(build_golden_patch()),
    }
    for split, scenarios in splits.items():
        files[f"splits/{split.value}.jsonl"] = "".join(canonical_json(s) + "\n" for s in scenarios)
    return files


def write_fixture_files(root: Path = FIXTURE_DIR) -> list[Path]:
    written = []
    for rel, content in build_fixture_files().items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        written.append(path)
    return written


# --- Loaders ----------------------------------------------------------------------------

def load_bypass_trace(root: Path = FIXTURE_DIR) -> BypassTrace:
    return BypassTrace.model_validate_json((root / "bypass_trace.json").read_text())


def load_golden_patch(root: Path = FIXTURE_DIR) -> RulePatch:
    return RulePatch.model_validate_json((root / "golden_patch.json").read_text())


def load_split(split: Split, root: Path = FIXTURE_DIR) -> list[Scenario]:
    lines = (root / "splits" / f"{split.value}.jsonl").read_text().splitlines()
    return [Scenario.model_validate_json(line) for line in lines if line]


def load_splits(root: Path = FIXTURE_DIR) -> dict[Split, list[Scenario]]:
    return {split: load_split(split, root) for split in Split}


def load_golden(name: str, root: Path = FIXTURE_DIR) -> tuple[Scenario, DetectionResult]:
    data = json.loads((root / "golden" / f"{name}.json").read_text())
    return Scenario.model_validate(data["scenario"]), DetectionResult.model_validate(data["baseline_v1"])
