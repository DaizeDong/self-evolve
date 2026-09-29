from __future__ import annotations
import copy
import glob
import json
import os
from concurrent.futures import ThreadPoolExecutor

from tools.sie import agents, llm_adapter


def reflect(sandbox_root: str, history: list[dict], n: int = 1) -> list[dict]:
    """M1a 串行单次(N=1)。首轮无历史 -> 对 target 当前内容静态审查;
    有历史 -> 读上轮失败摘要。M3 升 N=3 并行 MARS。"""
    out = []
    if history:
        # Carry the WHOLE record, not just its summary. History entries grew fields that say what
        # actually happened (files_changed, evalue, decision, reason, the phase a barren round died
        # in) precisely because a column of the constant string "accepted" gave the reflectors
        # nothing to diagnose from. This branch kept reading only `summary`, so on the fallback path
        # every one of those new fields was dropped a line after being written. Producer changed,
        # consumer not, which is the same shape as the gate that could not see `merged_findings`.
        last = dict(history[-1])
        ref = {"target_failure": last.pop("summary", "previous round failed"),
               "round": last.pop("round", 0)}
        ref.update(last)              # files_changed / evalue / decision / reason / phase / passed
        out.append(ref)
    else:
        srcs = [p for p in glob.glob(os.path.join(sandbox_root, "**", "*.py"),
                                     recursive=True)
                if not os.path.basename(p).startswith("test_")]
        note = f"static review of {len(srcs)} source file(s)"
        out.append({"static_review": note, "files": [os.path.relpath(s, sandbox_root)
                                                      for s in srcs]})
    return out[:max(1, n)]


# ── M3.9: MARS parallel reflection fanout ────────────────────────────────────

def _reflect_one(run_dir: str, history: list[dict], idx: int,
                 family: str = "claude") -> dict:
    """Reflect on a private snapshot; failures remain distinct from an empty review."""
    prompt = (
        f"You are reflector #{idx}. Diagnose the supplied read-only run history. "
        "Identify concrete failures and directions to improve them; do not edit files. "
        'Return only JSON: {"findings":["concrete finding"]}.\n\nRUN HISTORY:\n'
        + json.dumps(llm_adapter.strip_truth(history), ensure_ascii=False)
    )
    result = agents.invoke(prompt, family=family, role="reflect")
    out = {**result, "reflector": idx, "findings": []}
    if not result["ok"]:
        return out
    parsed = llm_adapter.parse_object(result["result"])
    findings = parsed.get("findings") if parsed is not None else None
    if not isinstance(findings, list) or any(
            not isinstance(item, str) or not item.strip() for item in findings):
        out.update(ok=False, error="malformed reflection JSON: findings must be a list of nonempty strings")
        return out
    out["findings"] = findings
    return out


def run_reflections_parallel(run_dir: str, history: list[dict],
                             n_reflectors: int = 3,
                             families: list[str] | None = None) -> list[dict]:
    """Run private history snapshots in separate disposable agent directories.

    Requested families label calls; actual provider metadata determines diversity.
    """
    if n_reflectors <= 0:
        return []
    if not families:
        families = ["claude", "codex", "claude"]
    fam_of = [families[i % len(families)] for i in range(n_reflectors)]
    with ThreadPoolExecutor(max_workers=n_reflectors) as ex:
        futs = [ex.submit(_reflect_one, run_dir, copy.deepcopy(history), i, fam_of[i])
                for i in range(n_reflectors)]
        return [f.result() for f in futs]


def meta_aggregate(reflections: list[dict]) -> dict:
    """Merge findings in order and retain a snapshot of all backend outcomes."""
    seen: set[str] = set()
    merged: list[str] = []
    for r in reflections:
        for f in r.get("findings", []):
            if f not in seen:
                seen.add(f)
                merged.append(f)
    return {"merged_findings": merged, "n_reflectors": len(reflections),
            "backend_outcomes": copy.deepcopy(reflections)}
