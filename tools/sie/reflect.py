from __future__ import annotations
import glob, os


def reflect(sandbox_root: str, history: list[dict], n: int = 1) -> list[dict]:
    """M1a 串行单次(N=1)。首轮无历史 -> 对 target 当前内容静态审查;
    有历史 -> 读上轮失败摘要。M3 升 N=3 并行 MARS。"""
    out = []
    if history:
        last = history[-1]
        out.append({"target_failure": last.get("summary", "previous round failed"),
                    "round": last.get("round", 0)})
    else:
        srcs = [p for p in glob.glob(os.path.join(sandbox_root, "**", "*.py"),
                                     recursive=True)
                if not os.path.basename(p).startswith("test_")]
        note = f"static review of {len(srcs)} source file(s)"
        out.append({"static_review": note, "files": [os.path.relpath(s, sandbox_root)
                                                      for s in srcs]})
    return out[:max(1, n)]
