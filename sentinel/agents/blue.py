"""Blue proposes bounded patches; deterministic code validates their semantics."""
from __future__ import annotations

from collections.abc import Sequence
from pydantic import Field, model_validator
from sentinel.features.registry import FEATURES
from sentinel.fixtures import load_golden_patch
from sentinel.schemas import BypassTrace, Rule, RulePatch
from sentinel.schemas.models import Model


class BlueProposal(Model):
    patches: list[RulePatch] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def unique_patch_ids(self):
        if len({p.patch_id for p in self.patches}) != len(self.patches):
            raise ValueError('patch IDs must be distinct')
        return self


def prompt_inputs(bypass: BypassTrace, rules: Sequence[Rule], base_version: int):
    # Never forward Red's rationale, labels, template IDs, seeds or holdout data.
    return {
        'evidence_id': bypass.bypass_id,
        'base_version': base_version,
        'rules': [r.model_dump(mode='json') for r in rules],
        'transactions': [dict(from_id=t.from_id, to_id=t.to_id, amount_cents=t.amount_cents,
                              timestamp=t.timestamp, device_id=t.device_id) for t in bypass.scenario.transactions],
        'diagnosis': [d.model_dump(mode='json') for d in bypass.why_it_worked],
        'feature_catalog': {name: dict(threshold_bounds=spec.threshold_bounds,
                                     needs_window=spec.needs_window, params=spec.params)
                            for name, spec in FEATURES.items()},
    }


def propose(bypass: BypassTrace, rules: Sequence[Rule], base_version: int, *, adapter=None) -> list[RulePatch]:
    if adapter is None:
        return [load_golden_patch().model_copy(update={'base_version': base_version})]
    return adapter.propose('blue', prompt_inputs(bypass, rules, base_version), BlueProposal,
                           prompt_version='blue-v1').patches
