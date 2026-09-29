"""Runtime output belongs to a verified private Git companion for every target."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import runtime_samples


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    sample = runtime_samples()
    companion = tmp_path/'synthetic companion'
    companion.mkdir()
    subprocess.run(['git', 'init', '-q', str(companion)], check=True)
    subprocess.run(['git', '-C', str(companion), 'remote', 'add', 'origin', sample['origin']], check=True)
    data = companion/'data'
    data.mkdir()
    home = tmp_path/'synthetic home'
    visibility = home/'.pii-guard/visibility.json'
    visibility.parent.mkdir(parents=True)
    visibility.write_text(json.dumps({'_refreshed':sample['fresh'], sample['slug']:'PRIVATE'}),encoding='utf-8')
    monkeypatch.setenv('USERPROFILE', str(home))
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR', str(data))
    monkeypatch.delenv('SELF_EVOLVE_CONFIG', raising=False)
    monkeypatch.delenv('SELF_EVOLVE_CONFIG_DIR', raising=False)
    return data, visibility, sample


def test_foreign_target_runs_are_private_and_namespaced(private_home, tmp_path):
    from tools.sie.statemachine import _run_dir
    data, _, sample = private_home
    first, second = tmp_path/'target-one', tmp_path/'target-two'
    first.mkdir()
    second.mkdir()
    a = Path(_run_dir(str(first), sample['run_id']))
    b = Path(_run_dir(str(second), sample['run_id']))
    assert a.is_relative_to(data) and b.is_relative_to(data) and a != b
    assert a.name == sample['run_id']
    assert _run_dir(str(first/'.'), sample['run_id']) == str(a)
    assert not (first/'.sie').exists() and not (second/'.sie').exists()


@pytest.mark.parametrize('proof', ['PUBLIC','UNKNOWN',None,False,{'v':'PUBLIC'}])
def test_invalid_visibility_blocks_before_write(private_home, tmp_path, proof):
    from tools.sie.statemachine import _run_dir
    data, visibility, sample = private_home
    visibility.write_text(json.dumps({'_refreshed':sample['fresh'], sample['slug']:proof}),encoding='utf-8')
    before = sorted(str(p.relative_to(data)) for p in data.rglob('*'))
    with pytest.raises(RuntimeError):
        _run_dir(str(tmp_path), sample['run_id'])
    assert sorted(str(p.relative_to(data)) for p in data.rglob('*')) == before


@pytest.mark.parametrize('stamp', ['stale','future','missing','malformed'])
def test_invalid_visibility_timestamp_blocks(private_home, tmp_path, stamp):
    from tools.sie.statemachine import _run_dir
    _, visibility, sample = private_home
    doc = {sample['slug']:'PRIVATE'}
    if stamp != 'missing':
        doc['_refreshed'] = sample.get(stamp, 'unparseable')
    visibility.write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(RuntimeError):
        _run_dir(str(tmp_path), sample['run_id'])


def test_invalid_run_ids_cannot_escape(private_home, tmp_path):
    from tools.sie.statemachine import _run_dir
    for run_id in private_home[2]['bad_run_ids']:
        with pytest.raises((ValueError,RuntimeError)):
            _run_dir(str(tmp_path), run_id)


def test_unversioned_override_is_not_data_home(private_home, tmp_path, monkeypatch):
    from tools.sie.statemachine import _run_dir
    standalone = tmp_path/'unversioned'
    standalone.mkdir()
    (standalone/'.git').write_text(private_home[2]['invalid_git_marker'], encoding='utf-8')
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR', str(standalone))
    with pytest.raises(RuntimeError):
        _run_dir(str(tmp_path), private_home[2]['run_id'])


def test_agent_scratch_is_unique_and_cleans_on_failure(private_home):
    from tools.sie.runtime_data import agent_scratch
    original = Path.cwd()
    paths = []
    def call(index):
        with agent_scratch() as path:
            paths.append(path)
            assert path.is_relative_to(private_home[0]) and path.is_dir()
            if index:
                raise ValueError('synthetic backend failure')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(call,index) for index in (0,1)]
        futures[0].result()
        with pytest.raises(ValueError):
            futures[1].result()
    assert len(set(paths)) == 2 and all(not p.exists() for p in paths)
    assert Path.cwd() == original


def test_doctor_is_read_only_and_reports_missing_capabilities(private_home, tmp_path, capsys):
    from tools.sie.cli import main
    data = private_home[0]
    before = list(data.rglob('*'))
    assert main(['doctor','--target',str(tmp_path)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {'evidence_providers','patchable_scope','required_inputs','live_call_policy','scenario_eval'} <= doc.keys()
    assert 'llmcall' in json.dumps(doc['live_call_policy'])
    assert list(data.rglob('*')) == before


def test_cache_keeps_existing_records_in_private_storage(private_home, monkeypatch):
    from tools.sie.edgar_cache import prepare_cache
    base = private_home[0]/'cache'
    base.mkdir()
    previous = base/'previous.json'
    previous.write_text(private_home[2]['cache_record'],encoding='utf-8')
    monkeypatch.setenv('EDGAR_IDENTITY',private_home[2]['edgar_identity'])
    current = Path(prepare_cache(str(base)))
    assert current != base and current.is_relative_to(base)
    assert previous.read_text(encoding='utf-8') == private_home[2]['cache_record']


def test_cache_requires_real_identity_configuration(private_home, monkeypatch):
    from tools.sie.edgar_cache import prepare_cache
    monkeypatch.delenv('EDGAR_IDENTITY',raising=False)
    with pytest.raises(RuntimeError):
        prepare_cache()


def _long_descendant(parent, sample):
    path = parent
    while len(str(path)) < sample['long_path_minimum']:
        path /= sample['long_component']
    return path


def test_existing_long_directory_uses_owning_repository(private_home, monkeypatch):
    from tools.sie import runtime_data
    data, _, sample = private_home
    path = _long_descendant(data, sample)
    assert runtime_data.verify_directory(path) == (path, data.parent)
    path.mkdir(parents=True)
    commands = []
    original_git = runtime_data._git

    def record(*args):
        commands.append(args)
        return original_git(*args)

    monkeypatch.setattr(runtime_data, '_git', record)
    assert runtime_data.verify_directory(path) == (path, data.parent)
    assert all(Path(args[1]) == data.parent for args in commands)


def test_long_run_survives_init_and_persisted_status(private_home, tmp_path, capsys):
    from tools.sie.cli import main
    from tools.sie.state import RunState, save_state
    from tools.sie.statemachine import _run_dir
    data, _, sample = private_home
    target = tmp_path/'target'
    target.mkdir()
    # A long valid run id crosses Windows Git's chdir limit without lengthening
    # the actual repository root or any individual filesystem component.
    run_id = sample['long_component'] * 2
    argv = ['--target', str(target), '--run-id', run_id]
    assert main(['init', *argv]) == 0
    initialized = json.loads(capsys.readouterr().out)
    path = Path(initialized['run_dir'])
    assert path.is_relative_to(data) and len(str(path)) > 260
    state = RunState(**{**sample['persisted_state'], 'run_id': run_id})
    save_state(state, str(path))
    assert main(['status', *argv]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status['phase'] == state.phase and status['round'] == state.round
    assert status['no_progress'] == state.no_progress
    assert _run_dir(str(target), run_id) == str(path)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize('proof', ['PUBLIC', 'UNKNOWN', None])
def test_nested_repository_visibility_is_still_checked(private_home, proof):
    from tools.sie.runtime_data import DataBoundaryError, verify_directory
    data, visibility, sample = private_home
    nested = data/'nested'
    subprocess.run(['git', 'init', '-q', str(nested)], check=True)
    subprocess.run(['git', '-C', str(nested), 'remote', 'add', 'origin', sample['nested_origin']], check=True)
    document = json.loads(visibility.read_text(encoding='utf-8'))
    if proof is not None:
        document[sample['nested_slug']] = proof
    visibility.write_text(json.dumps(document), encoding='utf-8')
    requested = nested/'uncreated'
    with pytest.raises(DataBoundaryError, match='PRIVATE companion visibility'):
        verify_directory(requested)
    assert not requested.exists()


def test_nested_private_repository_cannot_replace_expected_repository(private_home):
    from tools.sie.runtime_data import DataBoundaryError, verify_directory
    data, visibility, sample = private_home
    nested = data/'nested'
    subprocess.run(['git', 'init', '-q', str(nested)], check=True)
    subprocess.run(['git', '-C', str(nested), 'remote', 'add', 'origin', sample['nested_origin']], check=True)
    document = json.loads(visibility.read_text(encoding='utf-8'))
    document[sample['nested_slug']] = 'PRIVATE'
    visibility.write_text(json.dumps(document), encoding='utf-8')
    requested = nested/'uncreated'
    assert verify_directory(requested) == (requested, nested)
    with pytest.raises(DataBoundaryError, match='repository boundary'):
        verify_directory(requested, expected_repo=data.parent)
    assert not requested.exists()


def test_long_linked_worktree_uses_file_marker(private_home, tmp_path):
    from tools.sie.runtime_data import verify_directory
    data, _, sample = private_home
    repo = data.parent
    tree = subprocess.run(['git', '-C', str(repo), 'write-tree'], check=True,
                          capture_output=True, text=True, encoding='utf-8').stdout.strip()
    commit = subprocess.run(['git', '-C', str(repo), '-c', 'user.name='+sample['git_name'],
                             '-c', 'user.email='+sample['git_email'], 'commit-tree', tree,
                             '-m', sample['git_message']], check=True, capture_output=True,
                            text=True, encoding='utf-8').stdout.strip()
    linked = tmp_path/'linked companion'
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(linked), commit],
                   check=True, capture_output=True, text=True, encoding='utf-8')
    assert (linked/'.git').is_file()
    requested = _long_descendant(linked, sample)
    requested.mkdir(parents=True)
    assert verify_directory(requested, expected_repo=linked) == (requested, linked)


def test_junction_escape_cannot_reuse_expected_repository(private_home, tmp_path):
    from tools.sie.runtime_data import DataBoundaryError, verify_directory
    data, _, _ = private_home
    outside = tmp_path/'outside'
    outside.mkdir()
    link = data/'linked-outside'
    if os.name == 'nt':
        subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
                       check=True, capture_output=True, text=True, encoding='utf-8')
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(DataBoundaryError):
        verify_directory(link/'uncreated', expected_repo=data.parent)
    assert list(outside.iterdir()) == []


def test_nested_bare_repository_is_not_a_runtime_directory(private_home):
    from tools.sie.runtime_data import DataBoundaryError, verify_directory
    data, _, _ = private_home
    bare = data/'nested-bare'
    subprocess.run(['git', 'init', '--bare', '-q', str(bare)], check=True)
    with pytest.raises(DataBoundaryError):
        verify_directory(bare/'uncreated')
    assert not (bare/'uncreated').exists()


def test_git_failure_preserves_bounded_cause(private_home, tmp_path, monkeypatch):
    from tools.sie.runtime_data import DataBoundaryError, _git
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path.parent))
    with pytest.raises(DataBoundaryError) as caught:
        _git('-C', str(tmp_path), 'rev-parse', '--show-toplevel')
    assert 'not a git repository' in str(caught.value).lower()
    assert len(str(caught.value)) < 700
