"""Integration checks for PR #7's factory, routes, and response-store lifecycle."""
import os
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from sentinel.agents.red import FixtureRedPolicy
from sentinel.api.app import create_app
from sentinel.llm import adapter as llm


def test_dotenv_selects_red_before_policy_is_constructed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('SENTINEL_RED=fixture\nSENTINEL_LLM_MODE=fixture\n')
    with patch.dict(os.environ, {}, clear=True):
        with TestClient(create_app(str(tmp_path / 'app.db'))) as client:
            lab = client.post('/labs', json={'seed': 7, 'account_count': 10}).json()['lab_id']
            run = client.post(f'/labs/{lab}/red-runs', json={}).json()
            assert run['turns'] == 1 and run['bypass'] is not None
            assert run['history'] == []  # fixture candidates have no heuristic recipe


def test_unknown_red_from_dotenv_fails_during_app_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text('SENTINEL_RED=unknown\nSENTINEL_LLM_MODE=fixture\n')
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match='SENTINEL_RED'):
            create_app(str(tmp_path / 'app.db'))


def test_timeline_and_world_routes_have_distinct_contracts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SENTINEL_LLM_MODE', 'fixture')
    with TestClient(create_app(str(tmp_path / 'app.db'), red_policy=FixtureRedPolicy())) as client:
        routes = [(r.path, method) for r in client.app.routes for method in getattr(r, 'methods', [])]
        assert len(routes) == len(set(routes))
        lab = client.post('/labs', json={'seed': 7, 'account_count': 10}).json()['lab_id']
        run = client.post(f'/labs/{lab}/red-runs', json={}).json()
        timeline = client.get(f'/labs/{lab}/timeline', params={'run_id': run['run_id']})
        assert timeline.status_code == 200
        assert 'nodes' in timeline.json() and 'transfers' in timeline.json()
        assert 'transactions' not in timeline.json()
        world = client.get(f'/labs/{lab}/world')
        assert world.status_code == 200
        assert 'accounts' in world.json() and 'transactions' in world.json()
        other = client.post('/labs', json={'seed': 8, 'account_count': 10}).json()['lab_id']
        assert client.get(f'/labs/{other}/timeline', params={'run_id': run['run_id']}).status_code == 404


def test_response_store_closes_every_connection_and_rolls_back(tmp_path, monkeypatch):
    real_connect, opened = sqlite3.connect, []
    def connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        opened.append(db)
        return db
    monkeypatch.setattr(llm.sqlite3, 'connect', connect)
    path = tmp_path / 'responses.db'
    store = llm.ResponseStore(path)
    store.append('key', {'test': True}, {'answer': 1})
    assert len(store.attempts('key')) == 1
    assert len(store.export()) == 1
    with pytest.raises(RuntimeError, match='rollback'):
        with llm._db(path) as db:
            db.execute('DELETE FROM llm_attempts')
            raise RuntimeError('rollback')
    assert len(store.export()) == 1
    for db in opened:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
