"""M4.4: supervisor 双进程裁决 loader 测试。

安全核心：
- load_frozen_decider 从 frozen_dir 加载，绝不加载 candidate 版本
- candidate worktree 不进 sys.path / 解析路径
- Supervisor.decide 用 frozen acceptor，不从 candidate import
- frozen 缺模块 → ImmutableViolation
- 隔离 import 后 sys.path/sys.modules 无残留
"""
import os
import sys
import pathlib
import pytest
from tools.sie import supervisor as sup
from tools.sie import immutable as im


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_frozen(tmp_path, acceptor_src):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "acceptor.py").write_text(acceptor_src, encoding="utf-8")
    return str(frozen)


# ---------------------------------------------------------------------------
# Step 1 / Step 2: loader 从 frozen 加载正确版本
# ---------------------------------------------------------------------------

def test_load_frozen_decider_returns_frozen_version(tmp_path):
    src = (
        "MARK = 'FROZEN'\n"
        "def decide(paired, tier, st, params):\n"
        "    return {'decision':'REJECT','evalue':0.0,'reason':'frozen'}\n"
    )
    frozen = _make_frozen(tmp_path, src)
    mod = sup.load_frozen_decider(frozen, "acceptor")
    assert mod.MARK == "FROZEN"
    assert mod.decide([], "A", None, {})["reason"] == "frozen"


def test_load_frozen_decider_does_not_pollute_sys_path(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    before = list(sys.path)
    sup.load_frozen_decider(frozen, "acceptor")
    assert sys.path == before, "frozen 目录泄漏到全局 sys.path"


def test_candidate_path_is_isolated(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    cand = tmp_path / "candidate" / "tools" / "sie"
    cand.mkdir(parents=True)
    assert sup.candidate_path_is_isolated(frozen, str(cand)) is True


# ---------------------------------------------------------------------------
# Step 5 / Step 6: Supervisor 用 frozen acceptor，不用 candidate 篡改版
# ---------------------------------------------------------------------------

def test_supervisor_decide_uses_frozen_not_candidate(tmp_path):
    # frozen acceptor 永远 REJECT；candidate 工作区放一个永远 ACCEPT 的伪 acceptor。
    frozen_src = (
        "def decide(paired, tier, st, params):\n"
        "    return {'decision':'REJECT','evalue':0.0,'reason':'frozen_rule'}\n"
    )
    frozen = _make_frozen(tmp_path, frozen_src)
    digests = {"acceptor.py": im.hash_file(os.path.join(frozen, "acceptor.py"))}
    cand_sie = tmp_path / "candidate" / "tools" / "sie"
    cand_sie.mkdir(parents=True)
    (cand_sie / "acceptor.py").write_text(
        "def decide(paired, tier, st, params):\n"
        "    return {'decision':'ACCEPT','evalue':9.9,'reason':'candidate_cheats'}\n",
        encoding="utf-8",
    )
    s = sup.Supervisor(frozen, digests)
    res = s.decide([(0.0, 0.0)], "A", None, {})
    assert res["decision"] == "REJECT" and res["reason"] == "frozen_rule"


# ---------------------------------------------------------------------------
# frozen 缺模块 → ImmutableViolation
# ---------------------------------------------------------------------------

def test_load_frozen_decider_missing_module_raises(tmp_path):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    # 不写 acceptor.py
    with pytest.raises(im.ImmutableViolation):
        sup.load_frozen_decider(str(frozen), "acceptor")


# ---------------------------------------------------------------------------
# 隔离 import 后 sys.modules 无残留（唯一名不污染标准名空间）
# ---------------------------------------------------------------------------

def test_load_frozen_decider_no_standard_name_in_sys_modules(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    # 清除可能存在的残留（其他测试产物）
    sys.modules.pop("acceptor", None)
    sup.load_frozen_decider(frozen, "acceptor")
    # 标准名 "acceptor" 不应出现在 sys.modules（用唯一名注册）
    assert "acceptor" not in sys.modules, "标准名 'acceptor' 不应污染 sys.modules"


# ---------------------------------------------------------------------------
# candidate worktree 不在 sys.path 时 candidate_path_is_isolated 返回 True
# 若 candidate 实际在 sys.path 上则返回 False
# ---------------------------------------------------------------------------

def test_candidate_path_is_isolated_false_when_in_sys_path(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    cand = tmp_path / "candidate"
    cand.mkdir(parents=True)
    # 将 candidate 推入 sys.path 模拟污染
    sys.path.insert(0, str(cand))
    try:
        result = sup.candidate_path_is_isolated(str(frozen), str(cand))
        assert result is False, "candidate 在 sys.path 时应返回 False"
    finally:
        sys.path.remove(str(cand))


def test_candidate_path_is_isolated_false_when_cwd_is_candidate(tmp_path, monkeypatch):
    """隔离漏洞修复：空串 sys.path 项展开为 cwd，若 cwd==candidate 应返回 False"""
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    cand = tmp_path / "candidate"
    cand.mkdir(parents=True)
    # 将 candidate 作为 cwd 并在 sys.path 中放入空串（代表 cwd）
    monkeypatch.chdir(str(cand))
    sys.path.insert(0, "")
    try:
        result = sup.candidate_path_is_isolated(str(frozen), str(cand))
        assert result is False, "cwd==candidate 且 sys.path 含空串时应返回 False（隔离破裂）"
    finally:
        sys.path.remove("")


def test_candidate_path_isolated_true_when_worktree_under_path_entry(tmp_path, monkeypatch):
    """方向修复：worktree 是 sys.path 条目(如 repo/cwd)的**子目录**时仍隔离(True)——
    子孙关系不让 candidate 的包被 import(import 仍解析到该条目自己的包)。
    （回归: 早期实现用 cand.startswith(pr) 误判此为不隔离, 致 --self 无法运行）"""
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    parent = tmp_path / "repo"
    cand = parent / ".sie" / "wt"
    cand.mkdir(parents=True)
    monkeypatch.chdir(str(parent))      # cwd = parent(candidate 的祖先), 非 candidate 本身
    sys.path.insert(0, "")
    try:
        assert sup.candidate_path_is_isolated(str(frozen), str(cand)) is True, \
            "worktree 在 cwd 子目录下(cwd≠worktree)应判隔离"
    finally:
        sys.path.remove("")


def test_candidate_path_isolated_false_when_subdir_on_path(tmp_path):
    """风险方向(b): candidate 的**子目录**在 sys.path 上 → candidate 代码可 import → False。"""
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    cand = tmp_path / "candidate"
    sub = cand / "pkg"
    sub.mkdir(parents=True)
    sys.path.insert(0, str(sub))
    try:
        assert sup.candidate_path_is_isolated(str(frozen), str(cand)) is False, \
            "candidate 子目录在 sys.path 上应判不隔离"
    finally:
        sys.path.remove(str(sub))


def test_load_frozen_decider_sys_modules_cleanup(tmp_path):
    """load-and-pop：exec 后唯一名应从 sys.modules 移除，防止跨版本污染"""
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    uniq = "sie_frozen_acceptor"
    # 确保初始不存在
    sys.modules.pop(uniq, None)
    sup.load_frozen_decider(frozen, "acceptor")
    # exec 后唯一名应被移除
    assert uniq not in sys.modules, f"唯一名 {uniq} 应在 exec 后清除"


# ---------------------------------------------------------------------------
# M4.5: 自举禁 candidate grade()（用 frozen/外部 grader）
# ---------------------------------------------------------------------------

def test_candidate_grade_is_trusted():
    """candidate_grade_is_trusted: 自举→False, 非自举→True。"""
    assert sup.candidate_grade_is_trusted(self_mode=True) is False
    assert sup.candidate_grade_is_trusted(self_mode=False) is True


def test_supervisor_grade_self_mode_uses_frozen_grader(tmp_path):
    """self_mode=True 时用 frozen verifiable.grade_pytest(sandbox_root)；candidate 撒谎的 grade() 被忽略。

    构造：
    - frozen verifiable.grade_pytest 永远返回 task_passed=False（grader_exit_code=1, graded_by=FROZEN）。
    - candidate 目录存在但不含任何 grade()；即使 candidate 有一个 grade() 返回 task_passed=True，
      Supervisor.grade 也绝不调用它——因为它走的是 frozen verifiable.grade_pytest。
    断言：结果必须来自 frozen grader（task_passed=False, graded_by='FROZEN'）。
    """
    # 构造 frozen 目录（含 acceptor.py + verifiable.py）
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "acceptor.py").write_text(
        "def decide(p, t, s, pa):\n"
        "    return {'decision': 'REJECT', 'evalue': 0.0, 'reason': 'x'}\n",
        encoding="utf-8",
    )
    (frozen / "verifiable.py").write_text(
        "def grade_pytest(sandbox_root):\n"
        "    return {'task_passed': False, 'grader_exit_code': 1,\n"
        "            'dimensions': [{'name': 't', 'tier': 'A', 'score': 0.0, 'weight': 1.0}],\n"
        "            'anchors': [], 'verifiable_coverage': 1.0, 'graded_by': 'FROZEN'}\n",
        encoding="utf-8",
    )

    digests = {
        "acceptor.py": im.hash_file(str(frozen / "acceptor.py")),
        "verifiable.py": im.hash_file(str(frozen / "verifiable.py")),
    }

    # candidate 目录,不含 grade()，但即使含有也会被忽略。
    cand = tmp_path / "cand"
    cand.mkdir()
    # 若 candidate 内部有一个"撒谎"grade()，它永远不会被 Supervisor.grade 调用。
    (cand / "grade.py").write_text(
        "def grade():\n    return {'task_passed': True, 'grader_exit_code': 0,"
        " 'graded_by': 'CANDIDATE_LIE'}\n",
        encoding="utf-8",
    )

    s = sup.Supervisor(str(frozen), digests)
    res = s.grade({"id": "t1"}, str(cand), self_mode=True)

    # frozen grader 的结果：task_passed=False, graded_by=FROZEN
    assert res["task_passed"] is False, "frozen grader 判 False，candidate 的 grade 不应被采信"
    assert res["grader_exit_code"] == 1
    assert res.get("graded_by") == "FROZEN"


def test_supervisor_grade_self_mode_false_raises(tmp_path):
    """self_mode=False 时 Supervisor.grade 应 raise RuntimeError（非自举走其他路径）。"""
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "acceptor.py").write_text(
        "def decide(p, t, s, pa):\n"
        "    return {'decision': 'REJECT', 'evalue': 0.0, 'reason': 'x'}\n",
        encoding="utf-8",
    )
    digests = {"acceptor.py": im.hash_file(str(frozen / "acceptor.py"))}
    cand = tmp_path / "cand"
    cand.mkdir()
    s = sup.Supervisor(str(frozen), digests)
    with pytest.raises(RuntimeError):
        s.grade({"id": "t1"}, str(cand), self_mode=False)


def test_supervisor_grade_uses_load_frozen_decider_for_verifiable(tmp_path):
    """frozen verifiable 经由 load_frozen_decider 加载（隔离机制），不污染 sys.modules。"""
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "acceptor.py").write_text(
        "def decide(p, t, s, pa):\n"
        "    return {'decision': 'REJECT', 'evalue': 0.0, 'reason': 'x'}\n",
        encoding="utf-8",
    )
    (frozen / "verifiable.py").write_text(
        "FROZEN_MARKER = 'FROZEN_VERIFIABLE'\n"
        "def grade_pytest(sandbox_root):\n"
        "    return {'task_passed': True, 'grader_exit_code': 0,\n"
        "            'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0,\n"
        "            'graded_by': 'FROZEN'}\n",
        encoding="utf-8",
    )
    digests = {
        "acceptor.py": im.hash_file(str(frozen / "acceptor.py")),
        "verifiable.py": im.hash_file(str(frozen / "verifiable.py")),
    }
    cand = tmp_path / "cand"
    cand.mkdir()

    # 确保标准名 "verifiable" 不在 sys.modules（防止干扰）
    sys.modules.pop("verifiable", None)
    sys.modules.pop("sie_frozen_verifiable", None)

    s = sup.Supervisor(str(frozen), digests)
    res = s.grade({"id": "t2"}, str(cand), self_mode=True)

    # 结果应来自 frozen verifiable
    assert res.get("graded_by") == "FROZEN"
    assert res["task_passed"] is True

    # load_frozen_decider 的 load-and-pop：唯一名不应残留在 sys.modules
    assert "sie_frozen_verifiable" not in sys.modules, "唯一名不应残留"
    assert "verifiable" not in sys.modules, "标准名不应污染 sys.modules"
