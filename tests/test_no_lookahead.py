"""Appending future transactions never changes past detections (design-v2 §5.3)."""
import pytest

from sentinel.detector.score import score, timeline
from sentinel.fixtures import load_golden
from sentinel.schemas import Label, Split, Transaction

GOLDEN = ("caught_fraud", "missed_fraud_slow_variant", "legit_lookalike")


def future_noise(scenario, after_ts: int) -> list[Transaction]:
    """Transactions that would fire every rule if a feature could see them: big, fast, many hops."""
    owned = scenario.owned_account_ids
    out = []
    for i in range(12):
        src = owned[i % len(owned)]
        dst = owned[(i + 1) % len(owned)] if len(owned) > 1 else "EXT-x"
        out.append(Transaction(
            transaction_id=f"zz-future-{i:03d}", from_id=src, to_id=dst, amount_cents=900_000,
            timestamp=after_ts + 60 * (i + 1), device_id=f"{src}-new", scenario_id=scenario.scenario_id,
            ground_truth_label=Label.MALICIOUS,
        ))
        out.append(Transaction(
            transaction_id=f"zz-in-{i:03d}", from_id="EXT-source", to_id=src, amount_cents=900_000,
            timestamp=after_ts + 60 * (i + 1), scenario_id=scenario.scenario_id, ground_truth_label=Label.MALICIOUS,
        ))
    return out


def scenarios_under_test(fixture_splits):
    yield from (load_golden(name)[0] for name in GOLDEN)
    for split in Split:
        yield from fixture_splits[split][:3]
        yield from [s for s in fixture_splits[split] if s.malicious_label][:3]


def test_appending_future_transactions_never_changes_past_detections(fixture_splits, candidate_rules):
    checked = noise_fired = 0
    for scenario in scenarios_under_test(fixture_splits):
        txns = scenario.transactions
        for cut in sorted({len(txns) // 4, len(txns) // 2, 3 * len(txns) // 4}):
            if cut == 0:
                continue
            cut_ts = txns[cut - 1].timestamp
            prefix = [t for t in txns if t.timestamp <= cut_ts]
            past = scenario.model_copy(update={"transactions": prefix})
            appended = sorted([*txns, *future_noise(scenario, txns[-1].timestamp)],
                              key=lambda t: (t.timestamp, t.transaction_id))
            future = scenario.model_copy(update={"transactions": appended})
            before = timeline(past, candidate_rules)
            full = timeline(future, candidate_rules)
            assert before == full[:len(before)], f"{scenario.scenario_id}: detections up to t={cut_ts} changed"
            noise_fired += any(fired for _, fired in full[len(before):])
            checked += 1
    assert checked > 20
    assert noise_fired > 0  # the appended transactions do fire rules once they are in the past


@pytest.mark.parametrize("name", GOLDEN)
def test_alert_reproduces_with_trace_cut_at_alert_time(name, candidate_rules):
    scenario, _ = load_golden(name)
    d = score(scenario, candidate_rules)
    if d.alert:
        cut = scenario.model_copy(update={
            "transactions": [t for t in scenario.transactions if t.timestamp <= d.first_alert_time]})
        assert score(cut, candidate_rules) == d
