"""Shared llmcall agents and cross-checks with actual-provider evidence."""
from __future__ import annotations

import importlib

from tools.sie import llm_adapter

VALID_FAMILIES = ("claude", "cc", "codex", "codexg")


def codex_available(timeout_s: int = 20) -> bool:
    """Compatibility capability probe; this does not establish live provider availability."""
    try:
        return callable(getattr(importlib.import_module("llmcall"), "call", None))
    except Exception:
        return False


def preflight_dual(dual_requested: bool) -> tuple[bool, str | None]:
    if not dual_requested:
        return False, None
    if codex_available():
        return True, None
    return False, "llmcall unavailable; dual checks disabled (降级). Actual independence remains unverified."


def invoke(prompt: str, family: str = "claude", *, model: str | None = None,
           tools: str | None = None, effort: str | None = None,
           role: str | None = None, timeout_s: int = 600,
           avoid: str | None = None) -> dict:
    """Invoke an agent; legacy routing arguments are informational compatibility inputs."""
    if family not in VALID_FAMILIES:
        return llm_adapter.failure("unknown requested family", requested_family=family)
    return {**llm_adapter.invoke_agent(prompt, avoid=avoid), "requested_family": family}


def _extract_json(text: str):
    return llm_adapter.parse_object(text)


def _cross_check(prompt, families, invoke_one):
    per = {}
    previous = None
    for alias in families:
        result = invoke_one(alias, previous)
        per[alias] = result
        if result["ok"]:
            previous = result.get("provider")
    successful = [result for result in per.values() if result["ok"]]
    heterogeneous = llm_adapter.independent(successful)
    return {"per": per, "n_ok": len(successful),
            "results_ok": [result["result"] for result in successful],
            "heterogeneous": heterogeneous,
            "status": "independent" if heterogeneous else "insufficient_independence"}


def cross_check(prompt: str, families=("claude", "codex"), *,
                tools: str | None = None, timeout_s: int = 600) -> dict:
    return _cross_check(prompt, families, lambda alias, previous: invoke(
        prompt, family=alias, tools=tools, timeout_s=timeout_s, avoid=previous))


def cross_check_verdicts(prompt: str, families=("claude", "codex"),
                         timeout_s: int = 600) -> dict:
    """Review is a judge operation. Aliases alone never establish independent agreement."""
    cc = _cross_check(prompt, families, lambda alias, previous: {
        **llm_adapter.invoke_judge(prompt, avoid=previous), "requested_family": alias})
    verdicts = {}
    valid_results = []
    for alias, result in cc["per"].items():
        obj = _extract_json(result["result"]) if result["ok"] else None
        verdict = obj.get("verdict") if obj else None
        verdicts[alias] = verdict if verdict in ("accept", "reject", "abstain") else None
        if verdicts[alias] is not None:
            valid_results.append(result)
        elif result["ok"]:
            result.update(ok=False, error="malformed verdict JSON")
    sufficient = llm_adapter.independent(valid_results)
    got = [verdict for verdict in verdicts.values() if verdict is not None]
    return {"verdicts": verdicts, "agree": len(set(got)) == 1 if sufficient else None,
            "n_ok": len(valid_results), "raw": cc,
            "status": "independent" if sufficient else "insufficient_independence"}
