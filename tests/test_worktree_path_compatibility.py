"""Real checkout, resume, and unsupported-path handling in private storage."""
import os
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import runtime_samples
from tools.sie.runtime_data import worktree_directory
from tools.sie import sandbox
from tools.sie.sandbox import make_worktree


def _source_repo(tmp_path):
    sample = runtime_samples()
    target = tmp_path / 'source'
    target.mkdir()
    for arguments in (['init', '-q'], ['config', 'user.email', sample['git_email']],
                      ['config', 'user.name', sample['git_name']]):
        subprocess.run(['git', '-C', str(target), *arguments], check=True, capture_output=True)
    name, contents = sample['worktree_file']
    (target / name).write_text(contents, encoding='utf-8')
    subprocess.run(['git', '-C', str(target), 'add', name], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), 'commit', '-qm', sample['git_message']],
                   check=True, capture_output=True)
    return target, name, contents


@pytest.mark.parametrize('case,minimum', runtime_samples()['worktree_lengths'])
def test_checkout_and_resume_preserve_content_at_long_private_path(tmp_path, monkeypatch, case, minimum):
    sample = runtime_samples()
    target, name, contents = _source_repo(tmp_path)
    run_id = sample['run_id'] + '-' + case
    destination = worktree_directory(str(target), run_id)
    if len(str(destination)) < minimum:
        root = Path(os.environ['SELF_EVOLVE_DATA_DIR'])
        root = root / ('p' * max(1, minimum - len(str(destination)) - 1))
        monkeypatch.setenv('SELF_EVOLVE_DATA_DIR', str(root))
        destination = worktree_directory(str(target), run_id)
    assert len(str(destination)) >= minimum

    try:
        actual = Path(make_worktree(str(target), 'HEAD', run_id))
    except subprocess.CalledProcessError as exc:
        pytest.fail(exc.stderr)
    assert actual == destination
    assert (actual / name).read_text(encoding='utf-8') == contents
    assert (actual / '.git').is_file()
    changed = contents + sample['worktree_edit']
    (actual / name).write_text(changed, encoding='utf-8')
    try:
        resumed = Path(make_worktree(str(target), 'HEAD', run_id))
    except subprocess.CalledProcessError as exc:
        pytest.fail(exc.stderr)
    assert resumed == actual
    assert (actual / name).read_text(encoding='utf-8') == changed
    assert (target / name).read_text(encoding='utf-8') == contents


@pytest.mark.skipif(os.name != 'nt', reason='Windows Git path representation')
def test_unavailable_short_path_fails_before_creating_worktree(tmp_path, monkeypatch):
    sample = runtime_samples()
    target, _, _ = _source_repo(tmp_path)
    run_id = sample['run_id']
    destination = worktree_directory(str(target), run_id)
    minimum = dict(sample['worktree_lengths'])['extended']
    root = Path(os.environ['SELF_EVOLVE_DATA_DIR'])
    root = root / ('p' * max(1, minimum - len(str(destination)) - 1))
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR', str(root))
    destination = worktree_directory(str(target), run_id)
    assert len(str(destination)) >= minimum
    monkeypatch.setattr(sandbox, '_windows_short_path', lambda path: None)

    with pytest.raises(RuntimeError, match='shorter PRIVATE data directory'):
        make_worktree(str(target), 'HEAD', run_id)

    assert not destination.exists()
    branch = subprocess.run(
        ['git', '-C', str(target), 'show-ref', '--verify', '--quiet',
         'refs/heads/sie/' + run_id], capture_output=True)
    assert branch.returncode == 1


def test_native_probe_and_graders_run_in_long_worktree(tmp_path, monkeypatch):
    from tools.sie.evaluate import evaluate
    from tools.sie.probes.exec_probe import run_exec_probe
    from tools.sie.verifiable import grade_pytest

    sample = runtime_samples()
    target, _, _ = _source_repo(tmp_path)
    for name, content in sample['worktree_python_files'].items():
        (target / name).write_text(content, encoding='utf-8')
    subprocess.run(['git', '-C', str(target), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), 'commit', '-qm', sample['git_message']],
                   check=True, capture_output=True)
    run_id = sample['run_id'] + '-native'
    minimum = dict(sample['worktree_lengths'])['extended']
    destination = worktree_directory(str(target), run_id)
    root = Path(os.environ['SELF_EVOLVE_DATA_DIR'])
    root = root / ('p' * max(1, minimum - len(str(destination)) - 1))
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR', str(root))
    destination = worktree_directory(str(target), run_id)
    assert len(str(destination)) >= minimum

    original_cwd = Path.cwd()
    actual = Path(make_worktree(str(target), 'HEAD', run_id))
    before = {name: (actual / name).read_bytes() for name in sample['worktree_python_files']}
    probe = run_exec_probe(str(actual))
    assert probe['has_tests'] and probe['exit_code'] == 0 and probe['mutation_killed'], probe
    assert grade_pytest(str(actual))['task_passed']
    assert evaluate(str(actual), 'A')['result']['task_passed']
    assert Path.cwd() == original_cwd
    assert before == {name: (actual / name).read_bytes() for name in before}
