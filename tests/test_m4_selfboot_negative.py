"""test_m4_selfboot_negative.py — M4.7: 自举负向用例端到端验收（spec §13/§9 M4 验收）。

四铁律负向用例：
  (a) patch 改 IMMUTABLE 路径(gate_human/acceptor) → 硬拒(immutable_gate/apply_patch enforce=True → REJECT immutable_hit，文件不落盘)
  (b) candidate 提供撒谎 grade() → 不采信(Supervisor.grade self_mode=True 用 frozen grade_pytest，candidate grade 被忽略)
  (c) 篡改 IMMUTABLE 文件 → 启动拒(verify_immutable raise ImmutableViolation，fail-closed)
  (d) candidate worktree 不在解析路径(candidate_path_is_isolated 真；selfboot_init 建好即断言)

Part B: B/C tier guard + statemachine 死 import 清理验证。
"""
import ast
import importlib.util
import os
import pathlib
import subprocess
import pytest

from tools.sie import selfboot, patch as P
from tools.sie import immutable as im
from tools.sie.supervisor import Supervisor


# ---------------------------------------------------------------------------
# Helper: 构造最小合法 git 仓库（含 tools/sie IMMUTABLE 文件），不依赖 tests 包导入
# ---------------------------------------------------------------------------

def _init_self_repo(tmp_path):
    """与 test_selfboot._init_self_repo 等价，内联避免 tests 包导入问题。"""
    root = pathlib.Path(tmp_path) / "self_repo"
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


def _self_repo(tmp_path):
    return _init_self_repo(tmp_path)


# ---------------------------------------------------------------------------
# (a) patch 改 IMMUTABLE 路径 → 硬拒（immutable_gate + apply_patch enforce=True）
# ---------------------------------------------------------------------------

def test_neg_a_patch_hits_immutable_rejected():
    """gate_human.py 和 acceptor.py 均属 IMMUTABLE；enforce=True 时必须 REJECT。"""
    for tgt in ["gate_human.py", "acceptor.py"]:
        res = P.immutable_gate([tgt], enforce=True)
        assert res is not None, f"immutable_gate 应返回 REJECT dict，tgt={tgt}"
        assert res["decision"] == "REJECT", f"decision 应为 REJECT，tgt={tgt}"
        assert res["reason"] == "immutable_hit", f"reason 应为 immutable_hit，tgt={tgt}"

    # enforce=False 时放行（返回 None）
    res_false = P.immutable_gate(["gate_human.py"], enforce=False)
    assert res_false is None, "enforce=False 时 immutable_gate 应返回 None（放行）"


def test_neg_a_apply_patch_rejects_immutable_file(tmp_path):
    """apply_patch(enforce_immutable=True) 对 IMMUTABLE 路径 REJECT 且不落盘。"""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    for immut_path in ["acceptor.py", "gate_human.py", "supervisor.py"]:
        tgt = sandbox / immut_path
        # 确保文件不存在（验证文件不落盘）
        if tgt.exists():
            tgt.unlink()

        result = P.apply_patch(str(sandbox), immut_path, "EVIL=1\n",
                               enforce_immutable=True)
        assert result["status"] == "REJECT", \
            f"apply_patch 对 {immut_path} 应 REJECT，实际: {result}"
        assert "immutable_hit" in result["reason"], \
            f"reason 应含 immutable_hit，实际: {result['reason']}"
        assert not tgt.exists(), f"{immut_path} 不应落盘"


# ---------------------------------------------------------------------------
# (b) candidate 提供撒谎 grade() → 不采信（frozen Supervisor.grade 全程用 frozen grader）
# ---------------------------------------------------------------------------

def test_neg_b_candidate_grade_not_trusted(tmp_path):
    """自举时 candidate 塞进去的 grade()（永远 task_passed=True）不被采信。

    Supervisor.grade(self_mode=True) 调用 frozen verifiable.grade_pytest，
    只要 frozen 的 grade_pytest 返回 task_passed=False，结果就是 False——
    candidate 的 True 被完全忽略。
    """
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_b", runs)
    sv: Supervisor = boot["supervisor"]
    cw = boot["candidate_worktree"]

    # candidate 在自举 worktree 内塞一个永远 task_passed=True 的 grade()
    cand_grade = pathlib.Path(cw) / "grade.py"
    cand_grade.write_text(
        "def grade(task):\n"
        "    return {'task_passed': True, 'grader_exit_code': 0,\n"
        "            'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0}\n",
        encoding="utf-8")

    # frozen verifiable.py 是占位（MARK）,替换成带 grade_pytest 的 frozen grader
    vpath = pathlib.Path(boot["frozen_dir"]) / "verifiable.py"
    # 先解除只读保护（materialize_frozen 写为 0o444）
    os.chmod(str(vpath), 0o644)
    vpath.write_text(
        "def run_grader(task, snapshot=None, env_whitelist=None):\n"
        "    return {'task_passed': False, 'grader_exit_code': 1,\n"
        "            'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0,\n"
        "            'graded_by': 'FROZEN'}\n\n"
        "def grade_pytest(sandbox_root):\n"
        "    return {'task_passed': False, 'grader_exit_code': 1,\n"
        "            'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0,\n"
        "            'graded_by': 'FROZEN'}\n",
        encoding="utf-8")

    # 重建 supervisor 以加载新 frozen verifiable（哈希更新以通过内部校验）
    digests = dict(boot["frozen_digests"])
    digests["verifiable.py"] = im.hash_file(str(vpath))
    sv2 = Supervisor(boot["frozen_dir"], digests)

    res = sv2.grade({"id": "t"}, cw, self_mode=True)
    assert res["task_passed"] is False, \
        f"candidate 的 True 应被忽略，frozen 返回 False，实际: {res}"
    assert res.get("graded_by") == "FROZEN", \
        f"graded_by 应为 FROZEN，实际: {res.get('graded_by')}"


def test_neg_b_supervisor_grade_non_self_mode_raises():
    """self_mode=False 时 Supervisor.grade raise RuntimeError（fail-closed）。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # 创建最小 frozen_dir（含 acceptor.py 占位）
        frozen = pathlib.Path(td) / "_frozen"
        frozen.mkdir()
        (frozen / "acceptor.py").write_text(
            "def decide(paired, tier, st, params):\n"
            "    return {'decision': 'REJECT', 'evalue': 1.0, 'reason': 'frozen'}\n",
            encoding="utf-8")
        digests = {"acceptor.py": im.hash_file(str(frozen / "acceptor.py"))}
        sv = Supervisor(str(frozen), digests)
        with pytest.raises(RuntimeError, match="self-mode only"):
            sv.grade({}, td, self_mode=False)


# ---------------------------------------------------------------------------
# (c) 篡改 IMMUTABLE 文件 → 启动拒（verify_immutable raise ImmutableViolation）
# ---------------------------------------------------------------------------

def test_neg_c_tampered_immutable_startup_rejected(tmp_path):
    """candidate 篡改裁决文件 → verify_immutable raise ImmutableViolation（fail-closed）。"""
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_c", runs)

    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")

    # candidate 篡改裁决文件后再次启动校验 → 必须 raise
    (pathlib.Path(cand_sie) / "acceptor.py").write_text("EVIL=1\n", encoding="utf-8")
    with pytest.raises(im.ImmutableViolation):
        im.verify_immutable(cand_sie, boot["frozen_digests"])


def test_neg_c_tampered_multiple_files_all_caught(tmp_path):
    """多个 IMMUTABLE 文件均被篡改 → verify_immutable 一次性报告所有违规（fail-closed）。"""
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_c2", runs)

    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")

    # 篡改两个 IMMUTABLE 文件
    (pathlib.Path(cand_sie) / "gate_human.py").write_text("TAMPERED=1\n", encoding="utf-8")
    (pathlib.Path(cand_sie) / "supervisor.py").write_text("TAMPERED=2\n", encoding="utf-8")

    with pytest.raises(im.ImmutableViolation) as exc_info:
        im.verify_immutable(cand_sie, boot["frozen_digests"])
    # 报错信息应含被篡改文件名
    msg = str(exc_info.value)
    assert "gate_human.py" in msg or "supervisor.py" in msg, \
        f"ImmutableViolation 应含文件名，实际: {msg}"


# ---------------------------------------------------------------------------
# (d) candidate worktree 不在解析路径（candidate_path_is_isolated 为 True）
# ---------------------------------------------------------------------------

def test_neg_d_candidate_not_on_resolution_path(tmp_path):
    """selfboot_init 建好后，candidate sie root 不在 supervisor 解析路径。"""
    from tools.sie import supervisor as sup

    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_d", runs)

    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")
    assert sup.candidate_path_is_isolated(boot["frozen_dir"], cand_sie) is True, \
        f"candidate_path_is_isolated 应为 True，cand_sie={cand_sie}"


def test_neg_d_selfboot_candidate_isolated_verified(tmp_path):
    """selfboot_init 步骤4：candidate worktree 不在 sys.path 上，selfboot 正常完成。"""
    from tools.sie import supervisor as sup

    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")

    # selfboot_init 步骤4 已包含 candidate_path_is_isolated 断言
    # 若 candidate 在 sys.path 上则 selfboot_init 会 raise ImmutableViolation
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_d2", runs)
    cand_wt = boot["candidate_worktree"]
    cand_sie = os.path.join(cand_wt, "tools", "sie")

    # 验证：隔离通过（True），否则 selfboot_init 就已 raise
    assert sup.candidate_path_is_isolated(boot["frozen_dir"], cand_sie) is True, \
        f"candidate_path_is_isolated 应为 True（selfboot_init 步骤4 已保证），cand_sie={cand_sie}"


# ---------------------------------------------------------------------------
# Part B: B/C tier guard, 自举时 tier 含 B/C → raise
# ---------------------------------------------------------------------------

def _stub_sm_infra(monkeypatch, tmp_path, tier: str):
    """为 run_loop 桩掉基础设施，注入指定 tier。"""
    import tools.sie.statemachine as _sm
    import tools.sie.archive as _arch

    sandbox = str(tmp_path / "sandbox")
    os.makedirs(sandbox, exist_ok=True)
    monkeypatch.setattr(_sm, "make_worktree", lambda *a, **k: sandbox)
    monkeypatch.setattr(_sm, "run_profile",
                        lambda *a, **k: {"tier": tier, "anchors_visible": []})
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


class _FakeSupervisor:
    """自举测试用 Supervisor 桩。"""
    def grade(self, task, candidate_wt, *, self_mode):
        return {"task_passed": True, "grader_exit_code": 0,
                "dimensions": [], "graded_by": "FROZEN"}

    def decide(self, paired, tier, st, params):
        return {"decision": "ACCEPT", "evalue": 0.0, "reason": "frozen accept"}


def test_selfboot_guard_b_tier_raises(tmp_path, monkeypatch):
    """自举时 tier=B → run_loop raise ValueError（自举限 A 档）。"""
    import tools.sie.statemachine as _sm

    target = str(tmp_path / "repo_b")
    os.makedirs(target)
    _stub_sm_infra(monkeypatch, tmp_path, tier="B")

    with pytest.raises(ValueError, match="B|tier|自举"):
        _sm.run_loop(
            target, "HEAD", "bc_b_test", max_rounds=1,
            supervisor=_FakeSupervisor(),
            candidate_worktree=str(tmp_path / "candidate"),
        )


def test_selfboot_guard_c_tier_raises(tmp_path, monkeypatch):
    """自举时 tier=C → run_loop raise ValueError（自举限 A 档）。"""
    import tools.sie.statemachine as _sm

    target = str(tmp_path / "repo_c")
    os.makedirs(target)
    _stub_sm_infra(monkeypatch, tmp_path, tier="C")

    with pytest.raises(ValueError, match="C|tier|自举"):
        _sm.run_loop(
            target, "HEAD", "bc_c_test", max_rounds=1,
            supervisor=_FakeSupervisor(),
            candidate_worktree=str(tmp_path / "candidate"),
        )


def test_selfboot_guard_a_tier_does_not_raise(tmp_path, monkeypatch):
    """自举时 tier=A → run_loop 不 raise（A 档是唯一允许的自举档位）。"""
    import tools.sie.statemachine as _sm

    target = str(tmp_path / "repo_a")
    os.makedirs(target)
    _stub_sm_infra(monkeypatch, tmp_path, tier="A")

    # tier=A 自举不应 raise
    result = _sm.run_loop(
        target, "HEAD", "bc_a_test", max_rounds=1,
        supervisor=_FakeSupervisor(),
        candidate_worktree=str(tmp_path / "candidate"),
    )
    # 正常返回（不 raise）
    assert "run_id" in result


def test_selfboot_guard_not_triggered_without_supervisor(tmp_path, monkeypatch):
    """非自举（supervisor=None）时 B/C tier 不触发 guard（行为完全不变）。"""
    import tools.sie.statemachine as _sm

    target = str(tmp_path / "repo_nosv")
    os.makedirs(target)
    _stub_sm_infra(monkeypatch, tmp_path, tier="B")

    # 非自举 B 档需要 evaluate 桩（避免真实 evaluate 调用失败）
    monkeypatch.setattr(_sm, "evaluate",
                        lambda *a, **k: {
                            "tier": "B",
                            "b_paired": [(0.0, 0.0)],
                            "coverage_floor_violation": False,
                            "visible_anchor_gain": 0.0,
                            "holdout_gain": None,
                            "anchors_visible_verified": [],
                        })

    # 非自举 supervisor=None 不 raise
    result = _sm.run_loop(
        target, "HEAD", "nosv_b_test", max_rounds=1,
        supervisor=None,
    )
    assert "run_id" in result


# ---------------------------------------------------------------------------
# Part B: 死 import _patch_module 已从 statemachine 删除（验证）
# ---------------------------------------------------------------------------

def test_no_dead_import_patch_module_in_statemachine():
    """statemachine.py 不应有 _patch_module 死 import（M4.6 fix 后已无引用）。"""
    sm_path = pathlib.Path(__file__).parent.parent / "tools" / "sie" / "statemachine.py"
    source = sm_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 检查是否有 `from tools.sie import patch as _patch_module` 或类似 import
    dead_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname == "_patch_module":
                    dead_imports.append(
                        f"line {node.lineno}: from {node.module} import {alias.name} as {alias.asname}"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == "_patch_module":
                    dead_imports.append(
                        f"line {node.lineno}: import {alias.name} as {alias.asname}"
                    )

    assert dead_imports == [], (
        f"statemachine.py 含死 import _patch_module：{dead_imports}\n"
        "M4.6 fix 后应已删除无引用的 import。"
    )
