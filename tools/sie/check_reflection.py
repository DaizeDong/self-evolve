from __future__ import annotations


def check(reflection: dict, threshold: float = 0.5) -> bool:
    """M1a 弱校验(spec 态3 M1): 非空且含有意义字段即过。M3 升 BenchTrace。"""
    if not reflection:
        return False
    keys = ("target_failure", "static_review", "fix_content", "files")
    return any(reflection.get(k) for k in keys)
