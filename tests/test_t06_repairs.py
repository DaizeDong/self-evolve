"""Regression cases run only behind the T06 fake-model collection barrier."""
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys

import pytest
from llmcall import Result
from tools.sie import agents, reflect, judge_codex, judges
from tools.sie.backends import llm as proposer

ROOT = Path(__file__).resolve().parents[1]


def uncertain():
    result = Result(error='synthetic uncertain execution', outcome='execution_uncertain',
                  effects='possible', execution_started=None, call_id='synthetic-call',
                  review_state='unavailable', review_error='synthetic review failure',
                  effective_provider='synthetic-endpoint', effective_model='gpt-synthetic',
                  model_family='codex', model_source='provider_reported',
                  attempts=[{'provider': 'codexg', 'outcome': 'execution_uncertain',
                             'effects': 'possible', 'execution_started': None}])
    result.evidence = ['synthetic capability evidence']
    return result


@pytest.mark.parametrize('family,expected', [('claude', 'claude'), ('cc', 'claude'), ('codex', 'codex')])
def test_family_constraint_filters_inherited_chain(monkeypatch, family, expected):
    calls = []
    def answer(prompt, **kw):
        calls.append(kw)
        return Result(provider='cc' if expected == 'claude' else 'codexg', text='answer',
                      model_family=expected, model_source='provider_reported')
    monkeypatch.setattr(sys.modules['llmcall'], 'call', answer)
    assert agents.invoke('synthetic', family=family)['ok']
    assert 'chain' not in calls[0]
    assert calls[0]['selection'].family == expected
    assert calls[0]['selection'].model is None


def test_explicit_route_model_and_context_survive(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sys.modules['llmcall'], 'call', lambda *a, **kw: calls.append(kw) or uncertain())
    agents.invoke('synthetic', family='codex', model='gpt-synthetic', chain=('codexg',),
                  avoid=('claude',), cwd=str(tmp_path), env={'SYNTHETIC': '1'}, effort='high')
    assert calls[0]['chain'] == ('codexg',)
    assert calls[0]['avoid'] == ('claude',)
    assert calls[0]['cwd'] == str(tmp_path)
    assert calls[0]['env'] == {'SYNTHETIC': '1'}
    assert calls[0]['selection'].intent == 'exact'
    assert calls[0]['selection'].model == 'gpt-synthetic'


def assert_evidence(out):
    assert out['outcome'] == 'execution_uncertain'
    assert out['effects'] == 'possible'
    assert out['execution_started'] is None
    assert out['call_id'] == 'synthetic-call'
    assert out['review_state'] == 'unavailable'
    assert out['effective_model'] == 'gpt-synthetic'
    assert out['effective_provider'] == 'synthetic-endpoint'


def test_failure_details_cross_agent_judge_reflection(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules['llmcall'], 'call', lambda *a, **kw: uncertain())
    direct = agents.invoke('synthetic')
    assert_evidence(direct)
    assert direct['attempts'] == uncertain().attempts
    assert direct['evidence'] == uncertain().evidence
    assert_evidence(agents.cross_check('synthetic')['per']['codex'])
    assert_evidence(judge_codex.invoke_codex_judge('synthetic'))
    artifact = tmp_path / 'report.md'
    artifact.write_text('synthetic')
    assert_evidence(judges.score(str(artifact), [], 'codex'))
    one = reflect._reflect_one(str(tmp_path), [{'summary': 'synthetic'}], 0, 'codex')
    assert_evidence(one)
    aggregate = reflect.meta_aggregate([one])
    assert aggregate['model_phase'] == 'unavailable'
    assert_evidence(aggregate['failures'][0])


def test_proposal_failure_has_list_compatibility_and_evidence(monkeypatch, tmp_path, capsys):
    (tmp_path / 'report.json').write_text(json.dumps({'sections': [{'anchors': [{'claim': 'synthetic'}]}]}))
    monkeypatch.setattr(proposer, '_scratch_cwd', lambda: str(tmp_path))
    monkeypatch.setattr(sys.modules['llmcall'], 'call', lambda *a, **kw: uncertain())
    proposals = proposer.generate_artifact(str(tmp_path), [], 'report.json')
    assert isinstance(proposals, list) and proposals == []
    assert_evidence(proposals.model_result)
    assert 'synthetic uncertain execution' in capsys.readouterr().err


def test_builtin_fallback_keeps_model_failure(monkeypatch, tmp_path):
    from tools.sie.model_boundary import ProposalBatch
    from tools.sie.propose import propose
    from tools.sie.backends import builtin
    monkeypatch.setattr(proposer, 'generate', lambda *a: ProposalBatch(model_result=vars(uncertain())))
    monkeypatch.setattr(builtin, 'generate', lambda *a: [{'file_rel': 'synthetic.py'}])
    result = propose(str(tmp_path), [], backend='llm')
    assert result == [{'file_rel': 'synthetic.py'}] and result.fallback == 'builtin'
    assert_evidence(result.model_result)


def test_proposer_consumes_one_total_budget(monkeypatch, tmp_path):
    from types import SimpleNamespace
    times = iter([0, 1, 10, 20])
    monkeypatch.setattr(proposer.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(proposer, '_scratch_cwd', lambda: str(tmp_path))
    budgets = []
    def codec(*a, **kw):
        budgets.append(kw['timeout'])
        return SimpleNamespace(returncode=0, stdout='synthetic prompt', stderr='')
    monkeypatch.setattr(proposer.subprocess, 'run', codec)
    def call(*a, **kw):
        budgets.append(kw['timeout'])
        return Result(provider='synthetic', text='{}')
    monkeypatch.setattr(sys.modules['llmcall'], 'call', call)
    assert proposer._proposal_call('claude-propose.js', '{}', 100).returncode == 0
    assert budgets == [99, 90, 80]


@pytest.mark.parametrize('mode', ['missing', 'old'])
def test_deterministic_cli_does_not_load_model_package(tmp_path, mode):
    code = '''import importlib.abc, json, sys, types
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'llmcall' or fullname.startswith('llmcall.'):
            raise ModuleNotFoundError('synthetic missing llmcall', name=fullname)
sys.meta_path.insert(0, Block())
sys.path.insert(0, sys.argv[1])
from tools.sie import cli, agents
from tools.sie.backends import llm
assert 'llmcall' not in sys.modules
try: cli.main(['--help'])
except SystemExit as e: assert e.code == 0
assert cli.main(['replay', '--target', sys.argv[2], '--run-id', 'synthetic']) == 0
from tools.sie.state import RunState, save_state
save_state(RunState('synthetic', 'INIT', 0, None, 'A'), cli._run_dir(sys.argv[2], 'synthetic'))
assert cli.main(['status', '--target', sys.argv[2], '--run-id', 'synthetic']) == 0
cli.run_loop = lambda *a, **kw: {'synthetic': True}
agents.codex_available = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('deterministic provider probe'))
assert cli.main(['run', '--target', sys.argv[2], '--run-id', 'synthetic']) == 0
assert 'llmcall' not in sys.modules
if sys.argv[3] == 'old': sys.modules['llmcall'] = types.SimpleNamespace(call=lambda *a, **kw: 1)
r = agents.invoke('synthetic', family='codex')
assert not r['ok'] and r['outcome'] == 'dependency_unavailable', r
assert 'llmcall' in r['error']
'''
    proc = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT), str(tmp_path), mode],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize('payload', [None, [], 'invalid', {'text': '', 'provider': None,
    'error': 'synthetic', 'outcome': 'execution_uncertain', 'effects': 'possible',
    'review_state': 'unavailable', 'execution_started': None, 'call_id': 'synthetic-call',
    'effective_model': 'gpt-synthetic', 'effective_provider': 'synthetic-endpoint'}])
def test_js_failed_result_and_malformed_transport(tmp_path, payload):
    script = tmp_path / 'check.js'
    script.write_text("const cp=require('child_process');let calls=[];cp.spawnSync=(a,b,k)=>{calls.push(JSON.parse(k.input));return {status:1,stdout:"
                      + json.dumps(json.dumps(payload)) + ",stderr:'synthetic stderr'};};const {launch}=require("
                      + json.dumps(str(ROOT / 'workflows/_agent_launch.js'))
                      + ");console.log(JSON.stringify({out:launch('codex',{},'synthetic'),calls}));")
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert len(data['calls']) == 1
    assert 'chain' not in data['calls'][0]
    assert data['calls'][0]['selection']['family'] == 'codex'
    assert not data['out']['ok']
    if isinstance(payload, dict): assert_evidence(data['out'])
