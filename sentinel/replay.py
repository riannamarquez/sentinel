"""Verify a version-2 lab snapshot without a network transport.

Usage: python -m sentinel.replay lab.json
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from sentinel.agents import blue
from sentinel.detector.patches import apply_patch
from sentinel.detector.score import score
from sentinel.eval.evaluator import evaluate
from sentinel.llm.adapter import ReplayAdapter, ResponseStore
from sentinel.scenarios.factory import build_splits, attack_scenario
from sentinel.schemas import BankConfig, BypassTrace, EvaluationReport, Rule, RulePatch, Split, sha256_of
from sentinel.sim.actions import moved_out_cents


def verify(bundle):
    if bundle['format_version'] != 2:
        raise ValueError('Export a new version-2 bundle to preserve run ownership')
    config = BankConfig.model_validate(bundle['lab']['config'])
    versions = {v['version']: [Rule.model_validate(r) for r in v['rules']] for v in bundle['versions']}
    runs = bundle['runs']
    if len({r['run_id'] for r in runs}) != len(runs):
        raise ValueError('Duplicate run ID')
    # Reject disagreement between the playback views and the authoritative nested artifacts.
    expected = dict(bypasses=[b for r in runs for b in r['bypasses']],
                    patches=[p['patch'] for r in runs for p in r['patches']],
                    reports=[p for r in runs for p in r['reports']],
                    approvals=[a for r in runs for a in r['approvals']],
                    rechallenges=[r['rechallenge'] for r in runs if r['rechallenge']])
    for name, items in expected.items():
        if bundle[name] != items:
            raise ValueError(f'Artifacts missing or altered: {name}')
    checked, bypasses_checked = 0, 0
    splits = None
    with tempfile.TemporaryDirectory() as directory:
        recordings = ResponseStore(Path(directory) / 'responses.db')
        for row in bundle.get('llm_recordings', []):
            if sha256_of(row['request']) != row['input_hash']:
                raise ValueError('LLM recording input hash mismatch')
            recordings.append(row['input_hash'], row['request'], row['response'], row['error'])
        adapter = ReplayAdapter(recordings, model=bundle.get('llm_model', 'configured'))
        for run in runs:
            if run['lab_id'] != bundle['lab']['lab_id']:
                raise ValueError('Run belongs to another lab')
            patches = {p['patch']['patch_id']: p for p in run['patches']}
            if len(patches) != len(run['patches']):
                raise ValueError('Duplicate patch ID within run')
            for raw in run['reports']:
                report = EvaluationReport.model_validate(raw)
                if report.run_id != run['run_id'] or report.baseline_version != run['base_version']:
                    raise ValueError('Report belongs to another run or base version')
                entry = patches.get(report.patch_id)
                if entry is None or entry['error'] is not None:
                    raise ValueError('Report patch missing or rejected in this run')
                patch = RulePatch.model_validate(entry['patch'])
                if patch.base_version != report.baseline_version:
                    raise ValueError('Patch base version mismatch')
                rules = versions[report.baseline_version]
                candidate = apply_patch(rules, patch)
                if sha256_of(candidate) != report.candidate_rules_hash:
                    raise ValueError('Report candidate rules missing or altered')
                if splits is None:
                    splits = build_splits(config.seed, config.holdout_benign_n, config.holdout_attack_copies)
                actual = evaluate(report_id=report.report_id, run_id=report.run_id, patch_id=report.patch_id,
                                  splits=splits, baseline_rules=rules, baseline_version=report.baseline_version,
                                  candidate_rules=candidate)
                if actual != report:
                    raise ValueError('Evaluation replay mismatch')
                checked += 1
            for raw in run['bypasses']:
                trace = BypassTrace.model_validate(raw)
                if trace.detector_version != run['base_version']:
                    raise ValueError('Bypass base version mismatch')
                rules = versions[trace.detector_version]
                moved = moved_out_cents(trace.scenario)
                if score(trace.scenario, rules).alert or moved != trace.moved_cents or moved < trace.objective_cents:
                    raise ValueError('Recorded bypass no longer meets its objective')
                # An unfinished run may not have called Blue yet.
                if run.get('blue_history') and bundle.get('llm_mode', 'fixture') != 'fixture':
                    if splits is None:
                        splits = build_splits(config.seed, config.holdout_benign_n, config.holdout_attack_copies)
                    repair = blue.run_repair(trace, rules, trace.detector_version, adapter=adapter,
                        development={split: splits[split] for split in (Split.SEARCH, Split.REGRESSION)},
                        replay_turn_limit=len(run['blue_history']))
                    if [h.model_dump(mode='json') for h in repair.history] != run['blue_history']:
                        raise ValueError('Blue tool feedback replay mismatch')
                    proposed = [repair.selected] if repair.selected else []
                    if proposed != [RulePatch.model_validate(p['patch']) for p in run['patches']]:
                        raise ValueError('Blue replay mismatch for this run')
                elif run['patches'] and bundle.get('llm_mode', 'fixture') != 'fixture':
                    proposed = blue.propose(trace, rules, trace.detector_version, adapter=adapter)
                    if proposed != [RulePatch.model_validate(p['patch']) for p in run['patches']]:
                        raise ValueError('Blue replay mismatch for this run')
                bypasses_checked += 1
            if run['rechallenge']:
                if len(run['approvals']) != 1:
                    raise ValueError('Rechallenge has no unique decision')
                decision = run['approvals'][0]
                events = [e for e in bundle['events'] if e['event_id'] == decision['event_id']]
                if len(events) != 1 or events[0]['run_id'] != run['run_id']:
                    raise ValueError('Decision event belongs to another run')
                version = events[0]['version_after']
                fresh = attack_scenario(config.seed, Split.FINAL_HOLDOUT, 'slow_chain_3',
                                        10_000 + int(run['run_id'].split('-')[1]))
                if score(fresh, versions[version], version).model_dump(mode='json') != run['rechallenge']:
                    raise ValueError('Rechallenge replay mismatch')
    return {'reports_verified': checked, 'bypasses_verified': bypasses_checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.bundle.read_text())), sort_keys=True))


if __name__ == '__main__':
    main()
