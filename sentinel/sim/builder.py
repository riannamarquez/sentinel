"""Assemble a benign household into a Scenario, enforcing "balance never below 0"."""
from __future__ import annotations

from sentinel.schemas import Label, Scenario, Split, Transaction


class HouseholdBuilder:
    def __init__(self, scenario_id: str, template_id: str, seed: int, split: Split):
        self.scenario_id, self.template_id, self.seed, self.split = scenario_id, template_id, seed, split
        self._raw: list[tuple] = []
        self._opening: dict[str, int] = {}

    def account(self, account_id: str, opening_cents: int) -> str:
        self._opening[account_id] = opening_cents
        return account_id

    def add(self, ts: int, from_id: str, to_id: str, amount_cents: int, device_id: str | None = None):
        assert isinstance(amount_cents, int) and amount_cents > 0, amount_cents
        self._raw.append((ts, len(self._raw), from_id, to_id, amount_cents, device_id))

    def build(self) -> Scenario:
        """Sort by time, then drop any outgoing payment an owned account cannot cover.

        Dropping is deterministic (it depends only on the sorted trace), so the same seed
        always yields the same household. External EXT-* accounts have unlimited funds.
        """
        balance = dict(self._opening)
        kept = []
        for ts, _, f, t, amount, dev in sorted(self._raw):
            if f in balance:
                if balance[f] < amount:
                    continue
                balance[f] -= amount
            if t in balance:
                balance[t] += amount
            kept.append((ts, f, t, amount, dev))
        txns = [
            Transaction(
                transaction_id=f"{self.scenario_id}-{i:05d}", from_id=f, to_id=t, amount_cents=a,
                timestamp=ts, device_id=d, scenario_id=self.scenario_id, ground_truth_label=Label.BENIGN,
            )
            for i, (ts, f, t, a, d) in enumerate(kept)
        ]
        return Scenario(
            scenario_id=self.scenario_id, template_id=self.template_id, seed=self.seed, split=self.split,
            malicious_label=False, opening_balances_cents=dict(self._opening),
            initial_devices={a: f"{a}-d0" for a in self._opening},
            owned_account_ids=sorted(self._opening), transactions=txns,
        )
