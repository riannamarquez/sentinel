"""Re-score a stored bypass against a chosen rule set. Pure and deterministic: it only calls the
detector's score() and timeline(), so a replay can never disagree with how a run was scored."""
from __future__ import annotations

from collections.abc import Sequence

from sentinel.detector.score import score, timeline
from sentinel.schemas import BypassReplay, BypassTrace, HopReplay, Rule


def replay_bypass(trace: BypassTrace, rules: Sequence[Rule], *, run_id: str, choice: str, label: str,
                  version: int | None, patch_id: str | None = None) -> BypassReplay:
    scenario = trace.scenario
    result = score(scenario, rules, version)
    fired = dict(timeline(scenario, rules))        # transaction_id -> rules firing there (scored only)
    # score() alerts at the first scored transfer where any rule fires; timeline() walks the same views.
    alert_txn = next((tid for tid, ids in fired.items() if ids), None) if result.alert else None

    per_hop = [HopReplay(hop_index=i, transaction_id=t.transaction_id, scored=t.transaction_id in fired,
                         alerted=bool(fired.get(t.transaction_id)), rule_ids=list(fired.get(t.transaction_id, ())))
               for i, t in enumerate(scenario.transactions, start=1)]   # Scenario keeps transactions time-ordered
    alert_hop = next((h.hop_index for h in per_hop if h.transaction_id == alert_txn), None)
    return BypassReplay(
        run_id=run_id, bypass_id=trace.bypass_id, rules=choice, detector_label=label, detector_version=version,
        patch_id=patch_id, alert=result.alert, triggered_rule_ids=result.triggered_rule_ids,
        first_alert_time=result.first_alert_time, alert_transaction_id=alert_txn, alert_hop_index=alert_hop,
        per_hop=per_hop,
    )
