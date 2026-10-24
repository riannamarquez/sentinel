"""build_timeline against the golden bypass trace and the hand-written frontend contract."""
import json

from sentinel.api.timeline import build_timeline
from sentinel.detector.baseline import BASELINE_V1
from sentinel.fixtures import FIXTURE_DIR, OBJECTIVE_CENTS, load_bypass_trace

ARGS = dict(lab_id="lab-0001", run_id="run-000001", objective_cents=OBJECTIVE_CENTS, background_accounts=40)


def test_v1_misses_the_bypass():
    tl = build_timeline(load_bypass_trace().scenario, BASELINE_V1, version=1, **ARGS)
    assert tl.summary.caught is False
    assert not any(t.rules_fired for t in tl.transfers)


def test_v2_fires_r4_on_the_last_two_hops(candidate_rules):
    tl = build_timeline(load_bypass_trace().scenario, candidate_rules, version=2, **ARGS)
    assert tl.summary.caught is True
    assert [t.rules_fired for t in tl.transfers] == [[]] * (len(tl.transfers) - 2) + [["R4"], ["R4"]]
    assert [(t.from_, t.to) for t in tl.transfers[-2:]] == [("M2", "M3"), ("M3", "EXT-cashout")]


def test_v2_matches_the_frontend_example(candidate_rules):
    tl = build_timeline(load_bypass_trace().scenario, candidate_rules, version=2, **ARGS)
    expected = json.loads((FIXTURE_DIR / "timeline_example.json").read_text())
    assert tl.model_dump(by_alias=True) == expected
