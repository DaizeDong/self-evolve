from tools.sie import selfdeception
from tools.sie.state import RunState


def _st():
    return RunState(run_id="r", phase="ACCEPT", round=3, parent_vid="v1", tier="B")


P = {"frozen_anchor_effective_gain_eps": 0.02, "selfdeception_alert_band": 0.15}


def test_overfit_holdout_divergence_forces_human():
    out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.08,
                              holdout_gain=0.0, st=_st(), params=P)
    assert out["force_human"] is True
    assert "overfit_holdout" in out["alerts"]


def test_low_anchor_gain_alert():
    out = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.005,
                              holdout_gain=0.005, st=_st(), params=P)
    assert "low_anchor_gain" in out["alerts"]


def test_judge_anchor_divergence_alert_on_high_value():
    out = selfdeception.index(judge_gain=0.40, visible_anchor_gain=0.05,
                              holdout_gain=0.05, st=_st(), params=P)
    assert out["value"] == 0.35
    assert "judge_anchor_divergence" in out["alerts"]


def test_clean_case_no_alert_no_force():
    out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.09,
                              holdout_gain=0.08, st=_st(), params=P)
    assert out["alerts"] == []
    assert out["force_human"] is False


def test_multiple_alerts_simultaneously():
    # visible_anchor_gain < eps (0.005 < 0.02) AND visible > 0 AND holdout <= 0
    # Also value = 0.5 - 0.005 = 0.495 > 0.15 -> judge_anchor_divergence
    out = selfdeception.index(judge_gain=0.5, visible_anchor_gain=0.005,
                              holdout_gain=0.0, st=_st(), params=P)
    assert "low_anchor_gain" in out["alerts"]
    assert "overfit_holdout" in out["alerts"]
    assert "judge_anchor_divergence" in out["alerts"]
    assert out["force_human"] is True


def test_negative_value_divergence():
    # visible_anchor_gain > judge_gain -> value is negative; |value| > band -> alert
    out = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.25,
                              holdout_gain=0.20, st=_st(), params=P)
    assert abs(out["value"] - (-0.20)) < 1e-9
    assert "judge_anchor_divergence" in out["alerts"]
    assert out["force_human"] is False


def test_holdout_exactly_zero_triggers_overfit():
    # holdout_gain == 0.0 with visible > 0 -> overfit_holdout
    out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.05,
                              holdout_gain=0.0, st=_st(), params=P)
    assert "overfit_holdout" in out["alerts"]
    assert out["force_human"] is True


def test_default_params_used_when_none():
    # Without params, defaults apply: eps=0.02, band=0.15
    out = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.005,
                              holdout_gain=0.1, st=_st(), params=None)
    assert "low_anchor_gain" in out["alerts"]


def test_drift_count_exposed_in_state():
    # drift_count is readable from RunState; this function reads it (no mutation)
    st = _st()
    st.drift_count = 5
    out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.09,
                              holdout_gain=0.08, st=st, params=P)
    assert out["alerts"] == []
    assert st.drift_count == 5  # function should NOT mutate drift_count


def test_holdout_none_skips_overfit_gate():
    """holdout_gain=None (非抽检轮) 时闸③ 跳过, 不触发 overfit_holdout / force_human."""
    st = _st()
    out = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.04,
                              holdout_gain=None, st=st, params=P)
    assert "overfit_holdout" not in out["alerts"], \
        f"holdout=None should skip gate③, got {out['alerts']}"
    assert out["force_human"] is False


def test_holdout_none_preserves_other_gates():
    """holdout_gain=None 不影响闸② (low_anchor_gain) 或闸④ (judge_anchor_divergence)."""
    st = _st()
    # visible < eps → 闸② 触发; judge 大幅超出 → 闸④ 触发; holdout=None → 闸③ 不触发
    out = selfdeception.index(judge_gain=0.5, visible_anchor_gain=0.005,
                              holdout_gain=None, st=st, params=P)
    assert "low_anchor_gain" in out["alerts"]
    assert "judge_anchor_divergence" in out["alerts"]
    assert "overfit_holdout" not in out["alerts"]
    assert out["force_human"] is False
