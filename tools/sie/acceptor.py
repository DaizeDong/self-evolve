"""M1a: no-regression 硬门兜底。
签名锁定; M1b 把内部替换为 PACE per-tier e-process(站 confseq), decide() 签名不变。"""
from __future__ import annotations
from tools.sie.state import RunState

_PASS = 1.0  # A 档 score∈{0,1}; >=_PASS 视为 pass


def decide(paired: list[tuple[float, float]], tier: str,
           st: RunState, params: dict) -> dict:
    """决策：任一任务从 pass(>=1) 退化到 fail(<1) → 硬 REJECT。否则 ACCEPT。

    Args:
        paired: 若干 (old_score, new_score) 配对，per-task。
        tier: "A"|"B"|"C" 等档位 (M1a 兜底不分支)。
        st: RunState 当前运行状态。
        params: 参数字典 (M1a 未用, M1b PACE 可用)。

    Returns:
        {"decision":"ACCEPT"|"REJECT", "evalue":float, "reason":str}
    """
    if not paired:
        return {"decision": "REJECT", "evalue": 0.0, "reason": "no paired evidence"}

    regressed = [i for i, (b, a) in enumerate(paired) if b >= _PASS > a]
    improved = [i for i, (b, a) in enumerate(paired) if a > b]

    if regressed:
        return {"decision": "REJECT", "evalue": 0.0,
                "reason": f"no-regression hard gate: {len(regressed)} task(s) regressed"}

    # 无退化 -> ACCEPT(M1a 兜底); A 档天然二态, 不产 CONTINUE
    ev = (len(improved) + 1) / (len(paired) + 1)  # 占位 evalue(M1b 换 e-value)
    return {"decision": "ACCEPT", "evalue": float(ev),
            "reason": f"no regression; {len(improved)} improved"}
