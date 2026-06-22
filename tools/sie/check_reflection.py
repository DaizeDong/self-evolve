from __future__ import annotations


def check(reflection: dict, threshold: float = 0.5) -> bool:
    """M1a 弱校验(spec 态3 M1): 非空且含有意义字段即过。M3 升 BenchTrace。"""
    if not reflection:
        return False
    keys = ("target_failure", "static_review", "fix_content", "files")
    return any(reflection.get(k) for k in keys)


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
