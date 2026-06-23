"""统一 agent 调用层 + 异质交叉校验原语测试（mock subprocess, 不调真 agent）。

锁住: codex 可作任意阶段的 agent 选项; cross_check 是可复用的异质校验原语。
"""
import subprocess
from types import SimpleNamespace
import pytest

from tools.sie import agents


def _fake_run_factory(by_family: dict):
    """by_family: {family: (returncode, stdout)}; 缺失家族→视为不可用(rc=1)。"""
    def fake_run(cmd, **kw):
        fam = cmd[cmd.index("--family") + 1] if "--family" in cmd else "?"
        rc, out = by_family.get(fam, (1, ""))
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")
    return fake_run


def test_invoke_ok(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory({"codex": (0, "hello from codex")}))
    r = agents.invoke("prompt", family="codex")
    assert r["ok"] is True and r["family"] == "codex" and "codex" in r["result"]


def test_invoke_invalid_family():
    r = agents.invoke("p", family="bogus")
    assert r["ok"] is False


def test_invoke_nonzero_or_empty(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({"claude": (1, "")}))
    assert agents.invoke("p", family="claude")["ok"] is False
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({"claude": (0, "   ")}))
    assert agents.invoke("p", family="claude")["ok"] is False


def test_invoke_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert agents.invoke("p", family="codex")["ok"] is False


def test_cross_check_heterogeneous(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({
        "claude": (0, "claude says X"), "codex": (0, "codex says X"),
    }))
    cc = agents.cross_check("p", families=("claude", "codex"))
    assert cc["n_ok"] == 2 and cc["heterogeneous"] is True
    assert len(cc["results_ok"]) == 2


def test_cross_check_one_unavailable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({"claude": (0, "ok")}))
    cc = agents.cross_check("p", families=("claude", "codex"))
    assert cc["n_ok"] == 1 and cc["heterogeneous"] is False


def test_cross_check_verdicts_agree(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({
        "claude": (0, '{"verdict":"accept","notes":[]}'),
        "codex": (0, 'prose {"verdict":"accept"} more'),
    }))
    r = agents.cross_check_verdicts("p", families=("claude", "codex"))
    assert r["verdicts"] == {"claude": "accept", "codex": "accept"}
    assert r["agree"] is True and r["n_ok"] == 2


def test_cross_check_verdicts_disagree(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({
        "claude": (0, '{"verdict":"accept"}'),
        "codex": (0, '{"verdict":"reject"}'),
    }))
    r = agents.cross_check_verdicts("p", families=("claude", "codex"))
    assert r["agree"] is False


def test_cross_check_verdicts_single_valid_is_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run_factory({
        "claude": (0, '{"verdict":"accept"}'),  # codex unavailable
    }))
    r = agents.cross_check_verdicts("p", families=("claude", "codex"))
    assert r["agree"] is None and r["n_ok"] == 1
