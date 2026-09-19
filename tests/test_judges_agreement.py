import sys
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

def test_invoke_claude_judge_contract(monkeypatch):
    from tools.sie import agents, judge_claude
    from llmcall import Result
    calls = []
    def answer(prompt, **kw):
        calls.append(kw)
        return Result(provider="synthetic", text='{"span_scores":[]}',
                      model_family="claude", model_source="provider_reported")
    monkeypatch.setattr(sys.modules["llmcall"], "call", answer)
    result = judge_claude.invoke_claude_judge("synthetic", timeout_s=12)
    assert result["available"]
    assert len(calls) == 1
    assert calls[0]["requirements"].tool_allowlist == ("WebSearch",)
    assert calls[0]["requirements"].access == "read_only"
    assert calls[0]["selection"].intent == "inherit"
    assert "effort" not in calls[0]


def test_invoke_claude_judge_failure(monkeypatch):
    from tools.sie import agents, judge_claude
    from llmcall import Result
    calls = []
    def fail(*a, **kw):
        calls.append(kw)
        return Result(error="timeout", effects="possible")
    monkeypatch.setattr(sys.modules["llmcall"], "call", fail)
    result = judge_claude.invoke_claude_judge("synthetic")
    assert not result["available"] and result["raw"] == ""
    assert len(calls) == 1
