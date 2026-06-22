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
    # evalue_max_step 使用大默认值 (1e6), 使总量钳对正常测试无效;
    # 需测试钳功能时显式传入低 evalue_max_step.
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "evalue_max_step": 1e6, "continue_count_cap": 5, "anchors": anchors}
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


# ---------------------------------------------------------------------------
# M2.6 修复测试
# ---------------------------------------------------------------------------

def test_b_tier_strong_gain_not_full_before_should_accept():
    """B 档 before_gain=1.0, after_gain=0.8 (仍强增益) + 足量独立锚 → 不被 no-regression 门误拒 → ACCEPT.

    修复前: 顶层 no-regression 门误判 (1.0, 0.8) → before>=1.0>after 为退化 → REJECT (无 effective_independent 键).
    修复后: no-regression 门仅在 A 档执行; B 档 before_gain=1.0 合法浮点, 不代表 pass→fail.
    """
    # 30 个锚; 部分 before=1.0(满分增益浮点), after=0.9(强增益), diff=-0.1;
    # 另 20 锚大正增益 diff=+0.8; 整体 e-value >> 20 → ACCEPT
    paired_mixed = [(1.0, 0.9)] * 10 + [(0.0, 0.8)] * 20  # 30 锚; 混合正负 diff 整体强正
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "continue_count_cap": 5, "anchors": _indep_anchors(30)}
    out = acceptor.decide(paired_mixed, "B", _st(), p)
    # 不应因 no-regression 门被误 REJECT (B 档 before=1.0 是浮点增益, 非二态 pass/fail)
    assert "regress" not in out.get("reason", "").lower(), (
        f"B 档不应触发 no-regression 门: {out}")
    assert out["decision"] == "ACCEPT", (
        f"B 档足量正增益锚 + before=1.0 不退化 → 应 ACCEPT, got {out}")
    assert "effective_independent" in out, f"返回 dict 缺 effective_independent: {out}"
    assert "n_anchor" in out, f"返回 dict 缺 n_anchor: {out}"


def test_b_tier_before_full_gain_accept_with_real_positive_diff():
    """B 档足量锚含 before_gain=1.0 且整体强正增益 → 不被 no-regression 门误拒 → ACCEPT."""
    # 30 互异源; 混入 before=1.0 的锚 (B 档满分增益浮点, 不代表退化)
    # diff: (1.0,1.0)→0; (0.0,0.9)→+0.9 大增益; 整体强正增益 → e-value >> 20 → ACCEPT
    paired = [(1.0, 1.0)] * 4 + [(0.0, 0.9)] * 26  # 30 锚, 混入 before=1.0 但整体强正增益
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "continue_count_cap": 5, "anchors": _indep_anchors(30)}
    out = acceptor.decide(paired, "B", _st(), p)
    assert out["decision"] == "ACCEPT", (
        f"B 档强正增益 + 足量独立锚 + before=1.0 不退化 → 应 ACCEPT, got {out}")
    assert "regress" not in out.get("reason", "").lower(), (
        f"B 档不应触发 no-regression 门: {out}")


def test_evalue_clamped_to_step_cap():
    """构造会使 e-value 超 step_cap 的输入 → evalue 被钳到 step_cap."""
    # 50 锚最大正增益 → e-value 本应远超 25.0; step_cap=25.0 → evalue 应被钳到 <= 25.0
    # _params 默认 evalue_max_step=5.0, 此处显式覆盖为 25.0 (验证总量钳机制)
    paired = [(0.0, 1.0)] * 50   # 50 锚, 最大正增益, 无截断时 e-value >> 25
    p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
         "continue_count_cap": 5, "anchors": _indep_anchors(50), "evalue_max_step": 25.0}
    out = acceptor.decide(paired, "B", _st(), p)
    assert out["evalue"] <= 25.0 + 1e-9, (
        f"evalue 应被钳到 step_cap=25.0, got {out['evalue']}")
    # 验证确实被截断 (e-value 不加钳时远超 25.0)
    p_nocap = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
               "continue_count_cap": 5, "anchors": _indep_anchors(50)}
    out_nocap = acceptor.decide(paired, "B", _st(), p_nocap)
    assert out_nocap["evalue"] > 25.0, (
        f"无 step_cap 限制时 evalue 应远超 25.0 (验证钳有效), got {out_nocap['evalue']}")
    assert "effective_independent" in out
    assert "n_anchor" in out


def test_all_b_reject_paths_contain_required_keys():
    """所有 B 档 REJECT 路径均含 effective_independent 和 n_anchor 键."""
    # 门1 REJECT
    out1 = acceptor.decide([(0.0, 0.5)] * 5, "B", _st(), _params(_indep_anchors(5)))
    assert out1["decision"] == "REJECT"
    assert "effective_independent" in out1 and "n_anchor" in out1, f"门1 REJECT 缺键: {out1}"

    # 门2 REJECT
    out2 = acceptor.decide([(0.0, 0.5)] * 10, "B", _st(), _params(_same_source(10)))
    assert out2["decision"] == "REJECT"
    assert "effective_independent" in out2 and "n_anchor" in out2, f"门2 REJECT 缺键: {out2}"

    # 低 e-value REJECT (三门全过但证据不足)
    out3 = acceptor.decide([(0.0, 0.001)] * 16, "B", _st(),
                           _params(_indep_anchors(16), continue_count_cap=0))
    assert out3["decision"] in ("REJECT", "CONTINUE")
    assert "effective_independent" in out3 and "n_anchor" in out3, f"低 e-value 路径缺键: {out3}"
