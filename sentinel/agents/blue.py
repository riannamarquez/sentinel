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


# Agent tools see development data only. The final holdout stays with the independent evaluator.
class DevelopmentFeedback(Model):
    patch: RulePatch
    error: str | None = None
    bypass_caught: bool = False
    search_before: dict[str, int] = Field(default_factory=dict)
    search_after: dict[str, int] = Field(default_factory=dict)
    regression_attacks_lost: int = 0
    regression_new_false_positives: int = 0
    acceptable: bool = False


class BlueTurn(Model):
    turn: int = Field(ge=1, le=3)
    input_hash: str
    feedback: list[DevelopmentFeedback]
    selected_patch_id: str | None = None


class RepairResult(Model):
    selected: RulePatch | None = None
    history: list[BlueTurn]


def test_development_patch(bypass, rules, base_version, patch, development):
    """Deterministic tool result: aggregate search/regression counts, never hidden data."""
    from sentinel.detector.patches import PatchError, apply_patch
    from sentinel.detector.score import score
    from sentinel.eval.evaluator import flagged, confusion
    from sentinel.eval.gates import fp_budget
    from sentinel.schemas import Split

    try:
        if patch.base_version != base_version:
            raise PatchError('patch base_version does not match the current rules')
        candidate = apply_patch(list(rules), patch)
    except (PatchError, ValueError) as exc:
        return DevelopmentFeedback(patch=patch, error=str(exc)[:2000])
    search, regression = development[Split.SEARCH], development[Split.REGRESSION]
    before = flagged(search, rules)
    after = flagged(search, candidate)
    base_counts, new_counts = confusion(search, before), confusion(search, after)
    reg_before, reg_after = flagged(regression, rules), flagged(regression, candidate)
    reg_attacks = {s.scenario_id for s in regression if s.malicious_label}
    reg_base, reg_new = confusion(regression, reg_before), confusion(regression, reg_after)
    lost = len((reg_before & reg_attacks) - reg_after)
    new_fp = reg_new.fp - reg_base.fp
    caught = score(bypass.scenario, candidate).alert
    search_attacks = {s.scenario_id for s in search if s.malicious_label}
    acceptable = (caught and not lost and new_fp <= 0
                  and base_counts.fp + base_counts.tn > 0
                  and new_counts.fp - base_counts.fp <= fp_budget(base_counts.fp + base_counts.tn)
                  and not ((before & search_attacks) - after))
    return DevelopmentFeedback(
        patch=patch, bypass_caught=caught,
        search_before=base_counts.model_dump(), search_after=new_counts.model_dump(),
        regression_attacks_lost=lost, regression_new_false_positives=new_fp,
        acceptable=acceptable,
    )


def run_repair(bypass, rules, base_version, *, adapter, development, on_turn=None, max_turns=3, replay_turn_limit=None):
    """Observe -> propose -> use deterministic tools -> revise, with one selected candidate.

    Tools receive search/regression only. Only the independent evaluation endpoint may
    open the final holdout. No version is activated here, even when development succeeds.
    """
    import time
    from sentinel.llm.adapter import AdapterError, proposal_request
    from sentinel.schemas import Split, sha256_of

    if set(development) != {Split.SEARCH, Split.REGRESSION}:
        raise ValueError('Blue tools require only search and regression data')
    if not 1 <= max_turns <= 3:
        raise ValueError('Blue is limited to 1–3 turns')
    if replay_turn_limit is not None and (getattr(adapter, 'mode', None) != 'replay' or not 1 <= replay_turn_limit <= max_turns):
        raise ValueError('Only replay may stop at a recorded turn boundary')
    deadline = time.monotonic() + getattr(adapter, 'timeout_seconds', 90)
    history = []
    for turn in range(1, (replay_turn_limit or max_turns) + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AdapterError('Blue repair deadline exceeded')
        inputs = {**prompt_inputs(bypass, rules, base_version), 'turn': turn, 'max_turns': max_turns,
                  'development_history': [h.model_dump(mode='json') for h in history]}
        request = proposal_request('blue_agent', inputs, BlueProposal, 'blue-agent-v1')
        request['model'] = adapter.model
        proposal = adapter.propose('blue_agent', inputs, BlueProposal, prompt_version='blue-agent-v1',
                                   timeout_seconds=remaining)
        feedback = [test_development_patch(bypass, rules, base_version, p, development) for p in proposal.patches]
        passing = [f for f in feedback if f.acceptable]
        # Deterministic selection on development data, never on the hidden holdout.
        selected = min(passing, key=lambda f: (f.search_after['fp'], -f.search_after['tp'], f.patch.patch_id)).patch if passing else None
        record = BlueTurn(turn=turn, input_hash=sha256_of(request), feedback=feedback,
                          selected_patch_id=selected.patch_id if selected else None)
        history.append(record)
        if on_turn:
            on_turn(record)
        if time.monotonic() > deadline:
            raise AdapterError('Blue repair deadline exceeded')
        if selected:
            return RepairResult(selected=selected, history=history)
    return RepairResult(history=history)
