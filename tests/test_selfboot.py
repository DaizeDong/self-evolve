"""test_selfboot.py — M4.6: selfboot_init 独立 worktree + frozen 装配 + statemachine 接线。

测试覆盖:
- selfboot_init 建独立 worktree，frozen_dir 在 candidate worktree 之外
- frozen_dir 含 IMMUTABLE 文件，frozen_digests 非空
- candidate 路径隔离（candidate_path_is_isolated）
- supervisor 非 None
- is_self_run 读 args.self_mode
- state_patch 把 enforce_immutable 透传给 patch.apply_patch（不真递归 run/不真网络）
"""
import os
import subprocess
import pathlib
import pytest
from tools.sie import selfboot


# ---------------------------------------------------------------------------
# 辅助：构造最小合法 git 仓库（含 tools/sie IMMUTABLE 文件）
# ---------------------------------------------------------------------------

def _init_self_repo(tmp_path):
    root = tmp_path / "self_repo"
    sie = root / "tools" / "sie"
    sie.mkdir(parents=True)
    for m in [
        "acceptor.py", "verifiable.py", "gate_human.py", "judges.py",
        "selfdeception.py", "anchors.py", "statemachine.py",
        "profile.py", "sandbox.py", "supervisor.py", "immutable.py",
        "patch.py", "proxy.py", "events.py",
    ]:
        (sie / m).write_text(f"# {m}\nMARK='{m}'\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "config", "core.safecrlf", "false"], cwd=root,
                   check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root,
                   check=True, env=env)
    return str(root)


# ---------------------------------------------------------------------------
# Step 1 / Step 4: selfboot_init 建独立 worktree，frozen_dir 在 candidate 外
# ---------------------------------------------------------------------------

def test_selfboot_frozen_outside_candidate_worktree(tmp_path):
    """frozen 必须不在 candidate worktree 内（candidate 改不到裁决基线）。"""
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_1", runs)

    cw = pathlib.Path(boot["candidate_worktree"]).resolve()
    fd = pathlib.Path(boot["frozen_dir"]).resolve()

    # frozen 不能在 candidate worktree 内，也不能是 candidate worktree 的父
    assert fd != cw and cw not in fd.parents, (
        f"frozen_dir={fd} 不应在 candidate_worktree={cw} 内"
    )
    # frozen 含 IMMUTABLE 文件
    assert (fd / "acceptor.py").exists(), "frozen 应包含 acceptor.py"
    assert boot["frozen_digests"]["acceptor.py"], "frozen_digests 应有 acceptor.py 哈希"


def test_selfboot_verifies_and_isolates(tmp_path):
    """candidate worktree 的 sie root 不在解析路径上，supervisor 非 None。"""
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_2", runs)

    from tools.sie import supervisor as sup

    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")
    assert sup.candidate_path_is_isolated(boot["frozen_dir"], cand_sie) is True
    assert boot["supervisor"] is not None


def test_selfboot_candidate_worktree_is_independent(tmp_path):
    """candidate worktree 路径含 self__ 前缀，与普通 run worktree 区分。"""
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_3", runs)
    cw = boot["candidate_worktree"]
    # 路径包含 self__ 前缀（make_worktree 内部用 run_id="self__run_self_3"）
    assert "self__" in cw, f"candidate_worktree 应含 self__ 前缀，实际: {cw}"


def test_selfboot_frozen_dir_inside_runs_root(tmp_path):
    """frozen_dir 应在 runs_root/<run_id>/_frozen 路径。"""
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_4", runs)
    expected = os.path.join(runs, "run_self_4", "_frozen")
    assert os.path.normcase(os.path.realpath(boot["frozen_dir"])) == \
           os.path.normcase(os.path.realpath(expected)), (
        f"frozen_dir 应为 {expected}，实际: {boot['frozen_dir']}"
    )


# ---------------------------------------------------------------------------
# is_self_run
# ---------------------------------------------------------------------------

def test_is_self_run_self_mode():
    class _Args:
        self_mode = True

    assert selfboot.is_self_run(_Args()) is True


def test_is_self_run_false_by_default():
    class _Args:
        self_mode = False

    assert selfboot.is_self_run(_Args()) is False


def test_is_self_run_missing_attr():
    class _Args:
        pass  # 无任何属性

    assert selfboot.is_self_run(_Args()) is False


def test_is_self_run_self_attr():
    """getattr(args, 'self') 也触发（兼容 argparse dest 为 'self' 的旧写法）。"""
    class _Args:
        self = True  # noqa: A003

    assert selfboot.is_self_run(_Args()) is True


# ---------------------------------------------------------------------------
# Step 6 / Step 7: statemachine.state_patch 透传 enforce_immutable
# ---------------------------------------------------------------------------

def test_statemachine_patch_receives_enforce_flag(monkeypatch):
    """主循环把 enforce 透传给 patch.apply_patch 的 enforce_immutable。"""
    from tools.sie import statemachine, patch

    seen = {}

    def fake_apply(p, worktree, *a, enforce_immutable=False, **k):
        seen["enforce_immutable"] = enforce_immutable
        return {"decision": "REJECT", "reason": "immutable_hit", "paths": ["acceptor.py"]}

    monkeypatch.setattr(patch, "apply_patch", fake_apply)

    statemachine.state_patch(
        proposals=[{"target": ["acceptor.py"], "diff": ""}],
        worktree="X",
        enforce_immutable=True,
    )
    assert seen["enforce_immutable"] is True


def test_statemachine_patch_enforce_false_by_default(monkeypatch):
    """enforce_immutable 默认 False（非自举行为不变）。"""
    from tools.sie import statemachine, patch

    seen = {}

    def fake_apply(p, worktree, *a, enforce_immutable=False, **k):
        seen["enforce_immutable"] = enforce_immutable
        return {"status": "APPLIED", "reason": "ok"}

    monkeypatch.setattr(patch, "apply_patch", fake_apply)

    statemachine.state_patch(
        proposals=[{"target": ["ok.py"], "diff": "x=1\n"}],
        worktree="X",
    )
    assert seen["enforce_immutable"] is False


def test_statemachine_patch_returns_results(monkeypatch):
    """state_patch 返回每个 proposal 的结果列表。"""
    from tools.sie import statemachine, patch

    call_count = {"n": 0}

    def fake_apply(p, worktree, *a, enforce_immutable=False, **k):
        call_count["n"] += 1
        return {"status": "APPLIED", "reason": "ok"}

    monkeypatch.setattr(patch, "apply_patch", fake_apply)

    proposals = [
        {"target": ["a.py"], "diff": ""},
        {"target": ["b.py"], "diff": ""},
    ]
    results = statemachine.state_patch(proposals, worktree="X")
    assert len(results) == 2
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# verify_immutable fail-closed：篡改 → selfboot_init 抛 ImmutableViolation
# ---------------------------------------------------------------------------

def test_selfboot_tampered_candidate_raises(tmp_path):
    """candidate worktree IMMUTABLE 文件被篡改 → selfboot_init raise ImmutableViolation。

    此测试模拟 verify_immutable 的 fail-closed 行为：构造一个 selfboot_init 调用路径
    中 verify_immutable 会抛出的场景（monkeypatch 注入篡改后果）。
    """
    from tools.sie import immutable as im

    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")

    # 注入：verify_immutable 强制抛 ImmutableViolation（模拟 candidate 篡改）
    original_verify = im.verify_immutable

    def tampered_verify(candidate_sie_root, frozen_digests):
        raise im.ImmutableViolation("IMMUTABLE 校验失败: acceptor.py: 哈希不符")

    import tools.sie.immutable as im_mod
    original = im_mod.verify_immutable
    im_mod.verify_immutable = tampered_verify
    # 也需要 patch selfboot 内的引用（从 .immutable import verify_immutable）
    import tools.sie.selfboot as sb_mod
    original_sb = sb_mod.verify_immutable
    sb_mod.verify_immutable = tampered_verify
    try:
        with pytest.raises(im.ImmutableViolation):
            selfboot.selfboot_init(repo, "HEAD", "run_tamper", runs)
    finally:
        im_mod.verify_immutable = original
        sb_mod.verify_immutable = original_sb
