"""Selected parents govern comparisons and exact rejection restoration."""
import json
from pathlib import Path

import pytest

from tools.make_fixtures import repair_samples


def _populate(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))


def _business_files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(root).parts}


def test_rejection_restores_full_selected_snapshot(tmp_path):
    from tools.sie.statemachine import _discard_rejected_changes
    sample = repair_samples()
    sandbox, snapshot = tmp_path/'sandbox', tmp_path/'snapshot'
    _populate(snapshot, sample['accepted_tree'])
    _populate(sandbox, sample['rejected_tree'])
    metadata = sandbox/'.git'
    metadata.write_text('Synthetic metadata marker.', encoding='utf-8')
    snapshot_before = _business_files(snapshot)
    _discard_rejected_changes(str(sandbox), str(snapshot))
    assert _business_files(sandbox) == snapshot_before
    assert _business_files(snapshot) == snapshot_before
    assert metadata.read_text(encoding='utf-8') == 'Synthetic metadata marker.'


def _loop(monkeypatch, tmp_path):
    from tools.sie import statemachine as sm
    sample = repair_samples()
    sandbox, target = tmp_path/'sandbox', tmp_path/'target'
    _populate(sandbox, sample['accepted_tree'])
    target.mkdir()
    monkeypatch.setattr(sm, 'make_worktree', lambda *a, **k: str(sandbox))
    monkeypatch.setattr(sm, 'run_profile', lambda *a, **k: {'tier': 'A'})
    monkeypatch.setattr(sm, 'reflect', lambda *a, **k: [{'findings': ['Synthetic finding']}])
    monkeypatch.setattr(sm, 'check', lambda *a, **k: True)
    monkeypatch.setattr(sm, 'propose', lambda *a, **k: [{'file_rel': 'main.py',
                         'new_content': sample['rejected_tree']['main.py']}])
    return sm, sandbox, target, sample


def test_loop_without_baseline_cannot_accept(tmp_path, monkeypatch):
    sm, sandbox, target, sample = _loop(monkeypatch, tmp_path)
    monkeypatch.setattr(sm, '_parent_baseline', lambda *a: None)
    evaluations = []
    monkeypatch.setattr(sm, 'evaluate', lambda *a, **k: evaluations.append(k) or
                        {'paired': [(0.0, 1.0)]*20, 'result': {'dimensions': sample['dimensions']}})
    monkeypatch.setattr(sm, 'decide', lambda *a: {'decision': 'ACCEPT', 'reason': 'Synthetic acceptance'})
    result = sm.run_loop(str(target), 'HEAD', 'synthetic-missing-baseline', max_rounds=3)
    assert result['accepted_versions'] == []
    assert result['halt_reason'] == 'baseline_unavailable'
    assert evaluations == []
    assert _business_files(sandbox) == {k: v.encode() for k, v in sample['accepted_tree'].items()}
    records = [json.loads(x) for x in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    assert records[-1]['type'] == 'BASELINE_UNAVAILABLE'
    assert records[-1]['parent_vid'] == 'base'
    assert records[-1]['baseline_status']


def test_failed_restore_stops_before_another_round(tmp_path, monkeypatch):
    sm, _, target, sample = _loop(monkeypatch, tmp_path)
    monkeypatch.setattr(sm, '_parent_baseline', lambda *a: {'dimensions': sample['dimensions']})
    evaluations = []
    monkeypatch.setattr(sm, 'evaluate', lambda *a, **k: evaluations.append(k) or
                        {'paired': [(1.0, 0.0)], 'result': {'dimensions': sample['dimensions']}})
    def fail_restore(*args):
        raise OSError('Synthetic restoration failure')
    monkeypatch.setattr(sm, '_discard_rejected_changes', fail_restore)
    result = sm.run_loop(str(target), 'HEAD', 'synthetic-restore-failure', max_rounds=3)
    assert result['accepted_versions'] == []
    assert result['halt_reason'] == 'restore_failed'
    assert len(evaluations) == 1
    records = [json.loads(x) for x in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    assert records[-1]['type'] == 'RESTORE_FAILED'
    assert records[-1]['restore_error']['type'] == 'OSError'


@pytest.mark.parametrize('kind', ['empty', 'failed', 'invalid'])
def test_unusable_baseline_has_durable_distinct_status(tmp_path, monkeypatch, kind):
    sm, _, target, sample = _loop(monkeypatch, tmp_path)
    baselines = {'empty': {'dimensions': []},
                 'failed': {'dimensions': sample['dimensions'], 'grader_exit_code': 2},
                 'invalid': {'dimensions': [None]}}
    monkeypatch.setattr(sm, '_parent_baseline', lambda *a: baselines[kind])
    monkeypatch.setattr(sm, 'evaluate', lambda *a, **k: pytest.fail('Unusable baseline reached evaluation'))
    result = sm.run_loop(str(target), 'HEAD', 'synthetic-'+kind, max_rounds=3)
    assert result['accepted_versions'] == [] and result['halt_reason'] == 'baseline_unavailable'
    records = [json.loads(x) for x in (Path(result['run_dir'])/'events.jsonl').read_text().splitlines()]
    assert records[-1]['baseline_status'] == {'empty': 'empty', 'failed': 'grader_failed',
                                             'invalid': 'invalid_dimensions'}[kind]


def test_selected_accepted_parent_and_lineage_survive_rejection(tmp_path, monkeypatch):
    from tools.sie import archive
    sm, sandbox, target, sample = _loop(monkeypatch, tmp_path)
    run_id = 'synthetic-selected-parent'
    run_dir = sm._run_dir(str(target), run_id)
    archive_dir = Path(run_dir)/'archive'
    archive.snapshot_version(str(archive_dir), 'v1', str(sandbox))
    archive.add_version(run_dir, 'v1', sample['dimensions'], 'base')
    _populate(sandbox, sample['rejected_tree'])
    (sandbox/'keep.txt').unlink()
    archive.snapshot_version(str(archive_dir), 'v2', str(sandbox))
    archive.add_version(run_dir, 'v2', sample['dimensions'], 'v1')
    lineage_before = (archive_dir/'lineage.json').read_bytes()
    snapshots_before = {v: _business_files(archive_dir/'versions'/v/'snapshot') for v in ['v1', 'v2']}
    monkeypatch.setattr(sm, 'select_parent', lambda *a: 'v1')
    observations = []
    def reflect(*args, **kwargs):
        observations.append(_business_files(sandbox))
        return [{'findings': ['Synthetic selected-parent finding']}]
    monkeypatch.setattr(sm, 'reflect', reflect)
    monkeypatch.setattr(sm, 'evaluate', lambda *a, **k:
                        {'paired': [(1.0, 0.0)], 'result': {'dimensions': sample['dimensions']}})
    result = sm.run_loop(str(target), 'HEAD', run_id, max_rounds=1)
    assert result['accepted_versions'] == []
    assert observations == [snapshots_before['v1']]
    assert _business_files(sandbox) == snapshots_before['v1']
    assert (archive_dir/'lineage.json').read_bytes() == lineage_before
    assert {v: _business_files(archive_dir/'versions'/v/'snapshot') for v in ['v1', 'v2']} == snapshots_before


def test_parent_task_pairing_tracks_names_and_removed_tasks():
    from tools.sie.evaluate import pair_parent_dimensions
    before = repair_samples()['dimensions']
    assert pair_parent_dimensions(before, list(reversed(before))) == [(0.0, 0.0), (1.0, 1.0)]
    assert pair_parent_dimensions(before, before[:1]) == [(0.0, 0.0), (1.0, 0.0)]
