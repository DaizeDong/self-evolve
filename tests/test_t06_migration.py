"""One-request migration tests; all model results are synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest

ROOT = Path(os.environ.get('T06_SOURCE_REPO', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
# Only contracts are loaded from llmcall. No controller, profiles or provider imports.
# Resolve the installed dependency without importing its controller or providers.
contract_path = os.environ.get('T06_CONTRACTS_PATH')
existing_fake = sys.modules.get('llmcall')
if not contract_path and existing_fake is not None and hasattr(existing_fake, 'Result'):
    contracts = existing_fake
else:
    if not contract_path:
        package_spec = importlib.util.find_spec('llmcall')
        if package_spec is None or not package_spec.origin:
            raise RuntimeError('T06 fake tests require an installed llmcall contract package')
        contract_path = Path(package_spec.origin).with_name('contracts.py')
    spec = importlib.util.spec_from_file_location('t06_contracts', contract_path)
    contracts = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contracts
    spec.loader.exec_module(contracts)
fake = sys.modules.get('llmcall')
if fake is None or not hasattr(fake, 'Result'):
    fake = SimpleNamespace(ModelSelection=contracts.ModelSelection, ExecutionRequirements=contracts.ExecutionRequirements, Result=contracts.Result)
else:
    contracts.ModelSelection = fake.ModelSelection
    contracts.ExecutionRequirements = fake.ExecutionRequirements
    contracts.Result = fake.Result
def forbidden(*a, **kw):
    raise AssertionError('unmocked model call')
fake.call = forbidden
sys.modules['llmcall'] = fake
from tools.sie import agents
from tools.sie.backends import llm as proposer


@pytest.mark.parametrize('result', [
    contracts.Result(error='timeout', outcome='timeout', effects='possible'),
    contracts.Result(error='unknown effects', effects='possible'),
    contracts.Result(provider='synthetic', text=''),
])
def test_one_request_for_failed_agent(monkeypatch, result):
    calls = []
    monkeypatch.setattr(fake, 'call', lambda *a, **kw: calls.append(kw) or result)
    assert not agents.invoke('synthetic prompt')['ok']
    assert len(calls) == 1
    assert not {'chain', 'model', 'effort'} & calls[0].keys()
    assert calls[0]['requirements'].replay == 'never_after_start'


def test_explicit_constraint_is_preserved_and_identity_checked(monkeypatch):
    calls = []
    result = contracts.Result(provider='synthetic', text='answer', model_family='claude', model_source='provider_reported')
    monkeypatch.setattr(fake, 'call', lambda *a, **kw: calls.append(kw) or result)
    assert not agents.invoke('prompt', family='codex', model='synthetic-v1', tools='web_search')['ok']
    assert len(calls) == 1
    assert calls[0]['selection'] == contracts.ModelSelection('exact', 'synthetic-v1', family='codex')
    assert 'chain' not in calls[0]
    assert calls[0]['requirements'].tool_allowlist == ('WebSearch',)


@pytest.mark.parametrize('output', ['not JSON', '{}', '{"file_rel":"escape.py","new_content":"x"}'])
def test_proposer_invalid_output_does_not_rerun(monkeypatch, tmp_path, output):
    (tmp_path / 'module.py').write_text('def value():\n    return 1\n')
    calls = []
    monkeypatch.setattr(proposer, '_scratch_cwd', lambda: str(tmp_path))
    monkeypatch.setattr(fake, 'call', lambda *a, **kw: calls.append(kw) or contracts.Result(provider='synthetic', text=output))
    assert proposer.generate(str(tmp_path), []) == []
    assert len(calls) == 1
    assert calls[0]['requirements'].tool_allowlist == ()
    assert calls[0]['requirements'].access == 'read_only'


def test_artifact_truth_stripping_and_anchor_gate(monkeypatch, tmp_path):
    artifact = {'title':'synthetic', 'sections':[{'anchors':[{'claim':'synthetic claim', 'expected':987654321, 'verified':True}]}]}
    (tmp_path / 'report.json').write_text(json.dumps(artifact))
    calls = []
    def answer(prompt, **kw):
        calls.append(prompt)
        assert '987654321' not in prompt
        return contracts.Result(provider='synthetic', text=json.dumps({'file_rel':'report.json','new_content':json.dumps({'sections':[]})}))
    monkeypatch.setattr(proposer, '_scratch_cwd', lambda: str(tmp_path))
    monkeypatch.setattr(fake, 'call', answer)
    assert proposer.generate_artifact(str(tmp_path), [], 'report.json') == []
    assert len(calls) == 1


def test_valid_proposal_keeps_domain_artifact_contract(monkeypatch, tmp_path):
    (tmp_path / 'module.py').write_text('def value():\n    return 1\n')
    monkeypatch.setattr(proposer, '_scratch_cwd', lambda: str(tmp_path))
    monkeypatch.setattr(fake, 'call', lambda *a, **kw: contracts.Result(provider='synthetic', text=json.dumps({'file_rel':'module.py','new_content':'def value():\n    return 2\n'})))
    assert proposer.generate(str(tmp_path), [])[0]['file_rel'] == 'module.py'


def test_js_transport_invalid_json_calls_fake_once(tmp_path):
    script = tmp_path / 'test.js'
    script.write_text("const cp=require('child_process'); let calls=[]; cp.spawnSync=(bin,args,kw)=>{calls.push(JSON.parse(kw.input));return {status:0,stdout:'invalid JSON'};};const {launch}=require(" + json.dumps(str(ROOT / 'workflows/_agent_launch.js')) + ");const r=launch(null,{},'synthetic'); console.log(JSON.stringify({r,calls}));")
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert not data['r']['ok']
    assert len(data['calls']) == 1
    assert not {'model','effort','chain'} & data['calls'][0].keys()
