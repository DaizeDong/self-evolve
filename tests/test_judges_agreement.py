# tests/test_judges_agreement.py
"""TDD tests for M3.2: pairwise_agreement, debias_order, invoke_claude_judge.
All tests mock subprocess/invoke — no real claude calls."""
import json
import subprocess

import pytest

from tools.sie import judges, judge_claude


# ── Helper ──────────────────────────────────────────────────────────────────

def _sc(pairs):
    """Build a minimal score dict from (span, score) pairs."""
    return {
        "span_scores": [{"span": s, "score": v} for s, v in pairs],
        "available": True,
        "aggregate": sum(v for _, v in pairs) / len(pairs),
    }


# ── Step 1: pairwise_agreement 基础 ─────────────────────────────────────────

def test_agreement_identical_is_one():
    """完全相同的两判官打分 → α=1.0。"""
    a = _sc([("s1", 0.8), ("s2", 0.4), ("s3", 0.9)])
    assert judges.pairwise_agreement(a, a) == 1.0


def test_agreement_opposite_is_low():
    """完全相反的打分（1↔0）→ α<0.2。"""
    a = _sc([("s1", 1.0), ("s2", 0.0), ("s3", 1.0)])
    b = _sc([("s1", 0.0), ("s2", 1.0), ("s3", 0.0)])
    assert judges.pairwise_agreement(a, b) < 0.2


# ── Step 3: sentinel on unavailable ─────────────────────────────────────────

def test_agreement_unavailable_returns_sentinel():
    """任一判官不可用 → 返回 None（防下游将不可用误作真实低一致性分）。"""
    a = _sc([("s1", 0.5)])
    b = {"span_scores": [], "available": False, "aggregate": 0.0}
    assert judges.pairwise_agreement(a, b) is None


def test_agreement_both_unavailable_returns_sentinel():
    """两判官均不可用 → 返回 None。"""
    u = {"span_scores": [], "available": False, "aggregate": 0.0}
    assert judges.pairwise_agreement(u, u) is None


# ── 边界：无共同 span ────────────────────────────────────────────────────────

def test_agreement_no_common_spans_returns_zero():
    """两判官 span 集合无交集 → 0.0（保守）。"""
    a = _sc([("s1", 0.8)])
    b = _sc([("s2", 0.9)])
    assert judges.pairwise_agreement(a, b) == 0.0


def test_agreement_empty_spans_both():
    """两判官 span_scores 均为空 → 0.0（无共同 span）。"""
    a = {"span_scores": [], "available": True, "aggregate": 0.0}
    b = {"span_scores": [], "available": True, "aggregate": 0.0}
    assert judges.pairwise_agreement(a, b) == 0.0


# ── 对齐：缺失 span 只按 inner join 计算 ─────────────────────────────────────

def test_agreement_partial_overlap():
    """判官 A 覆盖 s1+s2，判官 B 覆盖 s2+s3 → 只按 s2 对齐，完全一致→1.0。"""
    a = _sc([("s1", 0.5), ("s2", 0.7)])
    b = _sc([("s2", 0.7), ("s3", 0.3)])
    assert judges.pairwise_agreement(a, b) == pytest.approx(1.0)


def test_agreement_partial_overlap_diverge():
    """partial overlap 且对齐 span 打分有差 → α 在中间区间。"""
    a = _sc([("s1", 0.9), ("s2", 0.5)])
    b = _sc([("s2", 0.0), ("s3", 0.8)])
    # 共同 s2: |0.5 - 0.0| = 0.5, MAD=0.5, α=0.5
    result = judges.pairwise_agreement(a, b)
    assert result == pytest.approx(0.5)


# ── debias_order ─────────────────────────────────────────────────────────────

def test_debias_order_sorts_by_span():
    """debias_order 按 span 文本升序排列。"""
    sc = _sc([("z_span", 0.1), ("a_span", 0.9), ("m_span", 0.5)])
    out = judges.debias_order(sc)
    spans = [x["span"] for x in out["span_scores"]]
    assert spans == sorted(spans)


def test_debias_order_preserves_scores():
    """debias_order 不修改分值，仅重排顺序。"""
    pairs = [("b", 0.3), ("a", 0.7), ("c", 0.5)]
    sc = _sc(pairs)
    out = judges.debias_order(sc)
    score_map = {x["span"]: x["score"] for x in out["span_scores"]}
    assert score_map == {"a": 0.7, "b": 0.3, "c": 0.5}


def test_debias_order_does_not_mutate_input():
    """debias_order 返回副本，不改变原 dict。"""
    sc = _sc([("z", 0.1), ("a", 0.9)])
    original_order = [x["span"] for x in sc["span_scores"]]
    _ = judges.debias_order(sc)
    assert [x["span"] for x in sc["span_scores"]] == original_order


def test_debias_order_empty():
    """空 span_scores → 返回 dict 含空列表，不报错。"""
    sc = {"span_scores": [], "available": True, "aggregate": 0.0}
    out = judges.debias_order(sc)
    assert out["span_scores"] == []


# ── invoke_claude_judge ──────────────────────────────────────────────────────

def test_invoke_claude_judge_success(monkeypatch):
    """returncode=0 with stdout → available=True, raw=stdout."""
    raw = '{"span_scores":[]}'

    class FakeProc:
        returncode = 0
        stdout = raw
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": True, "raw": raw}


def test_invoke_claude_judge_timeout(monkeypatch):
    """subprocess.TimeoutExpired → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_claude_judge_file_not_found(monkeypatch):
    """FileNotFoundError (node missing) → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("node not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_claude_judge_os_error(monkeypatch):
    """OSError → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_claude_judge_nonzero_exit(monkeypatch):
    """Non-zero returncode → available=False, no raise."""
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "rate limit"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_claude_judge_empty_stdout(monkeypatch):
    """returncode=0 but empty stdout → available=False."""
    class FakeProc:
        returncode = 0
        stdout = "   "
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_claude.invoke_claude_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_claude_judge_argv_contains_web_search(monkeypatch):
    """invoke_claude_judge 命令行必须含 --tools web_search（judge 隔离规则）。"""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeProc:
            returncode = 0
            stdout = '{"span_scores":[]}'
            stderr = ""

        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    judge_claude.invoke_claude_judge("test prompt", timeout_s=10)

    cmd = captured["cmd"]
    assert "--tools" in cmd, f"--tools missing in {cmd}"
    tools_idx = cmd.index("--tools")
    assert cmd[tools_idx + 1] == "web_search", f"expected web_search after --tools, got {cmd[tools_idx+1]}"


# ── score() family="claude" 走真 invoke（mock）──────────────────────────────

def test_score_family_claude_available(monkeypatch, tmp_path):
    """score() family=claude 走 invoke_claude_judge(mock) 返回完整契约。"""
    raw = json.dumps({"span_scores": [
        {"span": "Revenue grew 12%", "score": 0.85},
    ]})

    def fake_invoke(prompt, timeout_s):
        return {"available": True, "raw": raw}

    monkeypatch.setattr(judge_claude, "invoke_claude_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("Revenue grew 12% in FY2024.", encoding="utf-8")
    out = judges.score(str(art), [{"span": "Revenue grew 12%"}], family="claude")
    assert out["available"] is True
    assert out["family"] == "claude"
    assert abs(out["aggregate"] - 0.85) < 1e-9
    assert out["unspanned_penalized"] == 0
    assert len(out["span_scores"]) == 1


def test_score_family_claude_unavailable(monkeypatch, tmp_path):
    """score() family=claude, invoke 返回 available=False → 契约 sentinel。"""
    def fake_invoke(prompt, timeout_s):
        return {"available": False, "raw": ""}

    monkeypatch.setattr(judge_claude, "invoke_claude_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("body", encoding="utf-8")
    out = judges.score(str(art), [{"span": "s1"}, {"span": "s2"}], family="claude")
    assert out["available"] is False
    assert out["family"] == "claude"
    assert out["aggregate"] == 0.0
    assert out["span_scores"] == []
    assert out["unspanned_penalized"] == 2
