"""Judge orchestration: prompt construction + span scoring + family routing.

Exports:
  build_judge_prompt(artifact_text, spans) -> str
      Iron rule 5: prompt carries ONLY span text — never claim/verified/
      marginal_gain/expected values.  Tested by test_prompt_carries_no_truth.

  score(artifact_path, anchors_visible, family) -> dict
      Routes to judge_codex or judge_claude; aggregates span_scores;
      degrades gracefully when judge is unavailable.

Return schema:
  {
    "family": str,
    "available": bool,
    "span_scores": [{"span": str, "score": float}, ...],
    "aggregate": float,       # mean over returned span_scores (0.0 if none)
    "unspanned_penalized": int,  # #spans not scored by judge (no padding)
  }
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.sie import judge_codex, judge_claude


def build_judge_prompt(artifact_text: str, spans: list[str]) -> str:
    """Build the judge prompt.

    Iron rule 5 (immutable): prompt MUST NOT carry any ground-truth fields —
    specifically: claim, verified, marginal_gain, expected, source_url, or
    any numeric tolerance value.  Only the span text strings themselves are
    included.  Tested by test_prompt_carries_no_truth.
    """
    span_block = "\n".join(f"- {s}" for s in spans)
    return (
        "You are an impartial judge. Score ONLY the assertions tied to the "
        "verifiable spans below. Assertions with NO verifiable span get zero or "
        "negative weight. Do not reward length. Return JSON: "
        '{"span_scores":[{"span":..., "score":0..1}]}.\n\n'
        f"ARTIFACT:\n{artifact_text}\n\nSPANS TO JUDGE:\n{span_block}\n"
    )


def _parse_span_scores(raw: str, spans: list[str]) -> dict:
    """Extract span_scores from judge raw output; degrade gracefully on parse error.

    If raw is not parseable JSON or lacks span_scores, returns empty list with
    aggregate=0.0 and unspanned_penalized=len(spans).  No exception is raised.
    """
    try:
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        ss = obj.get("span_scores", [])
    except (ValueError, json.JSONDecodeError):
        ss = []
    valid = [x for x in ss if isinstance(x, dict) and "span" in x and "score" in x]
    agg = sum(float(x["score"]) for x in valid) / len(valid) if valid else 0.0
    # Unspanned penalty: spans the judge did not score get no credit.
    # len(spans) - len(valid) reflects spans missing from judge output.
    return {
        "span_scores": valid,
        "aggregate": agg,
        "unspanned_penalized": max(0, len(spans) - len(valid)),
    }


def score(artifact_path: str, anchors_visible: list[dict], family: str) -> dict:
    """Score an artifact against visible anchors using the specified judge family.

    Args:
        artifact_path: Path to the artifact file (UTF-8 text).
        anchors_visible: List of anchor dicts; only ``span`` field is used.
        family: Judge family, one of {"codex", "claude"}.

    Returns:
        Result dict with keys: family, available, span_scores, aggregate,
        unspanned_penalized.  When available=False, aggregate=0.0 and
        unspanned_penalized=len(spans).
    """
    artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    spans = [a.get("span", "") for a in anchors_visible if a.get("span")]
    prompt = build_judge_prompt(artifact_text, spans)

    if family == "codex":
        res = judge_codex.invoke_codex_judge(prompt, timeout_s=600)
    elif family == "claude":
        res = judge_claude.invoke_claude_judge(prompt, timeout_s=600)
    else:
        raise ValueError(f"unknown judge family: {family!r}")

    if not res.get("available"):
        return {
            "family": family,
            "available": False,
            "span_scores": [],
            "aggregate": 0.0,
            "unspanned_penalized": len(spans),
        }

    parsed = _parse_span_scores(res["raw"], spans)
    parsed.update({"family": family, "available": True})
    return parsed
