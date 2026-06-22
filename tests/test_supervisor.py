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


def test_load_frozen_decider_sys_modules_cleanup(tmp_path):
    """load-and-pop：exec 后唯一名应从 sys.modules 移除，防止跨版本污染"""
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    uniq = "sie_frozen_acceptor"
    # 确保初始不存在
    sys.modules.pop(uniq, None)
    sup.load_frozen_decider(frozen, "acceptor")
    # exec 后唯一名应被移除
    assert uniq not in sys.modules, f"唯一名 {uniq} 应在 exec 后清除"
