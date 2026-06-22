from __future__ import annotations
import os


def generate(sandbox_root: str, reflections: list[dict]) -> list[dict]:
    """确定性最小修复器: 把反思里给出的 fix_content 落成 proposal。
    M1a 不实接 LLM(留 M3 fanout); 足以驱动端到端'采纳'路径验证。"""
    props = []
    for ref in reflections:
        fr = ref.get("file_rel")
        fc = ref.get("fix_content")
        if fr and fc:
            props.append({"file_rel": fr, "new_content": fc,
                          "fixes": ref.get("target_failure", "")})
    return props
