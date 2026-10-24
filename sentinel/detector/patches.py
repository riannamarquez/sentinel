"""Validate and apply Blue's RulePatches (design-v2 §6, US-06). Pure functions, explicit errors."""
from __future__ import annotations

from sentinel.features.registry import validate_condition
from sentinel.schemas import PatchOperation, Rule, RulePatch


class PatchError(ValueError):
    pass


def validate_rules(rules: list[Rule]) -> None:
    ids = [r.rule_id for r in rules]
    if len(ids) != len(set(ids)):
        raise PatchError("duplicate rule ids")
    for r in rules:
        for c in r.all_of:
            try:
                validate_condition(c)
            except ValueError as e:
                raise PatchError(f"{r.rule_id}: {e}") from e


def next_rule_id(rules: list[Rule]) -> str:
    return f"R{max((int(r.rule_id[1:]) for r in rules), default=0) + 1}"


def apply_patch(rules: list[Rule], patch: RulePatch) -> list[Rule]:
    """New rule list with the patch applied. The server assigns rule ids for add."""
    by_id = {r.rule_id: r for r in rules}
    if patch.operation is PatchOperation.ADD:
        out = [*rules, Rule(rule_id=next_rule_id(rules), all_of=patch.all_of)]
    elif patch.rule_id not in by_id:
        raise PatchError(f"unknown rule {patch.rule_id}")
    elif patch.operation is PatchOperation.MODIFY:
        out = [Rule(rule_id=r.rule_id, all_of=patch.all_of) if r.rule_id == patch.rule_id else r for r in rules]
    else:
        out = [r for r in rules if r.rule_id != patch.rule_id]
    validate_rules(out)
    return out
