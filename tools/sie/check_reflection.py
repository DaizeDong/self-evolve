from __future__ import annotations


# Every shape a reflection can legitimately arrive in. The four M1a names come from the serial
# reflect(); `merged_findings` comes from meta_aggregate() on the parallel MARS path, which is the
# path --live actually uses.
#
# merged_findings was missing here for the entire life of the parallel path, and the effect was not
# that the gate got stricter, it was that the gate INVERTED. A fanout that produced real findings
# arrives as {"merged_findings": [...]}, matched nothing, and was rejected; a fanout that produced
# NOTHING fell back at statemachine.py:529 to serial reflect(), which manufactures a placeholder
# like {"target_failure": "B ACCEPT"} out of the last history summary, and that passed. So the only
# reflections ever forwarded to the proposer were the empty ones, and every accepted change in three
# calibration runs was made by a proposer working from a one line stale summary.
#
# The proposer had understood merged_findings all along (backends/llm.py::_extract_findings), so the
# contract was right everywhere except the gate standing between them.
_REFLECTION_CONTENT_KEYS = ("target_failure", "static_review", "fix_content", "files",
                            "merged_findings")


def reflection_content_keys(reflection: dict) -> tuple:
    """Which recognized content keys this reflection actually carries. Used by the gate, and by the
    gate's caller to say WHAT was missing when it rejects; a rejection that cannot name the keys it
    looked for is the reason nine of ten barren rounds were unexplainable after the fact."""
    return tuple(k for k in _REFLECTION_CONTENT_KEYS if reflection and reflection.get(k))


def check(reflection: dict, threshold: float = 0.5) -> bool:
    """M1a 弱校验(spec 态3 M1): 非空且含有意义字段即过。M3 升 BenchTrace。"""
    if not reflection:
        return False
    return bool(reflection_content_keys(reflection))


def check_benchtrace(reflection: dict, available_traces: list[str],
                     threshold: float = 0.5) -> dict:
    """M3.10 BenchTrace grounding validation.

    Each finding must reference at least one real trace ID to be grounded.
    Returns dict with:
    - pass: bool, True if grounded_ratio >= threshold
    - grounded_ratio: float, grounded/total findings
    - ungrounded: list[dict], findings without valid trace refs
    """
    avail = set(available_traces)
    findings = reflection.get("findings", [])

    if not findings:
        return {"pass": False, "grounded_ratio": 0.0, "ungrounded": []}

    grounded = 0
    ungrounded: list[dict] = []

    for f in findings:
        refs = [r for r in f.get("trace_refs", []) if r in avail]
        if refs:
            grounded += 1
        else:
            ungrounded.append({
                "text": f.get("text", ""),
                "bad_refs": f.get("trace_refs", [])
            })

    ratio = grounded / len(findings)
    return {
        "pass": ratio >= threshold,
        "grounded_ratio": ratio,
        "ungrounded": ungrounded
    }
