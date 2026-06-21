"""M2.6: B 档 per-anchor 配对 + n_min/独立性下限门 测试.

三道硬门先于 e-value:
  1. n_anchor >= n_min (默认 8) — 锚数下限
  2. effective_independent_count >= effective_independent_anchor_min (默认 12) — 独立性下限
  3. evalue_max_step 单轮上限钳 (防一锚爆表)
三门全过 + e-value >= 1/α → ACCEPT
B 是随机档, 中间区允许 CONTINUE; A 档不允许 CONTINUE
"""
from tools.sie import acceptor
from tools.sie.state import RunState


def _st():
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="B")


def _params(anchors, **kw):
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "evalue_max_step": 5.0, "continue_count_cap": 5, "anchors": anchors}
    p.update(kw)
    return p


def _indep_anchors(n):
    """n 个互异源 (不同 host + cik) → effective_independent = n."""
    return [{"anchor_id": f"a{i}", "verified": True, "source_url": f"https://h{i}.com/x",
             "cik": str(i), "period": "FY"} for i in range(n)]


def _same_source(n):
    """n 个完全同源 → effective_independent = floor(1 + log2(n))."""
    return [{"anchor_id": f"a{i}", "verified": True, "source_url": "https://sec.gov/x",
             "cik": "1", "period": "FY2024"} for i in range(n)]


# ---------------------------------------------------------------------------
# 门1: n_anchor 下限
# ---------------------------------------------------------------------------

def test_reject_when_too_few_anchors():
    """n_anchor=5 < n_min=8 → REJECT, reason 含 n_anchor."""
    paired = [(0.0, 0.1)] * 5   # n_anchor=5 < n_min 8
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(5)))
    assert out["decision"] == "REJECT", f"expected REJECT, got {out}"
    assert "n_anchor" in out["reason"], f"reason should mention n_anchor: {out['reason']}"


def test_reject_when_exactly_n_min_minus_1():
    """n_anchor=7 = n_min-1=7 → REJECT."""
    paired = [(0.0, 0.5)] * 7
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(7)))
    assert out["decision"] == "REJECT"


# ---------------------------------------------------------------------------
# 门2: 有效独立锚下限 (小相关锚集)
# ---------------------------------------------------------------------------

def test_reject_small_correlated_anchor_set():
    """8 同源锚: n_anchor=8 过门1, 但 effective_independent=floor(1+log2(8))=4 < 12 → REJECT."""
    import math
    paired = [(0.0, 0.005)] * 8
    out = acceptor.decide(paired, "B", _st(), _params(_same_source(8)))
    assert out["decision"] == "REJECT", f"expected REJECT, got {out}"
    assert "effective_independent" in out["reason"], f"reason should mention effective_independent: {out['reason']}"
    expected_eff = int(math.floor(1 + math.log2(8)))  # = 4
    assert out["effective_independent"] == expected_eff, (
        f"effective_independent should be {expected_eff}, got {out['effective_independent']}")


def test_reject_correlated_set_even_with_high_gain():
    """就算增益很大, 小相关锚集仍不得 ACCEPT."""
    paired = [(0.0, 0.9)] * 8   # 强增益
    out = acceptor.decide(paired, "B", _st(), _params(_same_source(8)))
    assert out["decision"] == "REJECT"


# ---------------------------------------------------------------------------
# 三门全过: ACCEPT / CONTINUE
# ---------------------------------------------------------------------------

def test_accept_strong_independent_gain():
    """24 互异源, 大真增益 (after-before=0.4 per anchor) → 三门全过 → ACCEPT."""
    paired = [(0.0, 0.4)] * 24   # 24 互异源, 大真增益
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(24)))
    assert out["decision"] == "ACCEPT", f"expected ACCEPT, got {out}"
    assert out["effective_independent"] >= 12, (
        f"effective_independent should be >= 12, got {out['effective_independent']}")


def test_continue_on_marginal_evidence_is_random_tier():
    """足量锚+足量独立, 但增益弱 → e-value 低 → CONTINUE 或 REJECT (绝不 ACCEPT)."""
    paired = [(0.0, 0.01)] * 16   # 弱增益
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(16)))
    assert out["decision"] in ("CONTINUE", "REJECT"), f"expected CONTINUE or REJECT, got {out}"
    assert out["decision"] != "ACCEPT", f"should NOT ACCEPT on marginal evidence"


# ---------------------------------------------------------------------------
# 返回键完整性
# ---------------------------------------------------------------------------

def test_return_dict_contains_effective_independent_and_n_anchor():
    """返回 dict 必须含 effective_independent 和 n_anchor 键."""
    paired = [(0.0, 0.1)] * 5   # 触发门1 REJECT, 但还是要有这两个键
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(5)))
    assert "effective_independent" in out, f"missing effective_independent key: {out}"
    assert "n_anchor" in out, f"missing n_anchor key: {out}"


def test_return_n_anchor_value_is_correct():
    """n_anchor 返回值与 len(paired) 一致."""
    paired = [(0.0, 0.3)] * 10
    out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(3)))
    # n_anchor 过门1 (10>=8), 但独立锚3<12 → 门2拦截
    assert out["n_anchor"] == 10, f"n_anchor should be 10, got {out['n_anchor']}"


# ---------------------------------------------------------------------------
# A 档回归: B 分支不影响 A 档
# ---------------------------------------------------------------------------

def test_a_tier_unaffected_by_b_tier_changes():
    """A 档: 大样本强增益 → ACCEPT; A 档不走 B 分支."""
    from tools.sie.state import RunState
    st_a = RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="A")
    paired = [(0.0, 1.0)] * 100   # 强增益 + 足量样本
    out = acceptor.decide(paired, "A", st_a, {"alpha": 0.05})
    assert out["decision"] == "ACCEPT", f"A 档强增益应 ACCEPT, got {out}"
    assert "decision" in out and "evalue" in out and "reason" in out


def test_a_tier_no_regression_hard_gate_still_works():
    """A 档 no-regression 硬门不受 B 分支影响."""
    from tools.sie.state import RunState
    st_a = RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="A")
    paired = [(1.0, 0.0)]   # pass→fail 退化
    out = acceptor.decide(paired, "A", st_a, {"alpha": 0.05})
    assert out["decision"] == "REJECT"
    assert "regress" in out["reason"].lower()


# ---------------------------------------------------------------------------
# 缺 params["anchors"] 时保守拒绝
# ---------------------------------------------------------------------------

def test_missing_anchors_key_treats_as_zero():
    """params 缺 'anchors' 键 → effective_independent=0 < 12 → 门2 REJECT."""
    paired = [(0.0, 0.5)] * 10
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "evalue_max_step": 5.0}  # 无 anchors 键
    out = acceptor.decide(paired, "B", _st(), p)
    assert out["decision"] == "REJECT"
    assert out["effective_independent"] == 0
