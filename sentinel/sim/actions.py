"""apply_actions: validate Red's allowlisted moves and turn them into transactions (design-v2 §5.2).

An invalid action rejects the whole scenario; nothing is repaired silently (design §3).
"""
from __future__ import annotations

from sentinel.schemas import ActionType, Label, Scenario, SimulationAction, Split, Transaction
from sentinel.sim.clock import DAY

EXTERNAL_PREFIX = "EXT-"
FUNDING_ACCOUNT = "EXT-victim"
MAX_OPENED_ACCOUNTS = 8
HORIZON_S = 14 * DAY


class ActionError(ValueError):
    def __init__(self, index: int, reason: str):
        super().__init__(f"action {index}: {reason}")
        self.index, self.reason = index, reason


def is_external(account_id: str) -> bool:
    return account_id.startswith(EXTERNAL_PREFIX)


def apply_actions(
    *, scenario_id: str, template_id: str, seed: int, split: Split, start_ts: int,
    source_account_id: str, funding_cents: int, actions: list[SimulationAction],
) -> Scenario:
    """The stolen amount lands in the source account at start_ts; then each action runs in order."""
    if is_external(source_account_id):
        raise ActionError(-1, "the source account must be internal")
    balance = {source_account_id: 0}
    device = {source_account_id: f"{source_account_id}-d0"}
    initial_devices = dict(device)
    rows = [(start_ts, FUNDING_ACCOUNT, source_account_id, funding_cents, None)]
    balance[source_account_id] += funding_cents
    t, opened = start_ts, 0

    for i, a in enumerate(actions):
        t += a.timestamp_offset
        if t - start_ts > HORIZON_S:
            raise ActionError(i, "past the 14-day horizon")
        if a.type is ActionType.OPEN_SYNTHETIC_ACCOUNT:
            if a.target_id in balance or is_external(a.target_id):
                raise ActionError(i, f"cannot open {a.target_id}")
            opened += 1
            if opened > MAX_OPENED_ACCOUNTS:
                raise ActionError(i, f"more than {MAX_OPENED_ACCOUNTS} new accounts")
            balance[a.target_id] = 0
            device[a.target_id] = initial_devices[a.target_id] = f"{a.target_id}-d0"
        elif a.type is ActionType.CHANGE_SIMULATED_DEVICE:
            if a.source_id not in balance:
                raise ActionError(i, f"unknown account {a.source_id}")
            if a.device_id == device[a.source_id]:
                raise ActionError(i, "device is unchanged")
            device[a.source_id] = a.device_id
        elif a.type is ActionType.SIMULATED_TRANSFER:
            if a.source_id not in balance:
                raise ActionError(i, f"{a.source_id} is not an account this scenario controls")
            if a.target_id not in balance and not is_external(a.target_id):
                raise ActionError(i, f"{a.target_id} does not exist yet")
            if a.source_id == a.target_id:
                raise ActionError(i, "transfer to self")
            if a.amount_cents > balance[a.source_id]:
                raise ActionError(i, f"{a.source_id} has {balance[a.source_id]} cents, needs {a.amount_cents}")
            balance[a.source_id] -= a.amount_cents
            if a.target_id in balance:
                balance[a.target_id] += a.amount_cents
            rows.append((t, a.source_id, a.target_id, a.amount_cents, device[a.source_id]))
        # WAIT only advances time.

    txns = [
        Transaction(
            transaction_id=f"{scenario_id}-{i:05d}", from_id=f, to_id=to, amount_cents=amt, timestamp=ts,
            device_id=dev, scenario_id=scenario_id, ground_truth_label=Label.MALICIOUS,
        )
        for i, (ts, f, to, amt, dev) in enumerate(rows)
    ]
    return Scenario(
        scenario_id=scenario_id, template_id=template_id, seed=seed, split=split, malicious_label=True,
        start_ts=start_ts, source_account_id=source_account_id, funding_cents=funding_cents,
        opening_balances_cents={acct: 0 for acct in balance}, initial_devices=initial_devices,
        actions=list(actions), owned_account_ids=sorted(balance), transactions=txns,
    )


def moved_out_cents(scenario: Scenario) -> int:
    """Money that left the scenario's accounts for an external account (cash-out)."""
    owned = set(scenario.owned_account_ids)
    return sum(t.amount_cents for t in scenario.transactions if t.from_id in owned and is_external(t.to_id))
