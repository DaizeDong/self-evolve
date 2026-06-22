from __future__ import annotations
from tools.sie.backends import builtin


def propose(sandbox_root: str, reflections: list[dict],
            backend: str = "builtin") -> list[dict]:
    """生成提议。backend:
      - "builtin":      确定性最小修复器（默认；测试/无 LLM 时用）。
      - "llm":          真 Claude code proposer（cc 优先, claude fallback）；失败/空 → fallback builtin。
      - "llm-artifact": 真 Claude artifact proposer（改 B 档研究产物 JSON，非 .py）；
                        失败/空 → 不回退 builtin（builtin 只改代码，对 B 档产物无意义）→ 返回 []。
    backend 失败/超时/空 → fallback builtin（spec 态4；llm-artifact 例外，见上）。
    """
    if backend == "llm":
        from tools.sie.backends import llm  # 惰性 import: builtin 路径不依赖 llm/node
        props = llm.generate(sandbox_root, reflections)
        if props:
            return props
        # llm 空 → 回退确定性 builtin（不让一次 LLM 失败阻断闭环）
        return builtin.generate(sandbox_root, reflections)
    if backend == "llm-artifact":
        from tools.sie.backends import llm  # 惰性 import
        # B 档产物提议: 失败/空直接返回 []（builtin 改代码对产物无意义, 不回退）。
        # run_loop 态4 见空 → note_static_reject + LOOP（与契约一致）。
        return llm.generate_artifact(sandbox_root, reflections)
    return builtin.generate(sandbox_root, reflections)
