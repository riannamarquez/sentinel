import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from sentinel.api.app import create_app
from sentinel.api.store import Store
from sentinel.detector.baseline import BASELINE_V1
from sentinel.fixtures import load_golden_patch
from sentinel.llm.adapter import Adapter, AdapterError, ReplayAdapter, ResponseStore
from sentinel.replay import verify
from sentinel.schemas import EvaluationReport
from sentinel.agents.blue import BlueProposal

CONFIG = {'seed': 7, 'account_count': 10, 'holdout_benign_n': 40, 'holdout_attack_copies': 2}


def await_human(client, lab):
    red = client.post(f'/labs/{lab}/red-runs', json={}).json()
    rid = red['run_id']
    patches = client.post(f'/labs/{lab}/patches', json={'run_id': rid, 'bypass_id': red['bypass']['bypass_id']}).json()
    response = client.post(f'/labs/{lab}/evaluations', json={'run_id': rid, 'patch_id': patches['patches'][0]['patch']['patch_id']})
    assert response.status_code == 201, response.text
    return rid, response.json()


def test_approval_survives_crash_and_resumes_on_restart(tmp_path, monkeypatch):
    path = str(tmp_path / 'app.db')
    app = create_app(path)
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        rid, report = await_human(client, lab)
        def crash(*args):
            raise RuntimeError('simulated crash after decision commit')
        monkeypatch.setattr(app.state.store, 'complete_decision', crash)
        response = client.post(f'/labs/{lab}/approvals', json={'report_id': report['report_id'], 'decision': 'approve'})
        assert response.status_code == 200
        assert response.json()['completion_pending']
        assert app.state.store.run(rid)['state'] == 'apply_new_version'
        assert app.state.store.lab(lab)['active_version'] == 2
    with TestClient(create_app(path)) as client:
        run = client.get(f'/runs/{rid}').json()
        assert run['state'] == 'complete' and run['rechallenge']['detector_version'] == 2
        assert len(client.get(f'/labs/{lab}').json()['versions']) == 2
        retry = client.post(f'/labs/{lab}/approvals', json={'report_id': report['report_id'], 'decision': 'approve'})
        assert retry.status_code == 200 and not retry.json()['completion_pending']


def test_simultaneous_identical_approvals_commit_once(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / 'app.db'))
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        rid, report = await_human(client, lab)
        barrier = threading.Barrier(2)
        original = app.state.store.decide
        def simultaneous(*args):
            barrier.wait(timeout=5)
            return original(*args)
        monkeypatch.setattr(app.state.store, 'decide', simultaneous)
        def approve(_):
            return client.post(f'/labs/{lab}/approvals', json={'report_id': report['report_id'], 'decision': 'approve'})
        with ThreadPoolExecutor(2) as executor:
            responses = list(executor.map(approve, range(2)))
        assert [r.status_code for r in responses] == [200, 200]
        assert responses[0].json()['event_id'] == responses[1].json()['event_id']
        events = client.get(f'/runs/{rid}').json()['events']
        assert sum(e['action'] == 'approve' for e in events) == 1
        assert sum(e['action'] == 'enter:complete' for e in events) == 1


def test_rechallenge_uses_decision_version_even_after_another_approval(tmp_path):
    app = create_app(str(tmp_path / 'app.db'))
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        rejected_run, rejected = await_human(client, lab)
        _, approved = await_human(client, lab)
        app.state.store.decide(lab, EvaluationReport.model_validate(rejected), 'reject', None)
        assert app.state.store.pending_completions(rejected_run)[0]['detector_version'] == 1
        assert client.post(f'/labs/{lab}/approvals', json={'report_id': approved['report_id'], 'decision': 'approve'}).status_code == 200
        response = client.post(f'/labs/{lab}/approvals', json={'report_id': rejected['report_id'], 'decision': 'reject'})
        assert response.status_code == 200
        assert response.json()['active_version'] == 2
        assert response.json()['rechallenge']['detector_version'] == 1
        assert response.json()['rechallenge']['alert'] is False


def test_replay_keeps_repeated_patch_ids_with_their_run(tmp_path):
    calls = []
    def transport(request):
        patch = load_golden_patch().model_dump(mode='json')
        patch['all_of'][0]['threshold'] = 4 if not calls else 3
        calls.append(request)
        return {'patches': [patch]}
    app = create_app(str(tmp_path / 'app.db'), adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')))
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        for _ in range(2):
            _, report = await_human(client, lab)
            assert client.post(f'/labs/{lab}/approvals', json={'report_id': report['report_id'], 'decision': 'reject'}).status_code == 200
        # A third run has not called Blue and must not cause a replay miss.
        client.post(f'/labs/{lab}/red-runs', json={})
        bundle = client.get(f'/labs/{lab}/replay').json()
    assert verify(bundle) == {'reports_verified': 2, 'bypasses_verified': 3}
    swapped = copy.deepcopy(bundle)
    swapped['runs'][1]['patches'] = swapped['runs'][0]['patches']
    swapped['patches'] = [p['patch'] for r in swapped['runs'] for p in r['patches']]
    with pytest.raises(ValueError, match='candidate rules'):
        verify(swapped)


def test_export_reads_one_snapshot_while_writer_commits(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / 'app.db'))
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        rid = client.post(f'/labs/{lab}/red-runs', json={}).json()['run_id']
        reader, writer = app.state.store, Store(tmp_path / 'app.db')
        original_connect = reader._connect
        fired = []
        def connect():
            db = original_connect()
            def on_query(sql):
                if sql.startswith('SELECT * FROM runs') and not fired:
                    fired.append(True)
                    writer.save_patch(rid, load_golden_patch(), None)
            db.set_trace_callback(on_query)
            return db
        monkeypatch.setattr(reader, '_connect', connect)
        snapshot = reader.export_lab(lab)
        assert fired and snapshot['patches'] == []
        assert writer.run_artifacts(rid)['patches']


def test_invalid_red_candidate_does_not_shift_bypass_rationale(tmp_path):
    from sentinel.agents import red
    valid = red.FixtureRedPolicy().propose(objective_cents=300000, rules=BASELINE_V1, turn=1,
                                           history=[], seed=7, run_id="run-000001")[0]
    invalid = replace(valid, funding_cents=1, rationale='invalid candidate')
    valid = replace(valid, rationale='valid candidate evidence')

    class TwoCandidates:
        def propose(self, **kwargs):
            return [invalid, valid]

    with TestClient(create_app(str(tmp_path / 'app.db'), red_policy=TwoCandidates())) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        response = client.post(f'/labs/{lab}/red-runs', json={})
        assert response.status_code == 201
        assert response.json()['bypass']['rationale'] == 'valid candidate evidence'
        assert response.json()['bypass']['scenario']['scenario_id'].endswith('.c1')


def test_permanent_provider_error_is_not_retried(tmp_path):
    calls = []
    store = ResponseStore(tmp_path / 'llm.db')
    def transport(request):
        calls.append(request)
        raise HTTPError('https://example.com', 401, 'private error', {}, None)
    with pytest.raises(AdapterError):
        Adapter(transport, store, sleep=lambda _: None).propose('blue', {}, BlueProposal)
    assert len(calls) == 1
    assert store.export()[0]['error'] == 'permanent_provider_error'
    with pytest.raises(AdapterError):
        ReplayAdapter(store).propose('blue', {}, BlueProposal)


def test_deadline_covers_validation_and_transport_retries(tmp_path):
    now, calls = [0.0], []
    def transport(request):
        calls.append(request)
        now[0] += 0.6
        return {}  # invalid output
    store = ResponseStore(tmp_path / 'llm.db')
    adapter = Adapter(transport, store, timeout_seconds=1, clock=lambda: now[0])
    with pytest.raises(AdapterError, match='deadline'):
        adapter.propose('blue', {}, BlueProposal)
    assert len(calls) == 2
    assert store.export()[-1]['error'] == 'deadline_exceeded'


def test_background_admission_rejects_excess_work_without_changing_state(tmp_path):
    release = threading.Event()
    started = threading.Barrier(3)
    call_lock, call_count = threading.Lock(), [0]
    def transport(request):
        with call_lock:
            call_count[0] += 1
            initial = call_count[0] <= 2
        if initial:
            started.wait(timeout=5)
        assert release.wait(5)
        return {'patches': [load_golden_patch().model_dump(mode='json')]}
    app = create_app(str(tmp_path / 'app.db'), adapter=Adapter(transport, ResponseStore(tmp_path / 'llm.db')))
    with TestClient(app) as client:
        lab = client.post('/labs', json=CONFIG).json()['lab_id']
        attempts = [client.post(f'/labs/{lab}/red-runs', json={}).json() for _ in range(5)]
        try:
            for attempt in attempts[:4]:
                response = client.post(f'/labs/{lab}/patches?background=true', json={
                    'run_id': attempt['run_id'], 'bypass_id': attempt['bypass']['bypass_id']})
                assert response.status_code == 202
            started.wait(timeout=5)
            response = client.post(f'/labs/{lab}/patches?background=true', json={
                'run_id': attempts[4]['run_id'], 'bypass_id': attempts[4]['bypass']['bypass_id']})
            assert response.status_code == 503 and response.headers['Retry-After'] == '1'
            assert app.state.store.run(attempts[4]['run_id'])['state'] == 'measure_outcome'
            sync = client.post(f'/labs/{lab}/patches', json={
                'run_id': attempts[4]['run_id'], 'bypass_id': attempts[4]['bypass']['bypass_id']})
            assert sync.status_code == 503
        finally:
            release.set()
        for attempt in attempts[:4]:
            events = client.get(f"/runs/{attempt['run_id']}/events")
            assert 'enter:validate_patch' in events.text
        retry = client.post(f'/labs/{lab}/patches', json={
            'run_id': attempts[4]['run_id'], 'bypass_id': attempts[4]['bypass']['bypass_id']})
        assert retry.status_code == 201



def test_transient_provider_failure_retries_and_replays_success(tmp_path):
    calls, delays = [], []
    store = ResponseStore(tmp_path / 'llm.db')
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError('https://example.com', 503, 'unavailable', {}, None)
        return {'patches': [load_golden_patch().model_dump(mode='json')]}
    result = Adapter(transport, store, sleep=delays.append).propose('blue', {}, BlueProposal)
    assert len(calls) == 2 and delays == [0.5]
    assert ReplayAdapter(store).propose('blue', {}, BlueProposal) == result


def test_transport_backoff_is_included_in_overall_deadline(tmp_path):
    now, calls = [0.0], []
    def transport(request):
        calls.append(request)
        now[0] += 0.6
        raise HTTPError('https://example.com', 503, 'unavailable', {}, None)
    def sleep(delay):
        now[0] += delay
    adapter = Adapter(transport, ResponseStore(tmp_path / 'llm.db'), timeout_seconds=1,
                      clock=lambda: now[0], sleep=sleep)
    with pytest.raises(AdapterError, match='deadline'):
        adapter.propose('blue', {}, BlueProposal)
    assert len(calls) == 1


def test_job_admission_checks_state_inside_claim_transaction(tmp_path):
    from sentinel.api.states import RunState as S
    from sentinel.api.store import Conflict
    from sentinel.schemas import BankConfig
    store = Store(tmp_path / 'app.db')
    lab = store.create_lab(BankConfig(seed=7), {}, BASELINE_V1)
    run = store.create_run(lab)
    store.transition(run, S.GENERATE_WORLD)
    with pytest.raises(Conflict, match='invalid_state'):
        store.claim_job(run, S.INITIALIZE_LAB)
    assert not store.job_running(run)
    assert store.run(run)['state'] == S.GENERATE_WORLD
