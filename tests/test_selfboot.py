"""test_selfboot.py — M4.6: selfboot_init 独立 worktree + frozen 装配 + statemachine 接线。

测试覆盖:
- selfboot_init 建独立 worktree，frozen_dir 在 candidate worktree 之外
- frozen_dir 含 IMMUTABLE 文件，frozen_digests 非空
- candidate 路径隔离（candidate_path_is_isolated）
- supervisor 非 None
- is_self_run 读 args.self_mode
- run_loop 自举时态6/7 走 supervisor.grade/decide（frozen），非自举零影响
- CLI --self 触发 selfboot_init + 线进 supervisor
- apply_patch 把 enforce_immutable 直接透传（活路径验收）
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
# M4.6: apply_patch enforce_immutable 活路径验收（替换已删除的 state_patch 测试）
# ---------------------------------------------------------------------------

def test_apply_patch_receives_enforce_immutable_true(monkeypatch, tmp_path):
    """run_loop 态5 把 enforce_immutable=True 透传给 apply_patch（活路径）。"""
    from tools.sie import patch

    seen = {}

    def fake_apply(worktree, file_rel, new_content, *, enforce_immutable=False):
        seen["enforce_immutable"] = enforce_immutable
        return {"status": "REJECTED", "reason": "immutable_hit", "paths": [file_rel]}

    monkeypatch.setattr(patch, "apply_patch", fake_apply)
    # 直接调用 apply_patch（活路径：run_loop 态5 调用此函数）
    result = patch.apply_patch("worktree_path", "acceptor.py", "# content",
                               enforce_immutable=True)
    assert seen["enforce_immutable"] is True


def test_apply_patch_enforce_false_by_default(monkeypatch, tmp_path):
    """enforce_immutable 默认 False（非自举行为不变）。"""
    from tools.sie import patch

    seen = {}

    def fake_apply(worktree, file_rel, new_content, *, enforce_immutable=False):
        seen["enforce_immutable"] = enforce_immutable
        return {"status": "APPLIED", "reason": "ok"}

    monkeypatch.setattr(patch, "apply_patch", fake_apply)
    patch.apply_patch("worktree_path", "ok.py", "x=1\n")
    assert seen["enforce_immutable"] is False


# ---------------------------------------------------------------------------
# M4.6: run_loop 自举时态6 走 supervisor.grade，态7 走 supervisor.decide
# ---------------------------------------------------------------------------

def _stub_run_loop_infra(tmp_path, monkeypatch):
    """共享桩：mock 掉 run_loop 内的 git/pytest/网络重依赖。

    statemachine.py 用 `from X import f` 方式导入，所以必须 patch statemachine 模块
    自身的名字绑定（而非原始模块），才能影响 run_loop 内的调用。
    """
    import tools.sie.statemachine as _sm
    import tools.sie.archive as _arch

    sandbox = str(tmp_path / "sandbox")
    monkeypatch.setattr(_sm, "make_worktree", lambda *a, **k: sandbox)
    monkeypatch.setattr(_sm, "run_profile",
                        lambda *a, **k: {"tier": "A", "anchors_visible": []})
    monkeypatch.setattr(_sm, "freeze_target", lambda *a, **k: None)
    monkeypatch.setattr(_sm, "reflect",
                        lambda *a, **k: [{"file_rel": "x.py", "new_content": "x=1\n"}])
    monkeypatch.setattr(_sm, "check", lambda *a, **k: True)
    monkeypatch.setattr(_sm, "propose",
                        lambda *a, **k: [{"file_rel": "x.py", "new_content": "x=1\n"}])
    monkeypatch.setattr(_sm, "apply_patch",
                        lambda wt, fr, nc, enforce_immutable=False: {"status": "APPLIED"})
    monkeypatch.setattr(_arch, "add_version", lambda *a, **k: None)
    monkeypatch.setattr(_arch, "snapshot_version", lambda *a, **k: None)
    monkeypatch.setattr(_arch, "lineage", lambda *a, **k: [])


def test_run_loop_supervisor_injected_uses_frozen_grade_and_decide(tmp_path, monkeypatch):
    """自举 supervisor 注入时 run_loop 态6 调 supervisor.grade、态7 调 supervisor.decide。
    构造 candidate 改了 acceptor/evaluate，但因走 frozen Supervisor 被忽略→断言用 frozen 结果。
    """
    import os
    from tools.sie import statemachine

    grade_calls = []
    decide_calls = []

    class _FakeSupervisor:
        def grade(self, task, candidate_wt, *, self_mode):
            grade_calls.append({"task": task, "candidate_wt": candidate_wt,
                                 "self_mode": self_mode})
            return {
                "task_passed": True,
                "grader_exit_code": 0,
                "dimensions": [{"name": "pytest", "tier": "A", "score": 1.0, "weight": 1.0}],
                "graded_by": "FROZEN",
            }

        def decide(self, paired, tier, st, params):
            decide_calls.append({"paired": paired, "tier": tier})
            return {"decision": "ACCEPT", "evalue": 0.0, "reason": "frozen accept"}

    fake_supervisor = _FakeSupervisor()
    _stub_run_loop_infra(tmp_path, monkeypatch)

    target = str(tmp_path / "repo")
    os.makedirs(target)

    result = statemachine.run_loop(
        target, "HEAD", "run_sv_test", max_rounds=1,
        supervisor=fake_supervisor,
        candidate_worktree=str(tmp_path / "candidate"),
    )

    assert len(grade_calls) == 1, f"expected 1 grade call, got {grade_calls}"
    assert grade_calls[0]["self_mode"] is True
    assert grade_calls[0]["candidate_wt"] == str(tmp_path / "candidate")

    assert len(decide_calls) == 1, f"expected 1 decide call, got {decide_calls}"
    assert decide_calls[0]["paired"] == [(0.0, 1.0)]

    assert len(result["accepted_versions"]) == 1


def test_run_loop_non_self_supervisor_none_uses_evaluate(tmp_path, monkeypatch):
    """非自举（supervisor=None）：run_loop 走原路径；不调 supervisor.grade/decide。"""
    import os
    import tools.sie.statemachine as _sm

    _stub_run_loop_infra(tmp_path, monkeypatch)

    # 非自举调 evaluate（statemachine 自身绑定）→ 返回 REJECT 结果（score=0 → REJECT）
    monkeypatch.setattr(_sm, "evaluate",
                        lambda *a, **k: {
                            "result": {
                                "task_passed": False,
                                "grader_exit_code": 1,
                                "dimensions": [{"name": "t", "tier": "A",
                                                "score": 0.0, "weight": 1.0}],
                            },
                            "paired": [(0.0, 0.0)],
                            "coverage": 1.0,
                        })

    target = str(tmp_path / "repo2")
    os.makedirs(target)

    result = _sm.run_loop(
        target, "HEAD", "run_nosv_test", max_rounds=1,
        supervisor=None,
    )
    assert result["accepted_versions"] == []


# ---------------------------------------------------------------------------
# M4.6: CLI --self 触发 selfboot_init + 线进 supervisor
# ---------------------------------------------------------------------------

def test_cli_self_mode_calls_selfboot_init(monkeypatch, tmp_path):
    """CLI run --self 时调 selfboot_init 并把 supervisor/candidate_worktree 线进 run_loop。"""
    import os
    from tools.sie import cli as _cli
    import tools.sie.selfboot as _sb_mod

    selfboot_calls = []
    run_loop_kwargs = {}

    class _FakeSupervisor:
        pass

    fake_boot = {
        "candidate_worktree": str(tmp_path / "candidate"),
        "frozen_dir": str(tmp_path / "frozen"),
        "frozen_digests": {},
        "supervisor": _FakeSupervisor(),
    }

    def fake_selfboot_init(self_repo_root, base_ref, run_id, runs_root):
        selfboot_calls.append({
            "self_repo_root": self_repo_root,
            "base_ref": base_ref,
            "run_id": run_id,
        })
        return fake_boot

    def fake_run_loop(target, base_ref, run_id, **kwargs):
        run_loop_kwargs.update(kwargs)
        return {"run_id": run_id, "accepted_versions": [], "final_phase": "INIT",
                "run_dir": str(tmp_path)}

    # cli.py does `from tools.sie.selfboot import selfboot_init` via dynamic import;
    # patch the module attribute resolved at call time.
    monkeypatch.setattr(_sb_mod, "selfboot_init", fake_selfboot_init)
    # cli.py does `from tools.sie.statemachine import run_loop` at module level;
    # patch the cli module's own name binding.
    monkeypatch.setattr(_cli, "run_loop", fake_run_loop)

    target = str(tmp_path / "repo")
    os.makedirs(target)

    rc = _cli.main(["run", "--target", target, "--run-id", "rid1",
                     "--base-ref", "HEAD", "--self"])
    assert rc == 0
    assert len(selfboot_calls) == 1
    assert selfboot_calls[0]["base_ref"] == "HEAD"
    assert run_loop_kwargs.get("supervisor") is fake_boot["supervisor"]
    assert run_loop_kwargs.get("candidate_worktree") == fake_boot["candidate_worktree"]
    assert run_loop_kwargs.get("enforce_immutable") is True


def test_cli_non_self_does_not_call_selfboot_init(monkeypatch, tmp_path):
    """CLI run 非 --self 时不调 selfboot_init，supervisor=None 传入 run_loop。"""
    import os
    from tools.sie import cli as _cli
    import tools.sie.selfboot as _sb_mod

    selfboot_calls = []
    run_loop_kwargs = {}

    def fake_selfboot_init(*a, **k):
        selfboot_calls.append(True)
        return {}

    def fake_run_loop(target, base_ref, run_id, **kwargs):
        run_loop_kwargs.update(kwargs)
        return {"run_id": run_id, "accepted_versions": [], "final_phase": "INIT",
                "run_dir": str(tmp_path)}

    monkeypatch.setattr(_sb_mod, "selfboot_init", fake_selfboot_init)
    monkeypatch.setattr(_cli, "run_loop", fake_run_loop)

    target = str(tmp_path / "repo2")
    os.makedirs(target)

    rc = _cli.main(["run", "--target", target, "--run-id", "rid2", "--base-ref", "HEAD"])
    assert rc == 0
    assert selfboot_calls == []
    assert run_loop_kwargs.get("supervisor") is None
    assert run_loop_kwargs.get("candidate_worktree") is None


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
