"""M1b.3: PACE A 档 e-process acceptor.

A 档: 每任务 task_passed 配对 (before, after) ∈ {0,1}² → betting martingale e-process.
no-regression 硬门覆盖优先; 无退化则跑 e-process 二态决策 (ACCEPT/REJECT).

签名锁定: decide() 接口不变 (M1a 兼容).
"""
from __future__ import annotations
from tools.sie.state import RunState

_PASS = 1.0  # A 档 score ∈ {0,1}; >= _PASS 视为 pass


# ---------------------------------------------------------------------------
# 内部: ONS-betting 鞅 (anytime-valid, confseq 缺失时回退)
# ---------------------------------------------------------------------------

def _ons_betting_wealth(diffs: list[float], alpha: float) -> tuple[float, list[float]]:
    """自洽 ONS-betting 鞅 (anytime-valid).

    将每对差 d 映射到 u = 0.5*(d+1) ∈ [0,1], null m=0.5.
    wealth = ∏ (1 + λ_t * (u_t - 0.5)), λ_t 由 ONS 步长自适应.

    Returns
    -------
    (evalue, path)
        evalue = max(path)  — 路径最大值 (等价于最优停时决策, Ville 不等式保证
                              P(evalue ≥ 1/α | H₀) ≤ α).
        path   = 每步 wealth 累积列表.
    """
    wealth = 1.0
    path: list[float] = []
    lam = 0.0
    A = 0.0   # ONS: 梯度平方累积
    b = 0.0   # ONS: 梯度累积

    # payoff ∈ [-0.5, 0.5]; 保证 factor = 1+λ·payoff > 0:
    # λ_safe = clip(λ, -(2-δ), 2-δ), δ=1e-6 → factor ≥ δ/2 = 5e-7 > 0 恒成立.
    # 不截断 factor 本身 (截断 factor 会破坏鞅恒等式并使梯度爆炸).
    _LAM_MAX = 2.0 - 1e-6

    for d in diffs:
        u = 0.5 * (d + 1.0)
        payoff = u - 0.5
        # 收紧 λ-clip 保证 factor > 0，去掉 factor 截断
        lam_safe = max(-_LAM_MAX, min(_LAM_MAX, lam))
        factor = 1.0 + lam_safe * payoff  # 恒 > 0 by λ-clip 设计
        wealth *= factor
        path.append(wealth)
        # ONS 梯度: d/dλ log(1 + λ·payoff) = payoff / (1 + λ·payoff)
        g = payoff / factor
        A += g * g
        b += g
        # ONS 更新: λ_{t+1} = clip(b / (A+1), -(2-δ), 2-δ)
        # 除数 +1 为正则项 (A=0 时避免初始大步)
        lam = max(-_LAM_MAX, min(_LAM_MAX, b / (A + 1.0)))

    evalue = max(path) if path else 1.0
    return evalue, path


# ---------------------------------------------------------------------------
# 内部: confseq 适配器 (优先使用; 失败时回退 ONS)
# ---------------------------------------------------------------------------

def _wealth_betting(diffs: list[float], alpha: float) -> tuple[float, list[float]]:
    """betting martingale e-process: confseq 优先, 缺失时回退 ONS-betting.

    Returns (evalue, path). evalue = max(path) (路径最大值).
    """
    try:
        import numpy as np
        from confseq.betting import betting_mart  # type: ignore
        u = np.array([0.5 * (d + 1.0) for d in diffs], dtype=float)
        mart = betting_mart(u, m=0.5, alpha=alpha)
        path = [float(v) for v in np.asarray(mart).ravel()]
        evalue = max(path) if path else 1.0
        return evalue, path
    except Exception:
        return _ons_betting_wealth(diffs, alpha)


def _pace_threshold(alpha: float) -> float:
    """PACE 采纳阈值 = 1/α (anytime-valid e-process 判停点)."""
    return 1.0 / alpha


# ---------------------------------------------------------------------------
# 内部: B/C 主观分缩放 (A 档不调用, M2/M3 接全)
# ---------------------------------------------------------------------------

def _scale_subjective(diffs: list[float], params: dict) -> list[float]:
    """B/C 主观分: 历史方差缩放 + 单轮 evalue_max_step 截断 (A 档跳过)."""
    import statistics
    cap = params.get("evalue_max_step", 4.0)
    if len(diffs) < 2:
        return diffs
    sd = statistics.pstdev(diffs) or 1.0
    return [max(-1.0, min(1.0, d / (sd * cap))) for d in diffs]


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def decide(paired: list[tuple[float, float]], tier: str,
           st: RunState, params: dict) -> dict:
    """PACE A 档 e-process 决策.

    流程 (A 档):
    1. 空配对 → REJECT (无证据)
    2. no-regression 硬门: 任一 pass→fail 回退 → 硬 REJECT
    3. e-process: 运行 betting martingale, evalue = max(path)
       - evalue ≥ 1/α → ACCEPT
       - evalue  < 1/α → REJECT (A 档二态, 禁 CONTINUE)

    Args:
        paired: 若干 (before_score, after_score) 配对, per-task.
        tier:   "A"|"B"|"C" 等 (叠加如"A+B"取主档).
        st:     RunState 当前运行状态.
        params: 参数字典; 支持 α/alpha/n_min/continue_count_cap 等键.

    Returns:
        {"decision": "ACCEPT"|"REJECT", "evalue": float, "reason": str}
    """
    alpha = params.get("α", params.get("alpha", 0.05))
    thr = _pace_threshold(alpha)
    base_tier = tier.split("+")[0]

    # 0. 空配对
    if not paired:
        return {"decision": "REJECT", "evalue": 0.0, "reason": "empty paired"}

    diffs = [after - before for (before, after) in paired]

    # 1. no-regression 硬门 (先查, 有退化立即 REJECT, 覆盖 e-process)
    regressed = [i for i, (b, a) in enumerate(paired) if b >= _PASS > a]
    if regressed:
        return {"decision": "REJECT", "evalue": 0.0,
                "reason": f"no-regression hard gate: {len(regressed)} task(s) regressed"}

    # 2. A 档 e-process (二态: ACCEPT/REJECT, 禁 CONTINUE)
    if base_tier == "A":
        evalue, _path = _wealth_betting(diffs, alpha)
        if evalue >= thr:
            return {"decision": "ACCEPT", "evalue": evalue,
                    "reason": f"e={evalue:.2f} >= 1/α={thr:.1f} (A 档二态)"}
        return {"decision": "REJECT", "evalue": evalue,
                "reason": f"e={evalue:.2f} < 1/α={thr:.1f} (A 档二态, 证据不足)"}

    # 3. B/C 档: 主观分缩放 + n_min 门 + CONTINUE 机制 (M2/M3 接全, 此处占位)
    n = len(paired)
    n_min = params.get("n_min", 8)
    if base_tier == "B" and n < n_min:
        return {"decision": "REJECT", "evalue": 0.0,
                "reason": f"n_anchor={n} < n_min={n_min} 禁 ACCEPT"}
    evalue, _path = _wealth_betting(_scale_subjective(diffs, params), alpha)
    if evalue >= thr:
        return {"decision": "ACCEPT", "evalue": evalue,
                "reason": f"e={evalue:.2f} >= 1/α (B/C 档)"}
    if 1.0 <= evalue < thr and st.continue_count < params.get("continue_count_cap", 5):
        return {"decision": "CONTINUE", "evalue": evalue,
                "reason": f"e={evalue:.2f} ∈ [1, 1/α) 继续取证"}
    return {"decision": "REJECT", "evalue": evalue,
            "reason": f"e={evalue:.2f} < 1/α (B/C 档, 证据不足)"}
