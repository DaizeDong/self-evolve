"""自欺指数多闸: judge 增益 vs frozen 锚真实增益 + holdout 背离 + 累计漂移 (IMMUTABLE)。

假设（调用方保证）:
  - visible_anchor_gain 已只含 frozen 留存锚的真实增益，不含当轮新增锚——
    由 anchors/evaluate 在传入前过滤，本函数不再重复过滤（闸①由上游保证）。

漂移信号回传:
  - 本函数不直接修改 RunState.drift_count；当 |value| > band 时，
    返回 dict 含 "judge_anchor_divergence" alert，statemachine 读到后
    负责执行 st.drift_count += 1。这样保持单向数据流，避免副作用。

M3.4 演进（向后兼容）:
  - 新增函数: retained_visible_gain, cumulative_drift
  - index() 新增返回键: block_accept, force_review
  - force_human 保留（向后兼容别名，语义不变：overfit_holdout 时 True）
  - 每个闸追加双 alert 字符串（旧名保持，新名含 M3.4 关键字供子串检测）
"""
from __future__ import annotations

from .state import RunState

_EPS = 0.02              # frozen_anchor_effective_gain_ε
_ALERT_BAND = 0.15       # selfdeception_alert_band
_DRIFT_CIRCUIT = 4       # N_drift


# ---------------------------------------------------------------------------
# 闸①辅助: retained_visible_gain —— 只计留存锚增益，新增锚不计当轮
# ---------------------------------------------------------------------------

def retained_visible_gain(prev_anchors: list[dict], cur_anchors: list[dict]) -> float:
    """计算 frozen visible 留存锚（span 在前后两轮均出现）的平均增益变化。

    新增锚（span 仅在 cur 出现）不计入当轮增益（闸①）。
    若无留存锚，返回 0.0。

    Args:
        prev_anchors: 上轮锚列表，每项含 "span" 和 "marginal_gain"。
        cur_anchors:  本轮锚列表，每项含 "span" 和 "marginal_gain"。

    Returns:
        留存锚的平均 (cur_gain - prev_gain)；新锚不计入分子/分母。
    """
    prev = {a["span"]: float(a.get("marginal_gain", 0.0))
            for a in prev_anchors if a.get("span")}
    cur = {a["span"]: float(a.get("marginal_gain", 0.0))
           for a in cur_anchors if a.get("span")}
    retained = set(prev) & set(cur)
    if not retained:
        return 0.0
    return sum(cur[s] - prev[s] for s in retained) / len(retained)


# ---------------------------------------------------------------------------
# 闸④辅助: cumulative_drift —— 累计漂移预算检测
# ---------------------------------------------------------------------------

def cumulative_drift(lineage_visible_cum: float, lineage_holdout_cum: float,
                     tolerance: float = 1.5) -> bool:
    """检测同 lineage 上 visible 累计涨幅是否超过 holdout 累计涨幅×容差。

    Args:
        lineage_visible_cum:  lineage 上 visible 锚累计涨幅。
        lineage_holdout_cum:  lineage 上 holdout 锚累计涨幅。
        tolerance:            容差倍数，默认 1.5×。

    Returns:
        True 表示 visible 累计涨幅 > holdout 累计涨幅×容差（过拟合漂移）。
    """
    return lineage_visible_cum > lineage_holdout_cum * tolerance


# ---------------------------------------------------------------------------
# 主函数: index —— 多闸检测，返回自欺指数与各闸信号
# ---------------------------------------------------------------------------

def index(
    judge_gain: float,
    visible_anchor_gain: float,
    holdout_gain: float | None,
    st: RunState,
    params: dict | None = None,
) -> dict:
    """计算自欺指数并触发多闸检测。

    Args:
        judge_gain: 当轮 judge 打分增益（propose 后 vs propose 前）。
        visible_anchor_gain: frozen 留存锚的真实可见增益（上游过滤新锚后传入）。
        holdout_gain: holdout 锚集的真实增益（用于过拟合背离检测）。
                      None 表示本轮无 holdout 数据（非抽检轮），跳过闸③。
        st: 当前 RunState，本函数只读 drift_count，不写入。
        params: 覆盖默认超参，支持键：
            frozen_anchor_effective_gain_eps (float, 默认 0.02)
            selfdeception_alert_band (float, 默认 0.15)

    Returns:
        {
            "value": float,        # judge_gain - visible_anchor_gain
            "alerts": list[str],   # 触发的闸名（可多个，含旧名与新名双串）
            "block_accept": bool,  # True 当且仅当 visible_anchor_gain < eps（闸②）
            "force_review": bool,  # True 当且仅当 overfit_holdout 触发（闸③，主信号）
            "force_human": bool,   # 向后兼容别名，= force_review（overfit_holdout）
        }

    闸规则:
        ② visible_anchor_gain < eps
               → alert "low_anchor_gain" + "below_eps:..."
               → block_accept=True
          （禁 ACCEPT 由 statemachine 执行，本函数也通过 block_accept 直接报告）
        ③ visible_anchor_gain > 0 且 holdout_gain <= 0
               → alert "overfit_holdout" + "holdout_divergence:..."
               → force_review=True, force_human=True（主信号）
           holdout_gain=None 时跳过本闸（视为"本轮无 holdout 数据"）。
        ④ |value| > band
               → alert "judge_anchor_divergence" + "collusion:..."
           （statemachine 读到此 alert 后应执行 drift_count += 1）
    """
    p = params or {}
    eps = float(p.get("frozen_anchor_effective_gain_eps", _EPS))
    band = float(p.get("selfdeception_alert_band", _ALERT_BAND))

    value = float(judge_gain) - float(visible_anchor_gain)
    alerts: list[str] = []
    force_human = False
    block_accept = False
    force_review = False

    # 闸②: frozen 留存锚增益过低 → 统计基础不可靠，禁 ACCEPT
    if visible_anchor_gain < eps:
        block_accept = True
        # 旧名（M2.7 兼容）+ 新名（M3.4 子串检测）
        # 注意: 每闸追加旧名+新名两条 alert(向后兼容); 下游统计触发数勿用 len(alerts), drift 累计须用专门信号(judge_anchor_divergence 检测)+=1
        alerts.append("low_anchor_gain")
        alerts.append(f"below_eps:visible_gain={visible_anchor_gain:.3f}<{eps}")

    # 闸③(主信号)：visible 涨而 holdout 不涨 = 过拟合背离 → 强制人审
    # holdout_gain=None 时跳过（非抽检轮，本轮无 holdout 数据，不报 overfit）
    if holdout_gain is not None and visible_anchor_gain > 0.0 and holdout_gain <= 0.0:
        force_human = True
        force_review = True
        # 旧名（M2.7 兼容）+ 新名（M3.4 子串检测）
        # 注意: 每闸追加旧名+新名两条 alert(向后兼容); 下游统计触发数勿用 len(alerts), drift 累计须用专门信号(judge_anchor_divergence 检测)+=1
        alerts.append("overfit_holdout")
        alerts.append(
            f"holdout_divergence:visible={visible_anchor_gain:.3f},"
            f"holdout={holdout_gain:.3f}")

    # 闸④: judge 增益显著超出锚真实增益 = 疑似 judge/proposal 合谋
    if abs(value) > band:
        # 旧名（M2.7 兼容）+ 新名（M3.4 子串检测）
        # 注意: 每闸追加旧名+新名两条 alert(向后兼容); 下游统计触发数勿用 len(alerts), drift 累计须用专门信号(judge_anchor_divergence 检测)+=1
        alerts.append("judge_anchor_divergence")
        alerts.append(f"collusion:selfdeception_index_abs={abs(value):.3f}>{band}")

    # 读取 drift_count 仅供日志/诊断（不写入，statemachine 负责累计）
    _ = st.drift_count

    return {
        "value": round(value, 12),
        "alerts": alerts,
        "block_accept": block_accept,
        "force_review": force_review,
        "force_human": force_human,
    }
