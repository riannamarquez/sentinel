"""Blue's measured feedback loop, split boundary, bounded stopping and replay."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from sentinel.agents.blue import run_repair
from sentinel.api.app import create_app
from sentinel.detector.baseline import BASELINE_V1
from sentinel.fixtures import load_bypass_trace, load_golden_patch, load_splits
from sentinel.llm.adapter import Adapter, ResponseStore
from sentinel.replay import verify
from sentinel.schemas import Split


def proposal(patch):
    return {'patches': [patch]}


def golden():
    return load_golden_patch().model_dump(mode='json')


def greedy():
    patch = golden()
    patch['patch_id'] = 'greedy'
    patch['all_of'] = [{'feature_key': 'transfer_amount', 'operator': '>=', 'threshold': 1}]
    return patch


def development():
    splits = load_splits()
    return {s: splits[s] for s in (Split.SEARCH, Split.REGRESSION)}


def test_blue_uses_tool_feedback_to_revise_and_stops_on_success(tmp_path):
    requests = []
    def transport(request):
        requests.append(request)
        if request['inputs']['turn'] == 1:
            assert request['inputs']['development_history'] == []
            return proposal(greedy())
        previous = request['inputs']['development_history'][0]['feedback'][0]
        assert previous['search_after']['fp'] > previous['search_before']['fp']
        assert not previous['acceptable']
        return proposal(golden())
    result = run_repair(load_bypass_trace(), BASELINE_V1, 1, adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')),
                        development=development())
    assert result.selected.patch_id == golden()['patch_id']
    assert len(requests) == len(result.history) == 2
    assert result.history[-1].feedback[0].bypass_caught
    assert result.history[-1].feedback[0].acceptable
    serialized = json.dumps([r['inputs'] for r in requests])
    for forbidden in ('final_holdout', 'ground_truth_label', 'malicious_label', 'template_id'):
        assert forbidden not in serialized


def test_blue_can_repair_a_semantically_invalid_patch(tmp_path):
    requests = []
    bad = golden() | {'operation': 'modify', 'rule_id': 'R999'}
    def transport(request):
        requests.append(request)
        if len(requests) == 1:
            return proposal(bad)
        assert 'unknown rule' in request['inputs']['development_history'][0]['feedback'][0]['error']
        return proposal(golden())
    result = run_repair(load_bypass_trace(), BASELINE_V1, 1, adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')),
                        development=development())
    assert result.selected and len(result.history) == 2


def test_blue_stops_after_three_failed_turns_without_selecting(tmp_path):
    calls = []
    def transport(request):
        calls.append(request)
        return proposal(greedy())
    result = run_repair(load_bypass_trace(), BASELINE_V1, 1, adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')),
                        development=development())
    assert result.selected is None
    assert len(calls) == len(result.history) == 3


def test_blue_rejects_access_to_final_holdout(tmp_path):
    adapter = Adapter(lambda _: pytest.fail('provider must not run'), ResponseStore(tmp_path / 'llm.db'))
    with pytest.raises(ValueError, match='only search and regression'):
        run_repair(load_bypass_trace(), BASELINE_V1, 1, adapter=adapter, development=load_splits())


def test_multi_turn_blue_is_recorded_and_verified_offline(tmp_path, monkeypatch):
    def transport(request):
        return proposal(greedy() if request['inputs']['turn'] == 1 else golden())
    app = create_app(str(tmp_path / 'app.db'), adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')))
    with TestClient(app) as client:
        lab = client.post('/labs', json={'seed': 7, 'account_count': 10, 'holdout_benign_n': 40,
                                        'holdout_attack_copies': 2}).json()['lab_id']
        red = client.post(f'/labs/{lab}/red-runs', json={}).json()
        rid = red['run_id']
        response = client.post(f'/labs/{lab}/patches', json={'run_id': rid, 'bypass_id': red['bypass']['bypass_id']})
        assert response.status_code == 201
        patches = response.json()
        assert len(patches['blue_history']) == 2
        assert len(patches['patches']) == 1
        assert client.get(f'/labs/{lab}/reports').json()['reports'] == []
        assert client.get(f'/labs/{lab}').json()['active_version'] == 1
        report = client.post(f'/labs/{lab}/evaluations', json={'run_id': rid, 'patch_id': patches['patches'][0]['patch']['patch_id']})
        assert report.status_code == 201
        assert client.post(f'/labs/{lab}/approvals', json={'report_id': report.json()['report_id'], 'decision': 'approve'}).status_code == 200
        bundle = client.get(f'/labs/{lab}/replay').json()
        assert len(bundle['llm_recordings']) == 2
        assert len(client.get(f'/runs/{rid}').json()['blue_history']) == 2
    def offline(*args, **kwargs):
        raise AssertionError('replay must not use the network')
    monkeypatch.setattr('socket.socket', offline)
    assert verify(bundle)['reports_verified'] == 1
    altered = copy.deepcopy(bundle)
    altered['runs'][0]['blue_history'][0]['feedback'][0]['acceptable'] = True
    with pytest.raises(ValueError, match='feedback replay mismatch'):
        verify(altered)



def test_failed_repair_does_not_open_holdout_or_activate_a_version(tmp_path):
    app = create_app(str(tmp_path / 'app.db'), adapter=Adapter(lambda _: proposal(greedy()), ResponseStore(tmp_path / 'llm.db')))
    with TestClient(app) as client:
        lab = client.post('/labs', json={'seed': 7, 'account_count': 10, 'holdout_benign_n': 40,
                                        'holdout_attack_copies': 2}).json()['lab_id']
        red = client.post(f'/labs/{lab}/red-runs', json={}).json()
        response = client.post(f'/labs/{lab}/patches', json={'run_id': red['run_id'], 'bypass_id': red['bypass']['bypass_id']})
        assert response.status_code == 201
        assert response.json()['state'] == 'failed'
        assert len(response.json()['blue_history']) == 3
        assert response.json()['patches'] == []
        assert client.get(f'/labs/{lab}/reports').json()['reports'] == []
        assert client.get(f'/labs/{lab}').json()['active_version'] == 1
        assert verify(client.get(f'/labs/{lab}/replay').json())['reports_verified'] == 0
