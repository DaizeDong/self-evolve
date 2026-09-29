"""Use current llmcall policy and validate its terminal results at one boundary."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import importlib
import json
from pathlib import Path
import subprocess
import sys


_FAMILIES = {"cc": "claude", "claude": "claude", "codex": "codex", "codexg": "codex"}
_NONTERMINAL = {"pending", "running", "queued", "in_progress", "in-progress",
                "submitted", "started", "processing"}
_FAILED = {"failed", "error", "cancelled", "canceled"}
POLICY_FIELDS = ("group", "groups_refused", "crossed")
_TERMINAL_FIELDS = ("status", "state", "terminal", "is_terminal", "done", "completed")


def actual_family(provider) -> str | None:
    return _FAMILIES.get(provider.strip().lower()) if isinstance(provider, str) else None


def failure(error: str, **metadata) -> dict:
    return {"ok": False, "result": "", "provider": None, "family": None,
            "attempts": [], **metadata, "error": error}


def normalize_result(value, *, serialized: bool = False) -> dict:
    """Validate actual Result fields, preserving explicit terminal-state extensions."""
    if serialized:
        if not isinstance(value, dict):
            return failure("malformed llmcall transport result")
        fields = value
    else:
        if value is None or isinstance(value, (dict, str, bytes)):
            return failure("malformed llmcall Result object")
        fields = {name: getattr(value, name) for name in
                  ("text", "provider", "error", "attempts", *_TERMINAL_FIELDS,
                   *POLICY_FIELDS) if hasattr(value, name)}
    provider = fields.get("provider")
    attempts = fields.get("attempts", [])
    if isinstance(attempts, list):
        attempts = [asdict(a) if is_dataclass(a) and not isinstance(a, type)
                    else dict(vars(a)) if hasattr(a, "__dict__") else a for a in attempts]
    metadata = {"provider": provider if isinstance(provider, str) else None,
                "family": actual_family(provider), "attempts": attempts}
    for key in (*_TERMINAL_FIELDS, *POLICY_FIELDS):
        if key in fields:
            metadata[key] = fields[key]
    if not all(key in fields for key in ("text", "provider", "error", "attempts")):
        return failure("malformed llmcall Result: missing required fields", **metadata)
    if not isinstance(attempts, list) or any(not isinstance(a, dict) for a in attempts):
        return failure("malformed llmcall attempts", **metadata)
    for key in ("status", "state"):
        state = fields.get(key)
        if isinstance(state, str) and state.lower() in _NONTERMINAL | _FAILED:
            return failure("llmcall returned non-success state: " + state, **metadata)
    if any(fields.get(key) is False for key in ("terminal", "is_terminal", "done", "completed")):
        return failure("llmcall returned a nonterminal result", **metadata)
    if fields.get("error"):
        return failure(str(fields["error"]), **metadata)
    if not isinstance(provider, str) or not provider.strip():
        return failure("llmcall returned no actual provider", **metadata)
    if not isinstance(fields["text"], str) or not fields["text"].strip():
        return failure("llmcall returned empty or invalid text", **metadata)
    return {"ok": True, "result": fields["text"], **metadata, "error": None}


def invoke_judge(prompt: str, *, avoid: str | None = None) -> dict:
    """Default llmcall mode is the read-only judge mode; preserve its defaults."""
    if not isinstance(prompt, str) or not prompt.strip():
        return failure("empty judge prompt")
    try:
        module = importlib.import_module("llmcall")
        kwargs = {"avoid": avoid} if avoid else {}
        return normalize_result(module.call(prompt, **kwargs))
    except Exception as exc:
        return failure(f"llmcall unavailable: {type(exc).__name__}: {exc}")


def invoke_agent(prompt: str, *, avoid: str | None = None) -> dict:
    """Run an agent in a disposable private cwd without changing the parent cwd."""
    if not isinstance(prompt, str) or not prompt.strip():
        return failure("empty agent prompt")
    from tools.sie import runtime_data

    helper = Path(__file__).resolve().with_name("llm_agent_child.py")
    try:
        with runtime_data.agent_scratch() as scratch:
            proc = subprocess.run(
                [sys.executable, "-B", str(helper)],
                input=json.dumps({"prompt": prompt, "avoid": avoid}),
                cwd=str(scratch), shell=False, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                return failure(f"llmcall child exited {proc.returncode}: {(proc.stderr or '').strip()}")
            result = normalize_result(json.loads(proc.stdout), serialized=True)
            if proc.stderr:
                result["diagnostic"] = proc.stderr.strip()
            return result
    except Exception as exc:
        return failure(f"llmcall agent unavailable: {type(exc).__name__}: {exc}")


def independent(results) -> bool:
    """Only successful results with known distinct actual providers establish independence."""
    families = set()
    for result in results:
        if not (result.get("ok") or result.get("available")):
            continue
        metadata = result.get("backend") or result.get("metadata") or result
        family = actual_family(metadata.get("provider"))
        if family:
            families.add(family)
    return len(families) >= 2


def parse_object(text: str) -> dict | None:
    """Accept an object or a fenced object; never recover malformed JSON as success."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


_TRUTH_KEYS = {"expected", "verified", "observed", "verify_reason", "fetched_at",
               "marginal_gain", "anchor_id", "ground_truth", "truth", "tolerance"}


def strip_truth(value, *, judge: bool = False):
    excluded = _TRUTH_KEYS | ({"claim", "source_url"} if judge else set())
    if isinstance(value, dict):
        return {key: strip_truth(item, judge=judge) for key, item in value.items()
                if str(key).lower() not in excluded}
    if isinstance(value, list):
        return [strip_truth(item, judge=judge) for item in value]
    return value
