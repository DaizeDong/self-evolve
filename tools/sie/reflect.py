from __future__ import annotations
import glob, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor


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
    """Single independent MARS reflector: calls reflect-fanout.js subprocess.
    Reads history trace only (append-only, read-only — Iron Law 2).
    Never writes to trace, never reads other reflectors' drafts.
    `family` selects the agent family (claude|codex) → 异质 MARS（codex 可在反思阶段参与）。"""
    from .agents import invoke
    if not history:
        return {"reflector": idx, "findings": [], "family": family}
    prompt = ("You are an independent reflector. Treat run history as read-only evidence. "
              "Diagnose concrete failures and improvements; do not propose code. "
              'Return JSON {"findings":["finding"]}, at most five.\n' + json.dumps(history))
    result = invoke(prompt, family=family, tools="web_search")
    from .model_boundary import metadata
    out = {**metadata(result), "reflector": idx, "findings": [], "family": family}
    if not result["ok"]:
        return dict(out, error=result.get("error", "unavailable"))
    try:
        text = result["result"]
        parsed = json.loads(text[text.index("{"):text.rindex("}") + 1])
        findings = parsed.get("findings")
        if isinstance(findings, list):
            out["findings"] = [f for f in findings if isinstance(f, str) and f.strip()][:5]
    except (ValueError, AttributeError):
        out["error"] = "invalid reflection output"
    return out


def run_reflections_parallel(run_dir: str, history: list[dict],
                             n_reflectors: int = 3,
                             families: list[str] | None = None) -> list[dict]:
    """N independent MARS reflections in parallel — **跨家族异质反思**。
    Independence guarantee: each reflector gets its own snapshot of history;
    they are spawned concurrently and cannot read each other's intermediate output.
    Trace is passed read-only (never mutated here — Iron Law 2).

    families: 每个 reflector 用的 agent 家族, 循环复用。默认 ["claude","codex","claude"]
      → N=3 时得到 claude/codex/claude 的异质反思组合（codex 不再只限 C 档判官）。

    注意 n_reflectors=3 只是本函数的签名默认, **生产路径从不用它**: statemachine.py 传的是
    len(_fams), dual 开时 2、关时 1。文档一度按 3 来描述实际行为, 与真跑对不上。
    """
    if not families:
        families = ["claude", "codex", "claude"]
    fam_of = [families[i % len(families)] for i in range(n_reflectors)]
    with ThreadPoolExecutor(max_workers=n_reflectors) as ex:
        futs = [ex.submit(_reflect_one, run_dir, list(history), i, fam_of[i])
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
    failures = [dict(r) for r in reflections if r.get("error")]
    return {"merged_findings": merged, "n_reflectors": len(reflections),
            "failures": failures, "reflectors": reflections,
            "model_phase": ("unavailable" if failures and len(failures) == len(reflections)
                            else "degraded" if failures else "available") }
