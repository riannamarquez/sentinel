"""Blue agent, stubbed: returns the golden hop-count patch from fixtures. No LLM."""
from __future__ import annotations

from collections.abc import Sequence

from sentinel.fixtures import load_golden_patch
from sentinel.schemas import BypassTrace, Rule, RulePatch


def propose(bypass: BypassTrace, rules: Sequence[Rule], base_version: int) -> list[RulePatch]:
    """Up to 3 candidates in the real agent; the stub always proposes the one known to pass."""
    return [load_golden_patch().model_copy(update={"base_version": base_version})]
