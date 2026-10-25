'''
Freeze the contract.
Uses Pydantic models that describe what /timeline returns
Includes example JSON file that Claire can build against

This file will hold models
'''
# Lets a method say it returns its own class (e.g. `-> TimelineNode`) before that class
# has finished being defined. Without this, Python would complain the name doesn't exist yet.
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, model_validator

from sentinel.detector import score
from sentinel.schemas import Rule, Scenario
from sentinel.schemas.models import Model # importing model from models.py because it is strict/effective
# Shared field types from models.py, so these limits match the rest of the project:
#   Cents         = int from 0 up to $1bn (in cents)
#   PositiveCents = same, but must be at least 1
#   Id            = 1-64 chars of letters, digits and _ . : -
#   Timestamp     = int seconds from 0 up to one simulated year
#   Version       = detector version number, 1 or higher
from sentinel.schemas.models import Cents, Id, PositiveCents, Timestamp, Version
from sentinel.sim.actions import is_external, moved_out_cents   # EXT-* check; cents that reached an EXT-* account


class TimelineNode(Model):
    """One node in the timeline graph. Only a cluster node carries a count."""
    id: Id                                                  # account id, e.g. "M1" or "EXT-cashout"
    role: Literal["source", "mule", "external", "cluster"] # turns away anything outside of the four roles
    # `int | None` means count may be a number or null. `default=None` means it's null
    # if left out, so source/mule/external nodes send "count": null.
    count: int | None = Field(default=None, ge=1)   # accounts folded into the cluster
                    # checks that a cluster's count is at least 1

    # Runs after the fields above pass their own checks, so `self.role` and `self.count`
    # already hold valid values here. Checks rules that involve more than one field.
    @model_validator(mode="after")
    def _check(self) -> TimelineNode:
        # A cluster stands for "N other accounts", so it needs its N.
        if self.role == "cluster" and self.count is None:
            raise ValueError("a cluster node must have a count")
        # A single account has no count; a non-null count on one would be a bug on our side.
        if self.role != "cluster" and self.count is not None:
            raise ValueError("only a cluster node may have a count")
        return self   # a model_validator must hand back the object when it passes


class TimelineTransfer(Model):
    """One transfer (graph edge). Only a scored transfer can fire rules."""
    id: Id
    from_: Id = Field(alias="from")   # `from` is a Python keyword; dump with by_alias=True
    to: Id                            # the node id the money goes to
    amount_cents: PositiveCents       # integer cents, never floats (0.1 + 0.2 != 0.3 in floats)
    t_offset_s: Timestamp             # seconds since the start of the simulated window
    scored: bool                      # the detector evaluated rules at this transfer
    # A list of rule ids like "R4". The pattern means: "R" then 1 to 4 digits, nothing else.
    # default_factory=list gives each transfer its own new empty list when left out.
    rules_fired: list[Annotated[str, Field(pattern=r"^R[0-9]{1,4}$")]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> TimelineTransfer:
        # Same check Transaction has in models.py: money can't go to the account it left.
        if self.from_ == self.to:
            raise ValueError("a transfer cannot go from a node to itself")
        # The detector only checks rules on transfers it scores (money leaving accounts the
        # scenario owns), so a rule can't have fired on an unscored one. An empty list is
        # falsy, so `if self.rules_fired` means "if at least one rule fired".
        if self.rules_fired and not self.scored:
            raise ValueError("an unscored transfer cannot fire rules")
        return self


# Its own model rather than a plain dict, so Pydantic checks the keys and types.
# A dict would accept a missing "caught", "caught": "yes", or negative cents.
class TimelineSummary(Model):
    moved_cents: Cents                # how much reached the external cash-out
    objective_cents: Cents            # how much Red was trying to move
    caught: bool                      # some rule fired on some transfer


class Timeline(Model):
    """What GET /labs/{id}/timeline returns: one scenario's subgraph, scored against one detector version."""
    lab_id: Id                        # e.g. "lab-0001", the format store.py generates
    run_id: Id                        # e.g. "run-000001"
    detector_version: Version         # which rule set scored these transfers (v2 has R4)
    start_ts: Timestamp               # every t_offset_s is measured from here
    # The graph's nodes. At least 1; at most 200 so the frontend graph stays fast
    # (design-review §3.5 caps the scenario subgraph at about 200 nodes).
    nodes: list[TimelineNode] = Field(min_length=1, max_length=200)
    transfers: list[TimelineTransfer] = Field(max_length=10_000)   # same cap as Scenario.transactions
    summary: TimelineSummary          # a nested model: the "summary" JSON object is checked too

    # Checks that the pieces agree with each other. These catch mistakes in hand-written
    # fixtures, like a transfer pointing at a node that was never listed.
    @model_validator(mode="after")
    def _check(self) -> Timeline:
        node_ids = [n.id for n in self.nodes]
        # A set drops duplicates, so if it's shorter than the list, some id appears twice.
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node ids must be unique")
        # Every edge must connect two nodes that exist, or the graph can't draw it.
        for t in self.transfers:
            if t.from_ not in node_ids or t.to not in node_ids:
                raise ValueError(f"transfer {t.id} points at a node that is not in nodes")
        # The frontend animates transfers in list order, so the list must already be sorted by time.
        offsets = [t.t_offset_s for t in self.transfers]
        if offsets != sorted(offsets):
            raise ValueError("transfers must be in time order")
        # any(...) is True if at least one transfer has a non-empty rules_fired list.
        # caught must match that exactly: no "caught" without a fired rule, and vice versa.
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
    # The alias means input must use the JSON name "from", not from_; ** passes it as a keyword.
    transfers = [
        TimelineTransfer(id=t.transaction_id, **{"from": t.from_id}, to=t.to_id, amount_cents=t.amount_cents,
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
