"""Producer writes stay in the configured companion's data/ layout (path checks only)."""
import json
from pathlib import Path
import subprocess

import pytest

from test_runtime_private import private_home
from runtime_fixture_support import initialize_companion_history
from tools.make_fixtures import storage_writer_samples
from tools.sie import runtime_data


@pytest.mark.parametrize("relative", storage_writer_samples()["alternate_roots"])
def test_data_override_requires_exact_declared_layout(private_home, monkeypatch, relative):
    data, _, _ = private_home
    override = data.parent / relative
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(override))
    with pytest.raises(runtime_data.DataBoundaryError, match="data/|layout"):
        runtime_data.private_root()
    assert not override.exists()


@pytest.mark.parametrize("variable", ["SELF_EVOLVE_CONFIG", "SELF_EVOLVE_CONFIG_DIR"])
def test_companion_alias_creates_no_root_fallback(private_home, monkeypatch, variable):
    data, _, _ = private_home
    data.rmdir()
    monkeypatch.delenv("SELF_EVOLVE_DATA_DIR")
    monkeypatch.setenv(variable, str(data.parent))
    assert runtime_data.private_root() == data
    assert not data.exists()


def test_data_override_has_precedence_over_config_alias(private_home, monkeypatch):
    data, _, _ = private_home
    monkeypatch.setenv("SELF_EVOLVE_CONFIG", str(data.parent / "absent"))
    monkeypatch.setenv("SELF_EVOLVE_CONFIG_DIR", str(data.parent / "also-absent"))
    assert runtime_data.private_root() == data


def test_config_precedence_ignores_unused_invalid_alias(private_home, monkeypatch):
    data, _, _ = private_home
    monkeypatch.delenv("SELF_EVOLVE_DATA_DIR")
    monkeypatch.setenv("SELF_EVOLVE_CONFIG", str(data.parent))
    monkeypatch.setenv("SELF_EVOLVE_CONFIG_DIR", str(data.parent / "absent"))
    assert runtime_data.private_root() == data


def test_config_alias_rejects_data_path_instead_of_repo_root(private_home, monkeypatch):
    data, _, _ = private_home
    monkeypatch.delenv("SELF_EVOLVE_DATA_DIR")
    monkeypatch.setenv("SELF_EVOLVE_CONFIG", str(data))
    with pytest.raises(runtime_data.DataBoundaryError, match="repository root"):
        runtime_data.private_root()


def test_new_worktree_is_outside_data_and_cannot_receive_runtime_records(private_home, tmp_path):
    data, _, _ = private_home
    sample = storage_writer_samples()
    target = tmp_path / "target"
    target.mkdir()
    worktree = runtime_data.worktree_directory(target, sample["run_id"])
    assert worktree.is_relative_to(data.parent.parent / ".worktrees" / "self-evolve" / data.parent.name)
    assert not worktree.is_relative_to(data.parent)
    with pytest.raises(runtime_data.DataBoundaryError):
        runtime_data.write_json(worktree / "events.jsonl", sample["payload"], append=True)
    assert not worktree.exists()


def test_source_parent_cannot_host_its_own_candidate(private_home, tmp_path):
    with pytest.raises(runtime_data.DataBoundaryError, match="separate"):
        runtime_data.worktree_directory(tmp_path, storage_writer_samples()["run_id"])


def test_configured_a_b_a_switch_keeps_separate_owned_records(private_home, tmp_path, monkeypatch):
    first, _, identity = private_home
    second_repo = tmp_path / "second-companion"
    second_repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(second_repo)], check=True)
    subprocess.run(['git', '-C', str(second_repo), 'remote', 'add', 'origin', identity['origin']], check=True)
    initialize_companion_history(second_repo, identity)
    sample = storage_writer_samples()
    monkeypatch.delenv('SELF_EVOLVE_DATA_DIR')
    paths = []
    for index, data in enumerate((first, second_repo/'data', first)):
        monkeypatch.setenv('SELF_EVOLVE_CONFIG', str(data.parent))
        run = runtime_data.run_directory(tmp_path, sample['run_id'])
        runtime_data.write_json(run/'events.jsonl', {**sample['payload'], 'index': index}, append=True)
        paths.append(run/'events.jsonl')
        assert runtime_data.private_root() == data
    assert paths[0] == paths[2] and paths[0] != paths[1]
    assert [json.loads(line)['index'] for line in paths[0].read_text(encoding='utf-8').splitlines()] == [0, 2]
    assert json.loads(paths[1].read_text(encoding='utf-8'))['index'] == 1


def test_current_producer_records_are_declared_and_round_trip(private_home, tmp_path):
    sample = storage_writer_samples()
    run = runtime_data.run_directory(tmp_path, sample["run_id"])
    for name in sample["run_files"]:
        destination = run / name
        runtime_data.write_json(destination, sample["payload"], append=name.endswith("jsonl"))
        assert json.loads(destination.read_text(encoding="utf-8")) == sample["payload"]
    queue = private_home[0] / "human-review" / sample["run_id"] / "pending_actions.jsonl"
    runtime_data.write_json(queue, sample["payload"], append=True)
    assert json.loads(queue.read_text(encoding="utf-8")) == sample["payload"]


def test_cli_init_refuses_unowned_directory_before_creation(private_home, tmp_path, monkeypatch, capsys):
    from tools.sie.cli import main
    sample = storage_writer_samples()
    run = runtime_data.run_directory(tmp_path, sample['run_id'])

    def refuse_directory(value, **kwargs):
        raise runtime_data.DataBoundaryError('Synthetic directory admission refusal')

    monkeypatch.setattr(runtime_data, '_authorize_artifact', refuse_directory)
    assert main(['init', '--target', str(tmp_path), '--run-id', sample['run_id']]) == 2
    result = capsys.readouterr()
    assert result.out == ''
    assert json.loads(result.err)['status'] == 'failed'
    assert not run.exists()


def test_agent_scratch_authorizes_concrete_child_before_creation(private_home, monkeypatch):
    data, _, _ = private_home
    authorize = runtime_data._authorize_artifact

    def refuse_child(value, **kwargs):
        if Path(value).name.startswith('call-'):
            raise runtime_data.DataBoundaryError('Synthetic child admission refusal')
        return authorize(value, **kwargs)

    monkeypatch.setattr(runtime_data, '_authorize_artifact', refuse_child)
    with pytest.raises(runtime_data.DataBoundaryError, match='child admission'):
        with runtime_data.agent_scratch():
            pytest.fail('Rejected scratch must not be yielded')
    assert list((data/'agent-work').iterdir()) == []


def test_agent_scratch_cleans_up_after_body_failure(private_home):
    with pytest.raises(RuntimeError, match='Synthetic body failure'):
        with runtime_data.agent_scratch() as path:
            assert path.is_dir()
            raise RuntimeError('Synthetic body failure')
    assert not path.exists()


@pytest.mark.parametrize('name', storage_writer_samples()['companion_metadata'])
def test_runtime_writer_preserves_companion_maintenance_metadata(private_home, name):
    sample = storage_writer_samples()
    destination = private_home[0].parent/name
    original = json.dumps(sample['payload'])+'\n'
    destination.write_text(original, encoding='utf-8')
    with pytest.raises(runtime_data.DataBoundaryError, match='data/ layout'):
        runtime_data.private_file_path(destination).write_text('', encoding='utf-8')
    assert destination.read_text(encoding='utf-8') == original
