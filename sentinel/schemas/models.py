"""Pydantic models shared by the engine, the API and the agents (design-v2 §4).

Money is always integer cents and time is always integer seconds since the start of the
simulated window. Every model is frozen and rejects unknown fields.
"""
from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_CENTS = 10**11                 # $1bn ceiling on any amount or money threshold
MAX_TS = 366 * 24 * 3600           # one simulated year
MAX_WINDOW_HOURS = 168             # design-v2 §6: a window over 168h is rejected
MAX_ACTIONS = 30                   # design-v2 §6: each Red scenario is <= 30 actions
MAX_CONDITIONS = 3                 # design-v2 §4.2: 1 to 3 conditions per rule

Cents = Annotated[int, Field(ge=0, le=MAX_CENTS)]
PositiveCents = Annotated[int, Field(gt=0, le=MAX_CENTS)]
Timestamp = Annotated[int, Field(ge=0, le=MAX_TS)]
Id = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=1, le=100_000)]
Count = Annotated[int, Field(ge=0, le=10_000_000)]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Lab configuration and world ------------------------------------------------------

class Segment(StrEnum):
    SALARIED = "salaried"
    GIG = "gig"
    STUDENT = "student"
    SMALL_BUSINESS = "small_business"


class BankConfig(Model):
    """Immutable once a run starts."""
    lab_id: Id | None = None
    seed: int = Field(ge=0, le=2**63 - 1)
    account_count: int = Field(default=200, ge=1, le=20_000)
    simulation_days: int = Field(default=28, ge=1, le=90)
    customer_segments: list[Segment] = Field(default_factory=lambda: list(Segment), min_length=1, max_length=4)
    initial_balance_range_cents: tuple[Cents, Cents] = (10_000, 500_000)
    detector_version: Version = 1
    holdout_benign_n: int = Field(default=500, ge=1, le=5_000)
    holdout_attack_copies: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _check(self) -> BankConfig:
        lo, hi = self.initial_balance_range_cents
        if lo > hi:
            raise ValueError("initial_balance_range_cents must be (low, high) with low <= high")
        if len(set(self.customer_segments)) != len(self.customer_segments):
            raise ValueError("customer_segments must not repeat")
        return self


class Customer(Model):
    customer_id: Id
    segment: Segment
    income_band: Literal["low", "mid", "high"]
    device_ids: list[Id] = Field(min_length=1, max_length=10)


class Account(Model):
    account_id: Id
    customer_id: Id
    created_at: Timestamp
    balance_cents: Cents                 # balance never below 0
    risk_tags: list[Annotated[str, Field(max_length=32)]] = Field(default_factory=list, max_length=10)


class Label(StrEnum):
    BENIGN = "benign"
    MALICIOUS = "malicious"


class Transaction(Model):
    transaction_id: Id
    from_id: Id
    to_id: Id
    amount_cents: PositiveCents
    timestamp: Timestamp
    device_id: Id | None = None
    merchant_category: Annotated[str, Field(max_length=32)] | None = None
    scenario_id: Id
    ground_truth_label: Label           # hidden from Red and Blue

    @model_validator(mode="after")
    def _check(self) -> Transaction:
        if self.from_id == self.to_id:
            raise ValueError("a transaction cannot go from an account to itself")
        return self


class World(Model):
    seed: int
    customers: list[Customer]
    accounts: list[Account]
    transactions: list[Transaction]


# --- Red's moves and scenarios --------------------------------------------------------

class ActionType(StrEnum):
    OPEN_SYNTHETIC_ACCOUNT = "open_synthetic_account"
    SIMULATED_TRANSFER = "simulated_transfer"
    CHANGE_SIMULATED_DEVICE = "change_simulated_device"
    WAIT = "wait"


class SimulationAction(Model):
    """One allowlisted move. timestamp_offset is seconds after the previous action."""
    type: ActionType
    timestamp_offset: int = Field(ge=0, le=14 * 24 * 3600)
    source_id: Id | None = None
    target_id: Id | None = None
    amount_cents: PositiveCents | None = None
    device_id: Id | None = None

    @model_validator(mode="after")
    def _check(self) -> SimulationAction:
        need = {
            ActionType.OPEN_SYNTHETIC_ACCOUNT: {"target_id"},
            ActionType.SIMULATED_TRANSFER: {"source_id", "target_id", "amount_cents"},
            ActionType.CHANGE_SIMULATED_DEVICE: {"source_id", "device_id"},
            ActionType.WAIT: set(),
        }[self.type]
        given = {f for f in ("source_id", "target_id", "amount_cents", "device_id") if getattr(self, f) is not None}
        if given != need:
            raise ValueError(f"{self.type} takes exactly {sorted(need)}, got {sorted(given)}")
        return self


class Split(StrEnum):
    SEARCH = "search"
    REGRESSION = "regression"
    FINAL_HOLDOUT = "final_holdout"


class Scenario(Model):
    scenario_id: Id
    template_id: Id
    seed: int = Field(ge=0, le=2**64 - 1)
    split: Split
    malicious_label: bool
    start_ts: Timestamp = 0
    source_account_id: Id | None = None      # malicious only: the account the objective drains
    funding_cents: Cents = 0                 # malicious only: stolen amount deposited into the source
    opening_balances_cents: dict[Id, Cents] = Field(default_factory=dict)
    initial_devices: dict[Id, Id] = Field(default_factory=dict)
    actions: list[SimulationAction] = Field(default_factory=list, max_length=MAX_ACTIONS)
    owned_account_ids: list[Id] = Field(min_length=1, max_length=50)
    transactions: list[Transaction] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        keys = [(t.timestamp, t.transaction_id) for t in self.transactions]
        if keys != sorted(keys):
            raise ValueError("transactions must be sorted by (timestamp, transaction_id)")
        if self.malicious_label != (self.source_account_id is not None):
            raise ValueError("source_account_id is set exactly when the scenario is malicious")
        return self


# --- Rules and patches (design-v2 §4.2) -----------------------------------------------

FeatureKey = Literal[
    "velocity_out_count",
    "velocity_out_amount",
    "velocity_in_amount",
    "new_device_before_transfer",
    "transfer_amount",
    "near_threshold_amount",
    "pass_through_ratio",
    "min_hold_hours",
    "short_hold_hop_count",
]
Operator = Literal[">=", ">", "<=", "<"]
ParamKey = Literal["n_hours", "hold_hours", "min_carry_pct", "reporting_threshold_cents"]


class Condition(Model):
    feature_key: FeatureKey
    operator: Operator
    threshold: int | float = Field(ge=0, le=MAX_CENTS)
    window_hours: int | None = Field(default=None, ge=1, le=MAX_WINDOW_HOURS)
    params: dict[ParamKey, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Condition:
        if isinstance(self.threshold, float) and not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        return self


class Rule(Model):
    rule_id: str = Field(pattern=r"^R[0-9]{1,4}$")
    all_of: list[Condition] = Field(min_length=1, max_length=MAX_CONDITIONS)


class PatchOperation(StrEnum):
    ADD = "add"
    MODIFY = "modify"
    DISABLE = "disable"


class RulePatch(Model):
    patch_id: Id
    base_version: Version
    operation: PatchOperation
    rule_id: str | None = Field(default=None, pattern=r"^R[0-9]{1,4}$")
    all_of: list[Condition] | None = Field(default=None, min_length=1, max_length=MAX_CONDITIONS)
    rationale: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def _check(self) -> RulePatch:
        if self.operation is PatchOperation.ADD and self.all_of is None:
            raise ValueError("add needs all_of")
        if self.operation is PatchOperation.MODIFY and (self.rule_id is None or self.all_of is None):
            raise ValueError("modify needs rule_id and all_of")
        if self.operation is PatchOperation.DISABLE and (self.rule_id is None or self.all_of is not None):
            raise ValueError("disable needs rule_id and no all_of")
        return self


class DetectorVersion(Model):
    version: Version
    rules: list[Rule] = Field(max_length=50)
    parent_version: Version | None = None
    created_by_event_id: Id


# --- Results ---------------------------------------------------------------------------

class DetectionResult(Model):
    scenario_id: Id
    detector_version: Version | None = None   # None when scoring an unapproved candidate
    alert: bool
    triggered_rule_ids: list[str] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)
    first_alert_time: Timestamp | None = None

    @model_validator(mode="after")
    def _check(self) -> DetectionResult:
        if self.alert != (self.first_alert_time is not None):
            raise ValueError("first_alert_time is set exactly when alert is true")
        if any(not math.isfinite(v) for v in self.features.values()):
            raise ValueError("feature values must be finite")
        return self


class ConditionDiagnosis(Model):
    feature_key: FeatureKey
    operator: Operator
    threshold: int | float
    closest_value: float          # the value that came nearest to firing, across the scenario
    held: bool                    # True when the condition never fired


class RuleDiagnosis(Model):
    rule_id: str
    conditions: list[ConditionDiagnosis]


class BypassTrace(Model):
    """Red's output: a scenario that moved money without an alert, and why it worked."""
    bypass_id: Id
    detector_version: Version
    scenario: Scenario
    moved_cents: Cents
    objective_cents: Cents
    why_it_worked: list[RuleDiagnosis]
    rationale: str = Field(default="", max_length=2_000)


class Confusion(Model):
    tp: Count
    fp: Count
    tn: Count
    fn: Count


class GateResult(Model):
    name: Literal["schema_valid", "fpr_budget", "regression_no_loss", "regression_benign", "holdout_recall_gain"]
    split: Split | None
    numerator: int
    denominator: Count
    threshold: int | float
    passed: bool
    detail: str = Field(default="", max_length=500)


MissReasonCode = Literal["long_hold", "short_chain", "low_carry", "other"]


class MissReason(Model):
    """One bucket of final-holdout attacks the candidate rules did not flag."""
    reason: MissReasonCode
    label: str = Field(max_length=100)
    count: Count


class EvaluationReport(Model):
    report_id: Id
    run_id: Id
    patch_id: Id
    baseline_version: Version
    candidate_version: Version              # the version number it gets if approved
    candidate_rules_hash: Sha256
    benign_n: Count                         # final holdout
    attack_n: Count                         # final holdout
    dataset_hashes: dict[Split, Sha256]
    baseline_confusion: dict[Split, Confusion]
    candidate_confusion: dict[Split, Confusion]
    recall_before: float | None
    recall_after: float | None
    fpr_before: float | None
    fpr_after: float | None
    regression_pass: bool
    holdout_pass: bool
    gate_pass: bool
    gate_results: list[GateResult]
    eligible_for_approval: bool
    # Defaults to empty so reports stored before this field existed still load.
    missed_breakdown: list[MissReason] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _check(self) -> EvaluationReport:
        if self.gate_pass != all(g.passed for g in self.gate_results):
            raise ValueError("gate_pass must equal all(gate_results.passed)")
        if self.eligible_for_approval != self.gate_pass:
            raise ValueError("eligible_for_approval must equal gate_pass")
        missed = self.candidate_confusion.get(Split.FINAL_HOLDOUT)
        if self.missed_breakdown and missed and sum(m.count for m in self.missed_breakdown) != missed.fn:
            raise ValueError("missed_breakdown counts must sum to the missed final-holdout attacks")
        return self


class AuditEvent(Model):
    """Append-only."""
    event_id: Id
    seq: Count
    timestamp: int = Field(ge=0)            # wall-clock seconds; not part of any simulated trace
    actor: Annotated[str, Field(min_length=1, max_length=64)]
    run_id: Id | None = None
    action: Annotated[str, Field(min_length=1, max_length=64)]
    input_hash: Sha256 | None = None
    output_hash: Sha256 | None = None
    version_before: Version | None = None
    version_after: Version | None = None
