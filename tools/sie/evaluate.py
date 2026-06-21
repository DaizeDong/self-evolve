"""M1a: evaluate.py — 只走 verifiable(A 档)。B/C 档 evaluate 在 M2/M3 接入。

Public API:
  evaluate(sandbox_root, tier, base_result=None) -> dict
    Returns {"result": <A-grade contract>, "paired": [(before, after), ...], "coverage": float}
    paired 给 acceptor: before=parent grade score, after=current sandbox grade score.
    缺省 base_result=None 时视为全 fail 基线，before=0.0。
"""
from __future__ import annotations
from tools.sie.verifiable import grade_pytest


def evaluate(sandbox_root: str, tier: str,
             base_result: dict | None = None) -> dict:
    """M1a 只走 verifiable(A 档)。B/C 档 evaluate 在 M2/M3 接入。

    Args:
        sandbox_root: 沙箱根目录路径。
        tier: 档位，M1a 只用 "A"。
        base_result: parent 版本的 grade 结果(A 档 contract dict)。
                     None 时视为全 fail 基线，before_score=0.0。

    Returns:
        {
          "result": <A-grade contract from grade_pytest>,
          "paired": [(before_score, after_score)],  # acceptor 判回退: after < before -> REJECT
          "coverage": float  # verifiable_coverage from grade_pytest
        }
    """
    after = grade_pytest(sandbox_root)
    after_score = after["dimensions"][0]["score"] if after["dimensions"] else 0.0

    if base_result and base_result.get("dimensions"):
        before_score = base_result["dimensions"][0]["score"]
    else:
        before_score = 0.0  # 冷启动: 视 parent 为全 fail 基线

    paired = [(float(before_score), float(after_score))]
    return {
        "result": after,
        "paired": paired,
        "coverage": after.get("verifiable_coverage", 0.0),
    }
