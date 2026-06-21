"""tests/test_selfdeception.py — M3.4 多闸完整测试套件。

测试覆盖:
  闸① retained_visible_gain: 新增锚不计当轮增益，只算留存锚 span 交集
  闸② block_accept: visible 留存增益 < eps → block_accept=True
  闸③ force_review/force_human: visible 涨而 holdout 不涨 → 过拟合报警 + 强制人审
  闸④ cumulative_drift: 累计漂移预算边界测试
"""
from tools.sie import selfdeception as sd
from tools.sie.state import RunState


def _rs(**kw):
    base = dict(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="C")
    base.update(kw)
    return RunState(**base)


# ---------------------------------------------------------------------------
# 闸① retained_visible_gain: 新增锚不计当轮增益
# ---------------------------------------------------------------------------

def test_new_anchors_not_counted():
    prev = [{"span": "a", "verified": True, "marginal_gain": 0.3}]
    # cur 多了新锚 b（高增益），但只算留存锚 a → 留存增益用 a 的，新锚 b 不计
    cur = [{"span": "a", "verified": True, "marginal_gain": 0.3},
           {"span": "b", "verified": True, "marginal_gain": 0.9}]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - 0.0) < 1e-9  # a 增益未变 → 留存增益 0，b(新锚)不计


def test_retained_gain_only_intersection():
    """只计 prev∩cur span 的增益变化；prev 独有 / cur 独有均不计。"""
    prev = [
        {"span": "x", "marginal_gain": 0.1},
        {"span": "y", "marginal_gain": 0.2},
    ]
    cur = [
        {"span": "y", "marginal_gain": 0.5},   # 留存，增益 +0.3
        {"span": "z", "marginal_gain": 0.9},   # 新锚，不计
    ]
    g = sd.retained_visible_gain(prev, cur)
    # 仅 y 留存: (0.5-0.2)/1 = 0.3
    assert abs(g - 0.3) < 1e-9


def test_retained_gain_no_overlap_returns_zero():
    """prev 与 cur 无公共 span → 返回 0.0。"""
    prev = [{"span": "a", "marginal_gain": 0.5}]
    cur = [{"span": "b", "marginal_gain": 0.8}]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - 0.0) < 1e-9


def test_retained_gain_decrease():
    """留存锚增益下降 → 返回负值。"""
    prev = [{"span": "p", "marginal_gain": 0.6}]
    cur = [{"span": "p", "marginal_gain": 0.2}]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - (-0.4)) < 1e-9


def test_retained_gain_empty_prev():
    """prev 为空 → 无留存锚 → 返回 0.0。"""
    prev = []
    cur = [{"span": "a", "marginal_gain": 0.9}]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - 0.0) < 1e-9


def test_retained_gain_multiple_retained():
    """多个留存锚：返回平均增益变化。"""
    prev = [
        {"span": "a", "marginal_gain": 0.1},
        {"span": "b", "marginal_gain": 0.3},
    ]
    cur = [
        {"span": "a", "marginal_gain": 0.3},   # +0.2
        {"span": "b", "marginal_gain": 0.5},   # +0.2
        {"span": "c", "marginal_gain": 0.9},   # 新锚，不计
    ]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - 0.2) < 1e-9


# ---------------------------------------------------------------------------
# 闸② block_accept: visible 留存增益 < eps
# ---------------------------------------------------------------------------

def test_below_eps_blocks_accept():
    out = sd.index(judge_gain=0.4, visible_anchor_gain=0.005,
                   holdout_gain=0.4, st=_rs())
    assert out["block_accept"] is True
    assert any("below_eps" in a for a in out["alerts"])


def test_above_eps_does_not_block_accept():
    """visible >= eps → block_accept=False。"""
    out = sd.index(judge_gain=0.1, visible_anchor_gain=0.05,
                   holdout_gain=0.05, st=_rs())
    assert out["block_accept"] is False


def test_block_accept_at_eps_boundary():
    """visible == eps 边界（不小于 eps）→ block_accept=False。"""
    out = sd.index(judge_gain=0.1, visible_anchor_gain=0.02,
                   holdout_gain=0.02, st=_rs())
    assert out["block_accept"] is False


# ---------------------------------------------------------------------------
# 闸③ force_review / force_human: visible 涨而 holdout 不涨
# ---------------------------------------------------------------------------

def test_visible_up_holdout_flat_alerts():
    out = sd.index(judge_gain=0.5, visible_anchor_gain=0.30,
                   holdout_gain=0.0, st=_rs())
    assert out["force_review"] is True
    assert any("holdout_divergence" in a for a in out["alerts"])


def test_judge_anchor_collusion_alert():
    # judge 增益远高于 frozen 锚真实增益 → |自欺指数|>band → 合谋报警
    out = sd.index(judge_gain=0.9, visible_anchor_gain=0.05,
                   holdout_gain=0.05, st=_rs())
    assert any("collusion" in a for a in out["alerts"])
    assert abs(out["value"]) > sd._ALERT_BAND


def test_force_review_requires_holdout_flat():
    """holdout > 0（健康）→ force_review=False，即使 visible 涨。"""
    out = sd.index(judge_gain=0.3, visible_anchor_gain=0.25,
                   holdout_gain=0.2, st=_rs())
    assert out["force_review"] is False


def test_force_human_equals_force_review():
    """force_human 是 force_review 的向后兼容别名，两者始终相等。"""
    # case A: overfit 触发
    out_a = sd.index(judge_gain=0.5, visible_anchor_gain=0.10,
                     holdout_gain=0.0, st=_rs())
    assert out_a["force_human"] == out_a["force_review"]

    # case B: 无 overfit
    out_b = sd.index(judge_gain=0.1, visible_anchor_gain=0.09,
                     holdout_gain=0.08, st=_rs())
    assert out_b["force_human"] == out_b["force_review"]


def test_holdout_none_skips_gate3():
    """holdout_gain=None（非抽检轮）→ 闸③跳过，不触发 force_review/force_human。"""
    out = sd.index(judge_gain=0.05, visible_anchor_gain=0.04,
                   holdout_gain=None, st=_rs())
    assert out["force_review"] is False
    assert out["force_human"] is False
    assert not any("holdout_divergence" in a for a in out["alerts"])
    assert "overfit_holdout" not in out["alerts"]


# ---------------------------------------------------------------------------
# 闸④ cumulative_drift: 累计漂移预算
# ---------------------------------------------------------------------------

def test_cumulative_drift_budget():
    # visible 累计涨 0.6，holdout 累计涨 0.3，容差 1.5× → 0.6 > 0.3*1.5=0.45 → 漂移
    assert sd.cumulative_drift(0.6, 0.3, tolerance=1.5) is True
    assert sd.cumulative_drift(0.4, 0.3, tolerance=1.5) is False


def test_cumulative_drift_exact_boundary():
    """visible == holdout * tolerance 边界（严格不超过）→ False。
    注意浮点: 0.3 * 1.5 = 0.44999... < 0.45，故用 0.44 作为不超过的保守值。
    """
    # 0.44 < 0.3 * 1.5 (≈0.44999...) → False
    assert sd.cumulative_drift(0.44, 0.3, tolerance=1.5) is False
    # 0.46 > 0.3 * 1.5 → True
    assert sd.cumulative_drift(0.46, 0.3, tolerance=1.5) is True


def test_cumulative_drift_default_tolerance():
    """默认容差 1.5×。"""
    # 0.7 > 0.4 * 1.5 = 0.6 → True
    assert sd.cumulative_drift(0.7, 0.4) is True
    # 0.5 > 0.4 * 1.5 = 0.6 → False
    assert sd.cumulative_drift(0.5, 0.4) is False


def test_cumulative_drift_zero_holdout():
    """holdout 为 0 时，任何正 visible 均超出（0 * tol = 0）→ True。"""
    assert sd.cumulative_drift(0.01, 0.0, tolerance=1.5) is True


def test_cumulative_drift_both_zero():
    """两者均为 0 → visible (0) > holdout*tol (0) → False。"""
    assert sd.cumulative_drift(0.0, 0.0, tolerance=1.5) is False


# ---------------------------------------------------------------------------
# index 返回结构完整性验证
# ---------------------------------------------------------------------------

def test_index_returns_all_required_keys():
    """index 返回 dict 必须包含所有 M3.4 规定键。"""
    out = sd.index(judge_gain=0.1, visible_anchor_gain=0.09,
                   holdout_gain=0.08, st=_rs())
    for key in ("value", "alerts", "block_accept", "force_review", "force_human"):
        assert key in out, f"missing key: {key}"


def test_index_value_is_judge_minus_visible():
    """value = judge_gain - visible_anchor_gain。"""
    out = sd.index(judge_gain=0.35, visible_anchor_gain=0.10,
                   holdout_gain=0.08, st=_rs())
    assert abs(out["value"] - 0.25) < 1e-9
