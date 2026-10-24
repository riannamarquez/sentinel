"""Scenario factory: three splits from different seed streams and template families (design-v2 §6).

- search: what Red and Blue see (the golden ring and the slow chain, plus a few households).
- regression: every attack the baseline catches, plus benign lookalikes for the hop-count fix.
- final_holdout: hidden variants of every template plus benign households, from their own stream.
"""
from __future__ import annotations

from sentinel.schemas import Scenario, Split
from sentinel.sim.actions import apply_actions
from sentinel.sim.benign import BENIGN_TEMPLATES, LOOKALIKE_TEMPLATES
from sentinel.sim.builder import HouseholdBuilder
from sentinel.sim.fraud import ATTACK_TEMPLATES, SOURCE
from sentinel.sim.rng import derive_seed, rng_for

SEARCH_ATTACKS = ("fast_ring", "slow_chain_3")
REGRESSION_ATTACKS = ("fast_ring",)


def benign_scenario(seed: int, split: Split, template: str, i: int) -> Scenario:
    gen = {**BENIGN_TEMPLATES, **LOOKALIKE_TEMPLATES}[template]
    component = ("benign", split.value, template, i)
    b = HouseholdBuilder(f"{split.value}.{template}.{i:04d}", template, derive_seed(seed, *component), split)
    gen(b, rng_for(seed, *component))
    return b.build()


def attack_scenario(seed: int, split: Split, template: str, i: int) -> Scenario:
    component = ("fraud", split.value, template, i)
    plan = ATTACK_TEMPLATES[template](rng_for(seed, *component))
    return apply_actions(
        scenario_id=f"{split.value}.{template}.{i:04d}", template_id=template,
        seed=derive_seed(seed, *component), split=split, start_ts=plan.start_ts,
        source_account_id=SOURCE, funding_cents=plan.funding_cents, actions=plan.actions(),
    )


def _benign(seed: int, split: Split, n: int, templates) -> list[Scenario]:
    templates = list(templates)
    return [benign_scenario(seed, split, templates[i % len(templates)], i) for i in range(n)]


def _attacks(seed: int, split: Split, templates, copies: int) -> list[Scenario]:
    return [attack_scenario(seed, split, t, i) for t in templates for i in range(copies)]


def final_holdout(seed: int, benign_n: int = 500, attack_copies: int = 8) -> list[Scenario]:
    split = Split.FINAL_HOLDOUT
    return _benign(seed, split, benign_n, BENIGN_TEMPLATES) + _attacks(seed, split, ATTACK_TEMPLATES, attack_copies)


def search(seed: int, benign_n: int = 500, attack_copies: int = 8) -> list[Scenario]:
    split = Split.SEARCH
    return (_benign(seed, split, max(1, benign_n // 10), BENIGN_TEMPLATES)
            + _attacks(seed, split, SEARCH_ATTACKS, max(1, attack_copies // 2)))


def regression(seed: int, benign_n: int = 500, attack_copies: int = 8) -> list[Scenario]:
    split = Split.REGRESSION
    return (_benign(seed, split, max(1, benign_n // 25), LOOKALIKE_TEMPLATES)
            + _attacks(seed, split, REGRESSION_ATTACKS, attack_copies))


def build_splits(seed: int, benign_n: int = 500, attack_copies: int = 8) -> dict[Split, list[Scenario]]:
    return {
        Split.SEARCH: search(seed, benign_n, attack_copies),
        Split.REGRESSION: regression(seed, benign_n, attack_copies),
        Split.FINAL_HOLDOUT: final_holdout(seed, benign_n, attack_copies),
    }
