'''
Freeze the contract.
Uses Pydantic models that describe what /timeline returns
Includes example JSON file that Claire can build against

This file will hold models
'''
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from sentinel.detector import score
from sentinel.schemas import Rule, Scenario
from sentinel.schemas.models import Model # importing model from models.py because it is strict/effective
from sentinel.schemas.models import Cents, Id, PositiveCents, Timestamp, Version
from sentinel.sim.actions import is_external, moved_out_cents


class TimelineNode(Model): 
    """One node in the timeline graph. Only a cluster node carries a count."""
    id: Id
    role: Literal["source", "mule", "external", "cluster"]
    count: int | None = Field(default=None, ge=1)   # accounts folded into the cluster

    @model_validator(mode="after")
    def _check(self) -> TimelineNode:
        if self.role == "cluster" and self.count is None:
            raise ValueError("a cluster node must have a count")
        if self.role != "cluster" and self.count is not None:
            raise ValueError("only a cluster node may have a count")
        return self


class TimelineTransfer(Model):
    """One transfer (graph edge). Only a scored transfer can fire rules."""
    model_config = ConfigDict(populate_by_name=True)   # merged with Model's frozen/extra="forbid"
    id: Id
    from_: Id = Field(alias="from")   # `from` is a Python keyword; dump with by_alias=True
    to: Id
    amount_cents: PositiveCents
    t_offset_s: Timestamp             # seconds since the start of the simulated window
    scored: bool                      # the detector evaluated rules at this transfer
    rules_fired: list[Annotated[str, Field(pattern=r"^R[0-9]{1,4}$")]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> TimelineTransfer:
        if self.from_ == self.to:
            raise ValueError("a transfer cannot go from a node to itself")
        if self.rules_fired and not self.scored:
            raise ValueError("an unscored transfer cannot fire rules")
        return self


class TimelineSummary(Model):
    moved_cents: Cents                # how much reached the external cash-out
    objective_cents: Cents            # how much Red was trying to move
    caught: bool                      # some rule fired on some transfer


class Timeline(Model):
    """What GET /labs/{id}/timeline returns: one scenario's subgraph, scored against one detector version."""
    lab_id: Id
    run_id: Id
    detector_version: Version
    start_ts: Timestamp               # every t_offset_s is measured from here
    nodes: list[TimelineNode] = Field(min_length=1, max_length=200)
    transfers: list[TimelineTransfer] = Field(max_length=10_000)
    summary: TimelineSummary

    @model_validator(mode="after")
    def _check(self) -> Timeline:
        node_ids = [n.id for n in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node ids must be unique")
        for t in self.transfers:
            if t.from_ not in node_ids or t.to not in node_ids:
                raise ValueError(f"transfer {t.id} points at a node that is not in nodes")
        offsets = [t.t_offset_s for t in self.transfers]
        if offsets != sorted(offsets):
            raise ValueError("transfers must be in time order")
        if self.summary.caught != any(t.rules_fired for t in self.transfers):
            raise ValueError("summary.caught must be true exactly when some transfer fired a rule")
        return self


def build_timeline(scenario: Scenario, rules: Sequence[Rule], *, lab_id: str, run_id: str,
                   version: int, objective_cents: int, background_accounts: int) -> Timeline:
    """Pure: one scenario scored against one rule set. No store, no I/O."""
    node_ids: list[str] = []
    for t in scenario.transactions:
        for account_id in (t.from_id, t.to_id):
            if account_id not in node_ids:
                node_ids.append(account_id)
    nodes = [TimelineNode(id=a, role="source" if a == scenario.source_account_id
                          else "external" if is_external(a) else "mule") for a in node_ids]
    if background_accounts > 0:
        nodes.append(TimelineNode(id="OTHER", role="cluster", count=background_accounts))

    fired = dict(score.timeline(scenario, rules))   # scored transfers only, no lookahead
    transfers = [
        TimelineTransfer(id=t.transaction_id, from_=t.from_id, to=t.to_id, amount_cents=t.amount_cents,
                         t_offset_s=t.timestamp - scenario.start_ts, scored=t.transaction_id in fired,
                         rules_fired=list(fired.get(t.transaction_id, ())))
        for t in sorted(scenario.transactions, key=lambda t: (t.timestamp, t.transaction_id))
    ]
    return Timeline(
        lab_id=lab_id, run_id=run_id, detector_version=version, start_ts=scenario.start_ts,
        nodes=nodes, transfers=transfers,
        summary=TimelineSummary(moved_cents=moved_out_cents(scenario), objective_cents=objective_cents,
                                caught=any(t.rules_fired for t in transfers)),
    )
