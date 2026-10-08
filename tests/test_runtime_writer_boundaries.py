"""Direct writers must prove the destination's governing PRIVATE repository."""
import json
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import repair_samples, runtime_samples
from test_runtime_private import private_home


@pytest.mark.parametrize('writer', ['profile', 'queue', 'event', 'state'])
@pytest.mark.parametrize('visibility', ['PUBLIC', 'UNKNOWN'])
def test_direct_writers_refuse_nested_repository(private_home, writer, visibility):
    from tools.sie import events, gate_human, profile, state
    data, proof, sample = private_home
    nested = data/'nested'
    nested.mkdir()
    subprocess.run(['git', 'init', '-q', str(nested)], check=True)
    subprocess.run(['git', '-C', str(nested), 'remote', 'add', 'origin', sample['nested_origin']], check=True)
    proof.write_text(json.dumps({'_refreshed': sample['fresh'], sample['slug']: 'PRIVATE',
                                 sample['nested_slug']: visibility}), encoding='utf-8')
    destination = nested/'untouched'
    payload = repair_samples()
    writes = {
        'profile': lambda: profile.freeze_target(str(destination), payload['profile']),
        'queue': lambda: gate_human.enqueue(str(destination), payload['action']),
        'event': lambda: events.append_event(str(destination), payload['action']),
        'state': lambda: state.save_state(state.RunState('synthetic', 'INIT', 0, None, ''), str(destination)),
    }
    with pytest.raises(RuntimeError):
        writes[writer]()
    assert not destination.exists()


def test_direct_writers_keep_private_payloads(private_home):
    from tools.sie import gate_human, profile
    data, _, _ = private_home
    destination = data/'targets'/'synthetic'/'runs'/'run'
    sample = repair_samples()
    profile.freeze_target(str(destination), sample['profile'])
    assert profile.load_target(str(destination)) == sample['profile']
    aid = gate_human.enqueue(str(destination), sample['action'])
    queued = gate_human.pending(str(destination))
    assert queued[0]['aid'] == aid and queued[0]['payload'] == sample['action']['payload']
    gate_human.resolve(str(destination), aid, 'approved')
    assert gate_human.pending(str(destination)) == []


def test_profile_without_run_directory_keeps_holdout_private(private_home, tmp_path, monkeypatch):
    from tools.sie import anchors, profile
    from tools.sie.probes import fact_probe
    data, _, _ = private_home
    sample = repair_samples()
    target = tmp_path/'target'
    target.mkdir()
    monkeypatch.setattr(profile, '_exec_signal', lambda *a: None)
    monkeypatch.setattr(fact_probe, 'probe', lambda *a: {'tier_signal': 'B', 'anchor_count': 30, 'evidence': {}})
    monkeypatch.setattr(fact_probe, '_find_artifacts', lambda *a: ['synthetic.json'])
    monkeypatch.setattr(anchors, 'extract_anchors', lambda *a: sample['anchors'])
    result = profile.run_profile(str(target), sample['profile']['base_ref'])
    holdout = Path(result['anchors_holdout_ref']['path'])
    assert holdout.is_relative_to(data)
    assert json.loads(holdout.read_text(encoding='utf-8'))
    assert not (target/'_run').exists()
