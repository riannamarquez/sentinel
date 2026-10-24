"""The round state machine (design-v2 §3) as an explicit enum and transition table.

Adds the terminal states the review asked for (1.1.7): NO_BYPASS_FOUND, FAILED and CANCELLED.
"""
from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    INITIALIZE_LAB = "initialize_lab"
    GENERATE_WORLD = "generate_world"
    BASELINE_SCORE = "baseline_score"
    RED_PROPOSES = "red_proposes"
    VALIDATE_ACTIONS = "validate_actions"
    RUN_SIMULATION = "run_simulation"
    MEASURE_OUTCOME = "measure_outcome"
    BLUE_PROPOSES = "blue_proposes"
    VALIDATE_PATCH = "validate_patch"
    EVALUATE_HOLDOUTS = "evaluate_holdouts"
    APPLY_GATES = "apply_gates"
    AWAIT_HUMAN = "await_human"
    APPLY_NEW_VERSION = "apply_new_version"
    REJECT_NO_CHANGE = "reject_no_change"
    RECHALLENGE = "rechallenge"
    COMPLETE = "complete"
    NO_BYPASS_FOUND = "no_bypass_found"
    FAILED = "failed"
    CANCELLED = "cancelled"


S = RunState
TERMINAL = frozenset({S.COMPLETE, S.NO_BYPASS_FOUND, S.FAILED, S.CANCELLED})

_FORWARD: dict[RunState, set[RunState]] = {
    S.INITIALIZE_LAB: {S.GENERATE_WORLD},
    S.GENERATE_WORLD: {S.BASELINE_SCORE},
    S.BASELINE_SCORE: {S.RED_PROPOSES},
    S.RED_PROPOSES: {S.VALIDATE_ACTIONS},
    S.VALIDATE_ACTIONS: {S.RUN_SIMULATION},                          # invalid candidates are dropped
    S.RUN_SIMULATION: {S.MEASURE_OUTCOME},
    S.MEASURE_OUTCOME: {S.BLUE_PROPOSES, S.RED_PROPOSES, S.NO_BYPASS_FOUND},  # retry, max 4 turns
    S.BLUE_PROPOSES: {S.VALIDATE_PATCH},
    S.VALIDATE_PATCH: {S.EVALUATE_HOLDOUTS},
    S.EVALUATE_HOLDOUTS: {S.APPLY_GATES},
    S.APPLY_GATES: {S.AWAIT_HUMAN},
    S.AWAIT_HUMAN: {S.APPLY_NEW_VERSION, S.REJECT_NO_CHANGE},
    S.APPLY_NEW_VERSION: {S.RECHALLENGE},
    S.REJECT_NO_CHANGE: {S.RECHALLENGE},
    S.RECHALLENGE: {S.COMPLETE},
}

# Every non-terminal state may also fail closed or be cancelled.
ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    state: frozenset(_FORWARD.get(state, set()) | ({S.FAILED, S.CANCELLED} if state not in TERMINAL else set()))
    for state in RunState
}


class InvalidTransition(Exception):
    def __init__(self, current: RunState, target: RunState):
        super().__init__(f"cannot go from {current} to {target}")
        self.current, self.target = current, target


def check_transition(current: RunState, target: RunState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(current, target)
