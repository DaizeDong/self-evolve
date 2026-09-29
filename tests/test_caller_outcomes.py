"""Generator-backed public regressions for caller boundaries and backend evidence."""
import copy
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tools.make_fixtures import caller_contract_samples, runtime_samples
from tools.sie import agents, judges, llm_adapter, propose, reflect, runtime_data, selfboot
from tools.sie import statemachine as sm
from tools.sie.backends import builtin, llm


@pytest.fixture
def sample():
    return caller_contract_samples()


def _stop(*args, **kwargs):
    raise RuntimeError('Synthetic stop after destination validation')


def test_direct_selfboot_refuses_unverified_root_before_writes(tmp_path, monkeypatch):
    root = tmp_path / 'unverified-runs'
    (tmp_path/'.git').write_text(runtime_samples()['invalid_git_marker'], encoding='utf-8')
    monkeypatch.setattr(selfboot, 'make_worktree', _stop)
    with pytest.raises(RuntimeError):
        selfboot.selfboot_init(str(tmp_path), 'HEAD', 'synthetic-run', str(root))
    assert not root.exists()


@pytest.mark.parametrize('run_id', ['../escape', 'nested/run', 'run.'])
def test_direct_selfboot_refuses_invalid_identifier_before_writes(tmp_path, monkeypatch, run_id):
    root = runtime_data.private_root() / tmp_path.name / 'runs'
    monkeypatch.setattr(selfboot, 'make_worktree', _stop)
    with pytest.raises((RuntimeError, ValueError)):
        selfboot.selfboot_init(str(tmp_path), 'HEAD', run_id, str(root))
    assert not root.parent.exists()


@pytest.mark.parametrize('serialized', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_normalization_preserves_present_policy_fields(sample, serialized, failed):
    fields = dict(text='synthetic answer', provider='cc', attempts=sample['failure']['attempts'],
                  error='synthetic failure' if failed else None, **sample['policy'])
    value = fields if serialized else SimpleNamespace(**fields)
    result = llm_adapter.normalize_result(value, serialized=serialized)
    assert result['ok'] is not failed
    for key, expected in sample['policy'].items():
        assert key in result and result[key] == expected


def test_normalization_preserves_null_without_inventing_fields(sample):
    fields = dict(text='synthetic answer', provider='cc', attempts=[], error=None, group=None)
    result = llm_adapter.normalize_result(SimpleNamespace(**fields))
    assert 'group' in result and result['group'] is None
    assert 'crossed' not in result and 'groups_refused' not in result


def test_actual_child_serialization_preserves_policy(sample, monkeypatch, capsys):
    module = SimpleNamespace(call=lambda *a, **k: SimpleNamespace(
        text='synthetic answer', provider='cc', attempts=[], error=None, **sample['policy']))
    monkeypatch.setitem(sys.modules, 'llmcall', module)
    child = Path(llm_adapter.__file__).with_name('llm_agent_child.py')
    monkeypatch.syspath_prepend(str(child.parent))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'prompt': 'Synthetic request'})))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(child), run_name='__main__')
    assert exc.value.code == 0
    result = json.loads(capsys.readouterr().out)
    for key, expected in sample['policy'].items():
        assert result.get(key) == expected


def test_scoring_preserves_policy_evidence(sample, tmp_path, monkeypatch):
    artifact = tmp_path / 'artifact.txt'
    artifact.write_text('Synthetic span', encoding='utf-8')
    from tools.sie import judge_claude
    response = dict(available=True, ok=True, provider='cc', family='claude', attempts=[],
                    raw=json.dumps({'span_scores': [{'span': 'Synthetic span', 'score': 1}]}),
                    error=None, **sample['policy'])
    monkeypatch.setattr(judge_claude, 'invoke_claude_judge', lambda *a, **k: response)
    result = judges.score(str(artifact), [{'span': 'Synthetic span'}], 'claude')
    assert result['available']
    for key, expected in sample['policy'].items():
        assert result.get(key) == expected


@pytest.mark.parametrize('kind', ['code', 'artifact', 'fallback'])
def test_failed_proposal_outcomes_survive_list_api(sample, tmp_path, monkeypatch, kind):
    (tmp_path / sample['code_path']).write_text(sample['code'], encoding='utf-8')
    (tmp_path / sample['artifact_path']).write_text(json.dumps(sample['artifact']), encoding='utf-8')
    outcome = dict(sample['failure'], **sample['policy'])
    monkeypatch.setattr(llm_adapter, 'invoke_agent', lambda *a, **k: copy.deepcopy(outcome))
    monkeypatch.setattr(builtin, 'generate', lambda *a: [])
    if kind == 'artifact':
        result = llm.generate_artifact(str(tmp_path), [], sample['artifact_path'])
    elif kind == 'fallback':
        result = propose.propose(str(tmp_path), [], backend='llm')
    else:
        result = llm.generate(str(tmp_path), [])
    assert isinstance(result, list) and result == []
    assert getattr(result, 'backend_outcomes', []) == [outcome]


def _loop_without_effects(monkeypatch, tmp_path):
    run_dir = runtime_data.private_root() / tmp_path.name / 'private-loop'
    monkeypatch.setattr(sm, '_run_dir', lambda *a: str(run_dir))
    monkeypatch.setattr(sm, 'make_worktree', lambda *a: str(tmp_path))
    monkeypatch.setattr(sm, 'run_profile', lambda *a: {'tier': 'A'})
    monkeypatch.setattr(sm, 'freeze_target', lambda *a: None)
    monkeypatch.setattr(sm, 'select_parent', lambda *a: 'base')
    monkeypatch.setattr(sm, 'check', lambda *a: True)
    return run_dir


def test_loop_persists_reflector_failure_before_fallback(sample, tmp_path, monkeypatch):
    run_dir = _loop_without_effects(monkeypatch, tmp_path)
    monkeypatch.setattr(agents, 'invoke', lambda *a, **k: copy.deepcopy(sample['failure']))
    monkeypatch.setattr(sm, 'propose', lambda *a, **k: [])
    sm.run_loop(str(tmp_path), 'HEAD', 'synthetic-run', max_rounds=1, reflect_mode='parallel')
    rows = [json.loads(line) for line in (run_dir / 'reflections.jsonl').read_text().splitlines()]
    assert rows[0]['backend_outcomes'][0]['attempts'] == sample['failure']['attempts']
    assert rows[0]['backend_outcomes'][0]['error'] == sample['failure']['error']


def test_aggregation_preserves_a_snapshot_of_backend_outcomes(sample):
    failure = dict(sample['failure'], **sample['policy'], findings=[])
    outcomes = [failure]
    expected = copy.deepcopy(outcomes)
    result = reflect.meta_aggregate(outcomes)
    assert result['merged_findings'] == []
    assert result['backend_outcomes'] == expected
    failure['attempts'].clear()
    failure['groups_refused'].clear()
    assert result['backend_outcomes'] == expected


def test_loop_persists_failed_proposer_after_builtin_fallback(sample, tmp_path, monkeypatch):
    run_dir = _loop_without_effects(monkeypatch, tmp_path)
    (tmp_path / sample['code_path']).write_text(sample['code'], encoding='utf-8')
    monkeypatch.setattr(llm_adapter, 'invoke_agent', lambda *a, **k: copy.deepcopy(sample['failure']))
    monkeypatch.setattr(builtin, 'generate', lambda *a: [])
    sm.run_loop(str(tmp_path), 'HEAD', 'synthetic-run', max_rounds=1, proposer='llm')
    rows = [json.loads(line) for line in (run_dir / 'proposals.jsonl').read_text().splitlines()]
    assert rows[0]['backend_outcomes'] == [sample['failure']]


@pytest.mark.parametrize('providers', [('cc', 'claude'), ('cc', 'codexg')])
def test_full_dual_review_uses_actual_independence(sample, tmp_path, monkeypatch, providers):
    run_dir = _loop_without_effects(monkeypatch, tmp_path)
    monkeypatch.setattr(sm, 'propose', lambda *a, **k: [
        {'file_rel': sample['code_path'], 'new_content': sample['code']}])
    replies = iter(providers)
    monkeypatch.setattr(llm_adapter, 'invoke_judge', lambda *a, **k: {
        'ok': True, 'result': '{"verdict":"reject"}', 'provider': next(replies),
        'attempts': [], 'error': None})
    monkeypatch.setattr(sm, 'apply_patch', _stop)
    sm.run_loop(str(tmp_path), 'HEAD', 'synthetic-run', max_rounds=1, proposer='llm', dual=True)
    events = [json.loads(line) for line in (run_dir / 'events.jsonl').read_text().splitlines()]
    review = next(event for event in events if event['type'] == 'DUAL_REVIEW')
    expected = 'independent' if providers[1] == 'codexg' else 'insufficient_independence'
    assert review.get('status') == expected
    assert review['agree'] is (True if expected == 'independent' else None)
    if expected != 'independent':
        assert not any(event['type'] == 'STATIC_REJECT' and event.get('phase') == 'REVIEW'
                       for event in events)


@pytest.mark.parametrize('scheme', ['scp', 'ssh', 'https'])
def test_origin_resolution_never_executes_ssh_config(sample, tmp_path, monkeypatch, scheme):
    config = tmp_path / '.ssh' / 'config'
    config.parent.mkdir()
    config.write_text(sample['ssh_config'], encoding='utf-8')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(subprocess, 'run', _stop)
    remote = {'scp': f"git@{sample['ssh_alias']}:{sample['origin_tail']}",
              'ssh': f"ssh://git@{sample['ssh_alias']}/{sample['origin_tail']}",
              'https': f"https://github.com/{sample['origin_tail']}"}[scheme]
    assert runtime_data._slug(remote) == sample['origin_tail'].removesuffix('.git')


def test_dynamic_ssh_config_is_refused_without_execution(sample, tmp_path, monkeypatch):
    config = tmp_path / '.ssh' / 'config'
    config.parent.mkdir()
    config.write_text(sample['ssh_dynamic'], encoding='utf-8')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(subprocess, 'run', _stop)
    with pytest.raises(runtime_data.DataBoundaryError):
        runtime_data._slug(f"git@{sample['ssh_alias']}:{sample['origin_tail']}")
