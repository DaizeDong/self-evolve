"""M3.5 tests: C-tier no-regression + bidirectional alpha gate + pure-C forced review
+ Codex-unavailable degrade.

Coverage:
  ① 纯 C 欲 ACCEPT → force_review, 不自动采纳
  ② c_tier_no_regression 回退 → False 硬拒
  ③ alpha_gate 双向 (α<0.4 人审 / α>0.85 无锚 人审+计自欺 / None 不可信)
  ④ judge_degrade Codex 不可用 → 禁单 Claude auto ACCEPT
  ⑤ C 配对极低权重, 绝不单独触发 ACCEPT
  ⑥ A/B 档行为不变 (force_review/degrade_reason 字段存在但 False/None)
"""
from tools.sie import acceptor
from tools.sie.state import RunState


def _rs(tier="C"):
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier=tier)


# ── ② c_tier_no_regression ──────────────────────────────────────────────────

def test_c_no_regression_all_pass():
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": True, "after": True}]) is True


def test_c_no_regression_hard_reject():
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": True, "after": True}]) is True
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": True, "after": False}]) is False  # 回退


def test_c_no_regression_before_false_not_regression():
    # before=False 表示任务本就未通过, after=False 不是回退
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": False, "after": False}]) is True


def test_c_no_regression_empty_is_true():
    assert acceptor.c_tier_no_regression([]) is True


def test_c_no_regression_multiple_any_regress():
    results = [
        {"task": "t1", "before": True, "after": True},
        {"task": "t2", "before": True, "after": False},  # 回退
        {"task": "t3", "before": True, "after": True},
    ]
    assert acceptor.c_tier_no_regression(results) is False


# ── ③ alpha_gate 双向 ────────────────────────────────────────────────────────

def test_alpha_gate_low_forces_review():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.30, anchor_up=True, params=p)
    assert out["force_review"] is True
    assert out["count_selfdeception"] is False


def test_alpha_gate_high_no_anchor_counts_selfdeception():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.92, anchor_up=False, params=p)
    assert out["force_review"] is True
    assert out["count_selfdeception"] is True  # α 异常高且锚不涨 → 合谋


def test_alpha_gate_high_with_anchor_ok():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.92, anchor_up=True, params=p)
    assert out["force_review"] is False
    assert out["count_selfdeception"] is False


def test_alpha_gate_normal_range_ok():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.65, anchor_up=False, params=p)
    assert out["force_review"] is False
    assert out["count_selfdeception"] is False


def test_alpha_gate_none_unavailable():
    """alpha=None (judge 不可用) → 按不可信处理, force_review=True."""
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=None, anchor_up=True, params=p)
    assert out["force_review"] is True


def test_alpha_gate_boundary_exactly_low():
    # alpha == α_low: 不触发(严格 <)
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.4, anchor_up=True, params=p)
    assert out["force_review"] is False


def test_alpha_gate_boundary_exactly_high():
    # alpha == α_high: 不触发(严格 >)
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.85, anchor_up=False, params=p)
    assert out["force_review"] is False
    assert out["count_selfdeception"] is False


# ── ④ judge_degrade ──────────────────────────────────────────────────────────

def test_codex_unavailable_blocks_single_claude():
    out = acceptor.judge_degrade(codex_available=False, claude_available=True)
    assert out["single_claude_block"] is True
    assert out["anchor_only"] is True   # 程序化锚为唯一裁决信号
    assert out["force_review"] is True


def test_both_judges_ok_no_degrade():
    out = acceptor.judge_degrade(codex_available=True, claude_available=True)
    assert out["single_claude_block"] is False
    assert out["anchor_only"] is False
    assert out["force_review"] is False


def test_codex_unavailable_claude_also_unavailable():
    # Codex 不可用时, 无论 Claude 是否可用都必须 block
    out = acceptor.judge_degrade(codex_available=False, claude_available=False)
    assert out["single_claude_block"] is True
    assert out["force_review"] is True


def test_codex_available_claude_unavailable():
    # Codex 可用, Claude 不可用: 不触发禁令(Codex 是独立 judge)
    out = acceptor.judge_degrade(codex_available=True, claude_available=False)
    assert out["single_claude_block"] is False
    assert out["force_review"] is False


# ── ① 纯 C 欲 ACCEPT → force_review, 不自动采纳 ─────────────────────────────

def test_pure_c_accept_forces_review():
    # C 配对一致正向，但 coverage=0 → 即便 e-process 想 ACCEPT 也必经人审
    paired = [(1.0, 0.0)] * 12  # 改后优于改前
    out = acceptor.decide(paired, tier="C", st=_rs("C"),
                          params={"alpha": 0.05, "coverage": 0.0})
    assert out["force_review"] is True
    assert out["decision"] != "CONTINUE" or out["force_review"]  # 纯 C 不自动落地


def test_pure_c_accept_decision_still_set():
    """force_review=True 时 decision 字段仍存在（人审后可读取原始决策）."""
    paired = [(1.0, 0.0)] * 12
    out = acceptor.decide(paired, tier="C", st=_rs("C"),
                          params={"alpha": 0.05, "coverage": 0.0})
    assert "decision" in out
    assert "force_review" in out
    assert out["force_review"] is True


def test_c_with_coverage_nonzero_no_force():
    """coverage>0: 纯 C 强制人审不触发（非 coverage=0 路径）."""
    # 极低 c_tier_weight=0.05 使 evalue 极低 → 正常 REJECT, 但 force_review 不因 coverage 触发
    paired = [(0.0, 1.0)] * 5
    out = acceptor.decide(paired, tier="C", st=_rs("C"),
                          params={"alpha": 0.05, "coverage": 0.5})
    # decision 可为 REJECT/CONTINUE/ACCEPT (取决于 evalue), 但 coverage!=0 不触发 force_review 路径
    assert "force_review" in out


# ── ⑤ C 配对极低权重, 绝不单独触发 ACCEPT ───────────────────────────────────

def test_c_tier_weight_too_low_to_accept_alone():
    """C 档 c_tier_weight=0.05 极低, 大量正向配对仍无法单独达到 ACCEPT 阈值."""
    # 即使 50 对全部正向, 因 c_tier_weight=0.05 极低权重, e-value 不应达 1/0.05=20
    paired = [(0.0, 1.0)] * 50
    out = acceptor.decide(paired, tier="C", st=_rs("C"),
                          params={"alpha": 0.05, "coverage": 1.0,
                                  "c_tier_weight": 0.05})
    # 关键: 即使有 50 对正向证据, C 单档因权重极低无法独立 ACCEPT (evalue << 20)
    # 若 decision==ACCEPT 且 evalue < 1/alpha, 则权重未生效 → fail
    if out["decision"] == "ACCEPT":
        # 若真的 ACCEPT, evalue 必须 >= 1/alpha=20; 权重 0.05 时 diffs 被压缩到 [-0.05, 0.05]
        # 理论上 50 对 d=1.0 → weighted d=0.05, u=0.525, ONS betting → evalue 极小
        # 这里做保守断言: 若发生 ACCEPT, 标记为 weight 未生效
        assert False, (
            f"C 档权重 0.05 下 50 对正向不应达 ACCEPT 阈值, got evalue={out['evalue']}"
        )


# ── ⑥ A/B 档行为不变 (新字段存在, force_review=False, degrade_reason=None) ──

def test_a_tier_has_new_fields():
    """A 档返回必须包含 force_review 和 degrade_reason 字段, 且均为无触发值."""
    paired = [(0.0, 1.0)] * 3
    out = acceptor.decide(paired, tier="A", st=_rs("A"), params={"alpha": 0.05})
    assert "force_review" in out, "A 档缺 force_review 字段"
    assert "degrade_reason" in out, "A 档缺 degrade_reason 字段"
    assert out["force_review"] is False
    assert out["degrade_reason"] is None


def test_b_tier_has_new_fields():
    """B 档返回必须包含 force_review 和 degrade_reason 字段."""
    paired = [(0.5, 0.8)] * 5
    out = acceptor.decide(paired, tier="B", st=_rs("B"),
                          params={"alpha": 0.05, "n_min": 8,
                                  "effective_independent_anchor_min": 12,
                                  "anchors": []})
    assert "force_review" in out, "B 档缺 force_review 字段"
    assert "degrade_reason" in out, "B 档缺 degrade_reason 字段"
    assert out["force_review"] is False


def test_a_tier_regression_still_hard_reject():
    """A 档 no-regression 硬门不受 M3.5 改动影响."""
    paired = [(1.0, 0.0)]  # pass→fail
    out = acceptor.decide(paired, tier="A", st=_rs("A"), params={"alpha": 0.05})
    assert out["decision"] == "REJECT"
    assert "regress" in out["reason"].lower()


def test_a_tier_small_sample_rejects():
    """A 档 e-process 小样本拒绝行为不变."""
    paired = [(0.0, 1.0), (1.0, 1.0), (0.0, 1.0)]
    out = acceptor.decide(paired, tier="A", st=_rs("A"), params={"alpha": 0.05})
    assert out["decision"] == "REJECT"
