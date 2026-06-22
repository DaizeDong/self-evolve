from __future__ import annotations
import glob, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor


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


# ── M3.9: MARS parallel reflection fanout ────────────────────────────────────

def _reflect_one(run_dir: str, history: list[dict], idx: int) -> dict:
    """Single independent MARS reflector: calls reflect-fanout.js subprocess.
    Reads history trace only (append-only, read-only — Iron Law 2).
    Never writes to trace, never reads other reflectors' drafts."""
    proc = subprocess.run(
        ["node", "workflows/reflect-fanout.js", "--run", run_dir, "--idx", str(idx)],
        input=json.dumps({"history": history}),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"reflector": idx, "findings": []}
    return json.loads(proc.stdout)


def run_reflections_parallel(run_dir: str, history: list[dict],
                             n_reflectors: int = 3) -> list[dict]:
    """N independent MARS reflections in parallel.
    Independence guarantee: each reflector gets its own snapshot of history;
    they are spawned concurrently and cannot read each other's intermediate output.
    Trace is passed read-only (never mutated here — Iron Law 2)."""
    with ThreadPoolExecutor(max_workers=n_reflectors) as ex:
        futs = [ex.submit(_reflect_one, run_dir, list(history), i)
                for i in range(n_reflectors)]
        return [f.result() for f in futs]


def meta_aggregate(reflections: list[dict]) -> dict:
    """Aggregate N independent reflections: merge findings, deduplicate preserving order."""
    seen: set[str] = set()
    merged: list[str] = []
    for r in reflections:
        for f in r.get("findings", []):
            if f not in seen:
                seen.add(f)
                merged.append(f)
    return {"merged_findings": merged, "n_reflectors": len(reflections)}
