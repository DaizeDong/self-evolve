"""Assert model diagnostics on disk after the actual run_loop and _step."""
import json
import sys

import pytest
from llmcall import Result
from tools.sie import statemachine as sm
from tools.sie.events import replay
from tools.sie.model_boundary import ProposalBatch
from tools.sie.state import load_state


def uncertain(family):
    result = Result(error='synthetic uncertain execution', outcome='execution_uncertain',
                  effects='possible', execution_started=None, call_id='synthetic-' + family,
                  review_state='unavailable', review_error='synthetic review failure',
                  effective_provider='synthetic-endpoint', effective_model='synthetic-model',
                  model_family=family, model_source='provider_reported',
                  attempts=[{'provider': 'synthetic', 'outcome': 'execution_uncertain',
                             'effects': 'possible', 'execution_started': None}])
    result.evidence = ['synthetic capability evidence']
    return result


def run_review(monkeypatch, tmp_path, answers, expected_calls=('claude', 'codex')):
    run_dir = tmp_path / 'run'
    sandbox = tmp_path / 'sandbox'
    sandbox.mkdir()
    monkeypatch.setattr(sm, '_run_dir', lambda *args: str(run_dir))
    monkeypatch.setattr(sm, 'make_worktree', lambda *args: str(sandbox))
    monkeypatch.setattr(sm, 'run_profile', lambda *args: {'tier': 'A'})
    monkeypatch.setattr(sm, 'select_parent', lambda *args: None)
    monkeypatch.setattr(sm, 'reflect', lambda *args, **kwargs: [{'synthetic': True}])
    monkeypatch.setattr(sm, 'check', lambda *args: True)
    proposed = []
    def propose(*args, **kwargs):
        proposed.append(True)
        return ProposalBatch([{'file_rel': 'synthetic.py', 'new_content': 'value = 2\n'}],
                             model_result={'call_id': 'synthetic-proposal'}, fallback=None)
    monkeypatch.setattr(sm, 'propose', propose)
    patched = []
    def patch(*args, **kwargs):
        patched.append(True)
        return {'status': 'REJECTED', 'reason': 'synthetic deterministic patch gate'}
    monkeypatch.setattr(sm, 'apply_patch', patch)
    calls = []
    def call(*args, **kwargs):
        family = kwargs['selection'].family
        calls.append(family)
        assert kwargs['requirements'].replay == 'never_after_start'
        return answers[family]
    monkeypatch.setattr(sys.modules['llmcall'], 'call', call)
    summary = sm.run_loop(str(sandbox), 'synthetic-ref', 'synthetic-run',
                          max_rounds=1, proposer='llm', dual=True)
    events = [json.loads(line) for line in (run_dir / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    review = next(event for event in events if event['type'] == 'DUAL_REVIEW')
    records = [json.loads(line) for line in (run_dir / 'proposals.jsonl').read_text(encoding='utf-8').splitlines()]
    assert replay(str(run_dir)) == load_state(str(run_dir))
    assert calls == list(expected_calls)
    assert len(proposed) == 1
    assert summary['accepted_versions'] == []
    return review, records, patched, events


def success(family, verdict='accept'):
    return Result(provider='synthetic', text=json.dumps({'verdict': verdict}),
                  outcome='success', model_family=family, model_source='provider_reported',
                  call_id='synthetic-' + family)


@pytest.mark.parametrize('available,phase', [(0, 'unavailable'), (1, 'degraded'), (2, 'complete')])
def test_dual_review_persists_failure_evidence(monkeypatch, tmp_path, available, phase):
    answers = {family: success(family) if index < available else uncertain(family)
               for index, family in enumerate(('claude', 'codex'))}
    event, _, patched, _ = run_review(monkeypatch, tmp_path, answers)
    assert event['model_phase'] == phase
    assert len(patched) == 1  # unavailable advisory review still reaches deterministic gate
    for family, result in answers.items():
        if result.error:
            failure = event['failures'][family]
            for key in ('error', 'outcome', 'effects', 'execution_started', 'review_state',
                        'review_error', 'attempts', 'evidence', 'model_family', 'model_source',
                        'effective_provider', 'effective_model', 'call_id'):
                assert failure[key] == getattr(result, key)
            assert not failure['metadata_truncated']
        else:
            assert family not in event['failures']


def test_one_proposal_has_one_record(monkeypatch, tmp_path):
    _, records, _, _ = run_review(monkeypatch, tmp_path, {family: uncertain(family) for family in ('claude', 'codex')})
    assert len(records) == 1
    assert records[0]['model_result']['call_id'] == 'synthetic-proposal'


def test_dual_review_bounds_failure_metadata(monkeypatch, tmp_path):
    answers = {family: uncertain(family) for family in ('claude', 'codex')}
    for answer in answers.values():
        answer.attempts *= 100
        answer.evidence = ['synthetic-' + 'x' * 50000] * 100
    event, _, _, _ = run_review(monkeypatch, tmp_path, answers)
    assert event['model_phase'] == 'unavailable'
    assert len(json.dumps(event)) < 50000
    for failure in event['failures'].values():
        assert failure['metadata_truncated']
        assert failure['attempts_total'] == 100
        assert failure['evidence_total'] == 100
        assert failure['effects'] == 'possible'
        assert failure['execution_started'] is None
        assert failure['call_id'].startswith('synthetic-')


def test_invalid_verdict_is_explicitly_unavailable(monkeypatch, tmp_path):
    event, _, patched, _ = run_review(monkeypatch, tmp_path, {family: success(family, 'invalid') for family in ('claude', 'codex')})
    assert event['model_phase'] == 'unavailable'
    assert len(patched) == 1
    assert all(failure['error'] == 'invalid or unavailable review verdict' for failure in event['failures'].values())


def test_two_rejects_keep_advisory_policy(monkeypatch, tmp_path):
    event, _, patched, events = run_review(monkeypatch, tmp_path, {family: success(family, 'reject') for family in ('claude', 'codex')})
    assert event['model_phase'] == 'complete'
    assert event['agree'] is True
    assert not patched
    assert events[-1]['type'] == 'STATIC_REJECT' and events[-1]['phase'] == 'REVIEW'


def test_nested_failure_metadata_has_total_bound(monkeypatch, tmp_path):
    answers = {family: uncertain(family) for family in ('claude', 'codex')}
    nested = 123456789
    for _ in range(4):
        nested = [nested] * 16
    for answer in answers.values():
        answer.evidence = nested
    event, _, _, _ = run_review(monkeypatch, tmp_path, answers)
    assert len(json.dumps(event)) < 50000
    assert all(failure['metadata_truncated'] for failure in event['failures'].values())


def test_missing_review_metadata_is_not_clean(monkeypatch, tmp_path):
    from tools.sie import agents
    monkeypatch.setattr(agents, 'cross_check_verdicts', lambda *args, **kwargs: {})
    event, _, patched, _ = run_review(monkeypatch, tmp_path, {}, expected_calls=())
    assert event['model_phase'] == 'unavailable'
    assert len(patched) == 1
    for failure in event['failures'].values():
        assert failure['error'] == 'invalid or unavailable review verdict'
        assert failure['effects'] == 'unknown'
        assert failure['execution_started'] is None
        assert failure['review_state'] == 'unavailable'
        assert failure['call_id'] is None
