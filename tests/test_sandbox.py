from __future__ import annotations
import os
from pathlib import Path
import subprocess as sp

import pytest

from tools.make_fixtures import runtime_samples
from tools.sie import runtime_data
from tools.sie.sandbox import canonical_in_sandbox, action_class, make_worktree, OUTWARD_OPS


def test_inside(tmp_path):
    root = str(tmp_path / "sbx")
    os.makedirs(root)
    p = os.path.join(root, "sub", "a.txt")
    assert canonical_in_sandbox(p, root) is True   # parent dir in sandbox, file not yet created


def test_dotdot_escape(tmp_path):
    root = str(tmp_path / "sbx")
    os.makedirs(root)
    p = os.path.join(root, "..", "outside.txt")
    assert canonical_in_sandbox(p, root) is False


def test_symlink_escape(tmp_path):
    root = str(tmp_path / "sbx")
    os.makedirs(root)
    outside = tmp_path / "secret"
    outside.mkdir()
    link = os.path.join(root, "link")
    try:
        os.symlink(str(outside), link)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege")
    target = os.path.join(link, "x.txt")
    assert canonical_in_sandbox(target, root) is False


def test_sibling_prefix_not_sandbox(tmp_path):
    """'/a/sandbox-evil' must NOT be judged as inside '/a/sandbox'."""
    root = str(tmp_path / "sandbox")
    os.makedirs(root)
    sibling = str(tmp_path / "sandbox-evil")
    os.makedirs(sibling)
    p = os.path.join(sibling, "bad.txt")
    assert canonical_in_sandbox(p, root) is False


def test_fs_root_outside_sandbox(tmp_path):
    """Filesystem root must never be inside sandbox."""
    root = str(tmp_path / "sandbox")
    os.makedirs(root)
    assert canonical_in_sandbox(os.path.abspath(os.sep), root) is False


def test_action_class_auto_vs_gated(tmp_path):
    root = str(tmp_path / "sbx")
    os.makedirs(root)
    inside = {"op": "write", "path": os.path.join(root, "f.py")}
    assert action_class(inside, root) == "auto"
    outside = {"op": "write", "path": os.path.join(str(tmp_path), "real_target.py")}
    assert action_class(outside, root) == "gated"
    # outward ops are always gated, even if path is inside sandbox
    for op in OUTWARD_OPS:
        assert action_class({"op": op, "path": os.path.join(root, "f")}, root) == "gated"


@pytest.fixture
def synthetic_target(tmp_path):
    sample = runtime_samples()
    tgt = tmp_path / "repo"
    tgt.mkdir()
    sp.run(["git", "init", "-q"], cwd=tgt, check=True)
    sp.run(["git", "config", "user.email", sample['git_email']], cwd=tgt, check=True)
    sp.run(["git", "config", "user.name", sample['git_name']], cwd=tgt, check=True)
    name, content = sample['worktree_file']
    (tgt / name).write_text(content, encoding='utf-8')
    sp.run(["git", "add", "-A"], cwd=tgt, check=True)
    sp.run(["git", "commit", "-qm", sample['git_message']], cwd=tgt, check=True)
    return tgt, sample


def _git_output(root, *args):
    return sp.run(['git', '-C', str(root), *args], check=True,
                  capture_output=True, text=True, encoding='utf-8').stdout.strip()


def test_new_run_and_probe_worktrees_do_not_create_branches(synthetic_target):
    target, sample = synthetic_target
    heads = _git_output(target, 'for-each-ref', '--format=%(refname):%(objectname)', 'refs/heads')
    base = _git_output(target, 'rev-parse', 'HEAD')
    for run_id in (sample['run_id'], 'profile_probe_' + base[:12]):
        root = make_worktree(str(target), base, run_id)
        assert not Path(root).is_relative_to(runtime_data.private_root())
        assert Path(root, sample['worktree_file'][0]).is_file()
        assert canonical_in_sandbox(os.path.join(root, 'new.py'), root)
        assert _git_output(root, 'rev-parse', 'HEAD') == base
        assert sp.run(['git', '-C', root, 'symbolic-ref', '-q', 'HEAD'],
                      capture_output=True).returncode == 1
    assert _git_output(target, 'for-each-ref', '--format=%(refname):%(objectname)', 'refs/heads') == heads


def test_restore_requires_registered_leaf_and_preserves_workspace_parents(synthetic_target):
    from tools.sie import business_tree
    target, sample = synthetic_target
    run_id = sample['run_id']
    candidate = Path(make_worktree(str(target), 'HEAD', run_id))
    source = runtime_data.run_directory(target, run_id) / 'base-snapshot'
    source.mkdir(parents=True)
    name, content = sample['worktree_file']
    (source/name).write_text(content+sample['worktree_edit'], encoding='utf-8')
    for parent in (candidate.parent, candidate.parent.parent):
        with pytest.raises(runtime_data.DataBoundaryError, match='complete candidate namespace'):
            business_tree.restore(source, parent)
        assert (candidate/name).read_text(encoding='utf-8') == content
    business_tree.restore(source, candidate)
    assert (candidate/name).read_text(encoding='utf-8') == content+sample['worktree_edit']
    assert (target/name).read_text(encoding='utf-8') == content


@pytest.mark.parametrize('legacy_attached', [False, True])
def test_resume_preserves_existing_checkout_and_dirty_candidate(synthetic_target, legacy_attached):
    target, sample = synthetic_target
    run_id = sample['run_id']
    if legacy_attached:
        run = runtime_data.run_directory(target, run_id)
        root = run.parent.parent / 'worktrees' / run_id
        root.parent.mkdir(parents=True, exist_ok=True)
        sp.run(['git', '-C', str(target), 'worktree', 'add', '-b', 'sie/' + run_id,
                str(root), 'HEAD'], check=True, capture_output=True)
    else:
        root = Path(make_worktree(str(target), 'HEAD', run_id))
    name = sample['worktree_file'][0]
    (root / name).write_text(sample['worktree_edit'], encoding='utf-8')
    for path, content in sample['worktree_python_files'].items():
        (root / path).write_text(content, encoding='utf-8')
    before = {
        'heads': _git_output(target, 'for-each-ref', '--format=%(refname):%(objectname)', 'refs/heads'),
        'head': _git_output(root, 'rev-parse', 'HEAD'),
        'status': _git_output(root, 'status', '--porcelain'),
        'branch': sp.run(['git', '-C', str(root), 'symbolic-ref', '-q', 'HEAD'],
                         capture_output=True, text=True).stdout,
    }
    resumed = make_worktree(str(target), 'HEAD', run_id)
    assert Path(resumed) == root
    assert _git_output(root, 'rev-parse', 'HEAD') == before['head']
    assert _git_output(root, 'status', '--porcelain') == before['status']
    assert sp.run(['git', '-C', str(root), 'symbolic-ref', '-q', 'HEAD'],
                  capture_output=True, text=True).stdout == before['branch']
    assert _git_output(target, 'for-each-ref', '--format=%(refname):%(objectname)', 'refs/heads') == before['heads']
    assert (root / name).read_text(encoding='utf-8') == sample['worktree_edit']
    for path, content in sample['worktree_python_files'].items():
        assert (root / path).read_text(encoding='utf-8') == content
