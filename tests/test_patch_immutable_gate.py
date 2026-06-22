"""M4.3: IMMUTABLE 路径硬拒门单测 + apply_patch 集成测试。"""
import os
import subprocess as sp

from tools.sie.patch import immutable_gate, apply_patch


# ---------------------------------------------------------------------------
# immutable_gate 单元测试
# ---------------------------------------------------------------------------

def test_gate_rejects_immutable_when_enforce():
    res = immutable_gate(["acceptor.py"], enforce=True)
    assert res is not None and res["decision"] == "REJECT"
    assert res["reason"] == "immutable_hit"
    assert "acceptor.py" in res["paths"]


def test_gate_rejects_gate_human_and_judges():
    for p in ["gate_human.py", "judges.py", "tools/sie/selfdeception.py"]:
        res = immutable_gate([p], enforce=True)
        assert res is not None and res["reason"] == "immutable_hit"


def test_gate_allows_non_immutable_when_enforce():
    assert immutable_gate(["propose.py", "reflect.py"], enforce=True) is None


def test_gate_noop_when_not_enforce():
    # 默认关(非自举)：连 acceptor 也不在这里拦
    assert immutable_gate(["acceptor.py"], enforce=False) is None


def test_gate_reports_all_hit_paths():
    res = immutable_gate(["propose.py", "acceptor.py", "judges.py"], enforce=True)
    assert set(res["paths"]) == {"acceptor.py", "judges.py"}


# ---------------------------------------------------------------------------
# apply_patch 集成测试（enforce_immutable 参数）
# ---------------------------------------------------------------------------

def _make_sandbox(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "seed.txt").write_text("x")
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "i"], cwd=r, check=True)
    return str(r)


def test_apply_patch_rejects_immutable_when_enforce(tmp_path):
    """enforce_immutable=True 时写 IMMUTABLE 路径 → REJECT immutable_hit。"""
    root = _make_sandbox(tmp_path)
    res = apply_patch(root, "acceptor.py", "x = 1\n", enforce_immutable=True)
    assert res["status"] == "REJECT"
    assert "immutable_hit" in res["reason"]
    # 文件不得落盘
    assert not os.path.exists(os.path.join(root, "acceptor.py"))


def test_apply_patch_allows_normal_when_enforce(tmp_path):
    """enforce_immutable=True 时写普通路径 → 放行(继续 AST 门)。"""
    root = _make_sandbox(tmp_path)
    res = apply_patch(root, "propose.py", "x = 1\n", enforce_immutable=True)
    assert res["status"] == "APPLIED"


def test_apply_patch_default_enforce_false(tmp_path):
    """enforce_immutable 默认 False → IMMUTABLE 路径也放行（向后兼容）。"""
    root = _make_sandbox(tmp_path)
    # 不传 enforce_immutable（默认 False），写 acceptor.py 应正常落盘
    res = apply_patch(root, "acceptor.py", "x = 1\n")
    assert res["status"] == "APPLIED"
    assert os.path.exists(os.path.join(root, "acceptor.py"))
