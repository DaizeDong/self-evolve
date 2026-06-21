from __future__ import annotations
import os
import subprocess as sp

import pytest

from tools.sie.sandbox import canonical_in_sandbox, action_class


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


def test_action_class_auto_vs_gated(tmp_path):
    root = str(tmp_path / "sbx")
    os.makedirs(root)
    inside = {"op": "write", "path": os.path.join(root, "f.py")}
    assert action_class(inside, root) == "auto"
    outside = {"op": "write", "path": os.path.join(str(tmp_path), "real_target.py")}
    assert action_class(outside, root) == "gated"
    # outward ops are always gated — even if path is inside sandbox
    for op in ("push", "merge_main", "send", "delete_outside"):
        assert action_class({"op": op, "path": os.path.join(root, "f")}, root) == "gated"


def test_make_worktree_real(tmp_path):
    tgt = tmp_path / "repo"
    tgt.mkdir()
    sp.run(["git", "init", "-q"], cwd=tgt, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=tgt, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=tgt, check=True)
    (tgt / "f.txt").write_text("hi")
    sp.run(["git", "add", "-A"], cwd=tgt, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=tgt, check=True)
    from tools.sie.sandbox import make_worktree
    root = make_worktree(str(tgt), "HEAD", "runX")
    assert os.path.isfile(os.path.join(root, "f.txt"))
    assert canonical_in_sandbox(os.path.join(root, "new.py"), root)
