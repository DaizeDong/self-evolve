from __future__ import annotations
from tools.sie.backends import builtin


def propose(sandbox_root: str, reflections: list[dict],
            backend: str = "builtin") -> list[dict]:
    """backend 失败/超时/空 -> warning + fallback builtin(spec 态4)。"""
    props: list[dict] = []
    if backend == "builtin":
        props = builtin.generate(sandbox_root, reflections)
    else:
        # 其他 backend(gepa/openevolve) M3 接入; 此处 fallback
        props = builtin.generate(sandbox_root, reflections)
    return props
