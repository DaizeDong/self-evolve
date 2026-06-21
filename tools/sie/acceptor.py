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
# 内部: 同源锚去相关降权 (防相关锚虚高 e-value)
# ---------------------------------------------------------------------------

def _decorrelate_downweight(diffs: list[float], cluster_ids: list[str]) -> list[float]:
    """同源锚去相关降权: 同 cluster_id 的锚按簇大小 1/size 降权.

    独立锚(每个 cluster_id 唯一)不降权, 权重保持 1.
    相关锚(多个锚共享同一 cluster_id)按 1/size 等比降权,
    使同源锚集合的总贡献等价于一个独立锚, 防虚高 e-value.

    Args:
        diffs:       每锚的 (after - before) 差序列.
        cluster_ids: 每锚的来源 cluster 标识.

    Returns:
        降权后的差序列, 与 diffs 等长.
    """
    from collections import Counter
    sizes = Counter(cluster_ids)
    return [d / sizes[c] for d, c in zip(diffs, cluster_ids)]


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

    # 1. A 档 e-process (二态: ACCEPT/REJECT, 禁 CONTINUE)
    #    no-regression 硬门仅适用于 A 档: paired ∈ {0,1}² 二态, b>=1.0>a 表示 pass→fail 退化.
    #    B 档 paired 是边际增益浮点 ∈ [0,1], before_gain=1.0 合法(满分增益)不代表退化,
    #    因此硬门仅在 A 档内执行, 避免误判 B 档强增益锚为退化.
    if base_tier == "A":
        # no-regression 硬门 (A 档专属: 任一 pass→fail → 硬 REJECT, 覆盖 e-process)
        regressed = [i for i, (b, a) in enumerate(paired) if b >= _PASS > a]
        if regressed:
            return {"decision": "REJECT", "evalue": 0.0,
                    "reason": f"no-regression hard gate: {len(regressed)} task(s) regressed"}
        evalue, _path = _wealth_betting(diffs, alpha)
        if evalue >= thr:
            return {"decision": "ACCEPT", "evalue": evalue,
                    "reason": f"e={evalue:.2f} >= 1/α={thr:.1f} (A 档二态)"}
        return {"decision": "REJECT", "evalue": evalue,
                "reason": f"e={evalue:.2f} < 1/α={thr:.1f} (A 档二态, 证据不足)"}

    # 3. B 档: per-anchor 边际增益配对 + 三道硬门 + CONTINUE 机制
    if base_tier == "B":
        from . import anchors as _anchors
        n_min = int(params.get("n_min", 8))
        eff_min = int(params.get("effective_independent_anchor_min", 12))
        n_anchor = len(paired)
        visible_verified = [a for a in params.get("anchors", []) if a.get("verified")]
        eff = _anchors.effective_independent_count(visible_verified)
        base = {"effective_independent": eff, "n_anchor": n_anchor}

        # 门1: 锚数下限 (n_anchor < n_min → 禁 ACCEPT)
        if n_anchor < n_min:
            return {"decision": "REJECT", "evalue": 0.0,
                    "reason": f"n_anchor {n_anchor} < n_min {n_min}", **base}

        # 门2: 有效独立锚下限 (小相关锚集 → 禁 B 档单独 ACCEPT)
        if eff < eff_min:
            return {"decision": "REJECT", "evalue": 0.0,
                    "reason": f"effective_independent {eff} < min {eff_min}", **base}

        # e-process: per-anchor 边际增益配对 (客观增益, 不走 _scale_subjective)
        # diffs = (after_gain - before_gain) per anchor; H₀: diff=0 (无改进)
        # ONS betting 鞅: u=0.5*(d+1) ∈ [0,1], null m=0.5, 即 d=0 为零假设中心
        # 可选: 若 params 提供 cluster_ids, 先去相关降权
        cluster_ids = params.get("cluster_ids")
        b_diffs = diffs  # per-anchor (after_gain - before_gain)
        if cluster_ids and len(cluster_ids) == len(b_diffs):
            b_diffs = _decorrelate_downweight(b_diffs, cluster_ids)

        # 输入钳: B diffs 天然 ∈ [-1,1], 此截断对正常增益无效 (仅防异常超范围输入).
        b_diffs = [max(-1.0, min(1.0, d)) for d in b_diffs]

        evalue, _path = _wealth_betting(b_diffs, alpha)

        # 门3: evalue_max_step 总量钳 (防累积 e-value 爆表)
        # 将路径最大值钳到 step_cap, 保证单次 decide() 调用最多贡献 step_cap 的 e-value.
        # 默认 1e6 (实际无限制), 仅在显式设置较低值时生效.
        # 注: 旧 per-diff payoff_cap 方案 (payoff_cap=min(0.5,(step_cap-1)/2) 恒=0.5,
        #     diff_cap=1.0) 对正常 [-1,1] 完全无截断, step_cap 参数实际失效.
        #     此处改为总量钳, step_cap 参数真正生效.
        step_cap = float(params.get("evalue_max_step", 1e6))
        evalue = min(evalue, step_cap)

        if evalue >= thr:
            return {"decision": "ACCEPT", "evalue": evalue,
                    "reason": f"B e-value {evalue:.2f} >= 1/alpha={thr:.1f}", **base}
        if 1.0 < evalue < thr:
            # B 是随机档, 允许 CONTINUE 累积证据
            if st.continue_count < int(params.get("continue_count_cap", 5)):
                return {"decision": "CONTINUE", "evalue": evalue,
                        "reason": f"B accumulating evidence e={evalue:.2f}", **base}
        return {"decision": "REJECT", "evalue": evalue,
                "reason": f"B e-value {evalue:.2f} below threshold", **base}

    # 4. C 档及其他: 主观分缩放 + CONTINUE 机制 (M3 接全, 此处保留占位)
    evalue, _path = _wealth_betting(_scale_subjective(diffs, params), alpha)
    if evalue >= thr:
        return {"decision": "ACCEPT", "evalue": evalue,
                "reason": f"e={evalue:.2f} >= 1/α (C 档)"}
    if 1.0 <= evalue < thr and st.continue_count < params.get("continue_count_cap", 5):
        return {"decision": "CONTINUE", "evalue": evalue,
                "reason": f"e={evalue:.2f} ∈ [1, 1/α) 继续取证"}
    return {"decision": "REJECT", "evalue": evalue,
            "reason": f"e={evalue:.2f} < 1/α (C 档, 证据不足)"}
