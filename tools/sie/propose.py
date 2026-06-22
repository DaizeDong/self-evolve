from __future__ import annotations
from tools.sie.backends import builtin


def propose(sandbox_root: str, reflections: list[dict],
            backend: str = "builtin") -> list[dict]:
    """生成提议。backend:
      - "builtin": 确定性最小修复器（默认；测试/无 LLM 时用）。
      - "llm":     真 Claude proposer（cc 优先, claude fallback）；失败/空 → fallback builtin。
    backend 失败/超时/空 → fallback builtin（spec 态4）。
    """
    if backend == "llm":
        from tools.sie.backends import llm  # 惰性 import: builtin 路径不依赖 llm/node
        props = llm.generate(sandbox_root, reflections)
        if props:
            return props
        # llm 空 → 回退确定性 builtin（不让一次 LLM 失败阻断闭环）
        return builtin.generate(sandbox_root, reflections)
    return builtin.generate(sandbox_root, reflections)
