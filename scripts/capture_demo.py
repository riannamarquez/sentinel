"""Capture real, isolated fixture-policy rounds for the offline presentation."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sentinel.agents.red import FixtureRedPolicy
from sentinel.api.app import create_app


def capture(decision):
    with TemporaryDirectory() as directory:
        with TestClient(create_app(str(Path(directory) / 'demo.db'), red_policy=FixtureRedPolicy())) as client:
            def request(path, body=None):
                response = client.post(path, json=body) if body is not None else client.get(path)
                response.raise_for_status()
                return response.json()
            lab = request('/labs', {'seed': 7, 'account_count': 200})
            base = '/labs/' + lab['lab_id']
            baseline = request(base + '/baseline', {})
            red = request(base + '/red-runs', {})
            patches = request(base + '/patches', {'run_id': red['run_id'], 'bypass_id': red['bypass']['bypass_id']})
            patch = next(p['patch'] for p in patches['patches'] if p['valid'])
            report = request(base + '/evaluations', {'run_id': red['run_id'], 'patch_id': patch['patch_id']})
            approval = request(base + '/approvals', {'report_id': report['report_id'], 'decision': decision})
            run = request('/runs/' + red['run_id'])
            assert run['state'] == 'complete'
            assert report['eligible_for_approval']
            assert all(gate['passed'] for gate in report['gate_results'])
            assert approval['active_version'] == (2 if decision == 'approve' else 1)
            assert approval['rechallenge']['alert'] is (decision == 'approve')
            return dict(lab=lab, baseline=baseline, red=red, patch=patch, report=report, approval=approval, run=run)


if __name__ == '__main__':
    os.environ['SENTINEL_LLM_MODE'] = 'fixture'
    result = {decision: capture(decision) for decision in ('approve', 'reject')}
    target = Path(__file__).resolve().parents[1] / 'web/app/demo/capture.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Captured both decision branches: {target}')
