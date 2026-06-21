"""自欺指数多闸: judge 增益 vs frozen 锚真实增益 + holdout 背离 + 累计漂移 (IMMUTABLE)。

假设（调用方保证）:
  - visible_anchor_gain 已只含 frozen 留存锚的真实增益，不含当轮新增锚——
    由 anchors/evaluate 在传入前过滤，本函数不再重复过滤（闸①由上游保证）。

漂移信号回传:
  - 本函数不直接修改 RunState.drift_count；当 |value| > band 时，
    返回 dict 含 "judge_anchor_divergence" alert，statemachine 读到后
    负责执行 st.drift_count += 1。这样保持单向数据流，避免副作用。
"""
from __future__ import annotations

from .state import RunState


def index(
    judge_gain: float,
    visible_anchor_gain: float,
    holdout_gain: float,
    st: RunState,
    params: dict | None = None,
) -> dict:
    """计算自欺指数并触发多闸检测。

    Args:
        judge_gain: 当轮 judge 打分增益（propose 后 vs propose 前）。
        visible_anchor_gain: frozen 留存锚的真实可见增益（上游过滤新锚后传入）。
        holdout_gain: holdout 锚集的真实增益（用于过拟合背离检测）。
        st: 当前 RunState，本函数只读 drift_count，不写入。
        params: 覆盖默认超参，支持键：
            frozen_anchor_effective_gain_eps (float, 默认 0.02)
            selfdeception_alert_band (float, 默认 0.15)

    Returns:
        {
            "value": float,       # judge_gain - visible_anchor_gain
            "alerts": list[str],  # 触发的闸名（可多个）
            "force_human": bool,  # True 当且仅当 overfit_holdout 触发
        }

    闸规则:
        ② visible_anchor_gain < eps  → alert "low_anchor_gain"
           （禁 ACCEPT 由 statemachine 执行，本函数只报告）
        ③ visible_anchor_gain > 0 且 holdout_gain <= 0
                                     → alert "overfit_holdout" + force_human=True
        ④ |value| > band             → alert "judge_anchor_divergence"
           （statemachine 读到此 alert 后应执行 drift_count += 1）
    """
    p = params or {}
    eps = float(p.get("frozen_anchor_effective_gain_eps", 0.02))
    band = float(p.get("selfdeception_alert_band", 0.15))

    value = float(judge_gain) - float(visible_anchor_gain)
    alerts: list[str] = []
    force_human = False

    # 闸②: frozen 留存锚增益过低 → 统计基础不可靠
    if visible_anchor_gain < eps:
        alerts.append("low_anchor_gain")

    # 闸③: visible 涨而 holdout 不涨 = 过拟合背离 → 强制人审
    if visible_anchor_gain > 0.0 and holdout_gain <= 0.0:
        alerts.append("overfit_holdout")
        force_human = True

    # 闸④: judge 增益显著超出锚真实增益 = 疑似 judge/proposal 合谋
    if abs(value) > band:
        alerts.append("judge_anchor_divergence")

    # 读取 drift_count 仅供日志/诊断（不写入，statemachine 负责累计）
    _ = st.drift_count

    return {"value": round(value, 12), "alerts": alerts, "force_human": force_human}
