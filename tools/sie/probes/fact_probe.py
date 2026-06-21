"""fact 探针: 代码判定带锚字段的调研产物 -> B 维信号 (不信 prose 自称).

防自欺（spec §5.1）：扫产物真正带 claim/span/source_url 三件套的结构化锚，
数量达 anchor_set_min(24) 才给 B 维信号。塑造 docstring 放水也无法骗过
（没有真锚字段就没信号）。

Contract:
  probe(target: str, base_ref: str) -> dict
  返回：{"tier_signal": "B"|None, "anchor_count": int,
         "verifiable_coverage": float, "evidence": {...}}
"""
from __future__ import annotations

import os
import glob
from .. import anchors as _anchors

_ANCHOR_SET_MIN = 24


def _find_artifacts(target: str) -> list[str]:
    """Locate artifact JSON files.

    If target is a file, return [target] if it's .json, else [].
    If target is a dir, recursively find all .json files.
    """
    if os.path.isfile(target):
        return [target] if target.endswith(".json") else []
    return sorted(glob.glob(os.path.join(target, "**", "*.json"), recursive=True))


def probe(target: str, base_ref: str) -> dict:
    """Probe for factual anchors in research artifacts.

    Scans target location for JSON artifacts, extracts all structurally valid
    anchors (must have claim, span, source_url), and determines if count reaches
    the minimum threshold for B-tier signal.

    Args:
        target: File or directory path to scan
        base_ref: Git base reference (passed for context, not currently used)

    Returns:
        dict with:
          - tier_signal: "B" if anchor_count >= _ANCHOR_SET_MIN, else None
          - anchor_count: Number of valid anchors found
          - verifiable_coverage: Fraction of anchor spans that are verified
          - evidence: Dict with scanned_files, anchor_set_min, etc.
    """
    all_anchors: list[dict] = []
    scanned = []

    for path in _find_artifacts(target):
        try:
            found = _anchors.extract_anchors(path)
        except Exception:
            # Skip files that can't be parsed or don't contain valid anchors
            continue
        if found:
            scanned.append(path)
            all_anchors.extend(found)

    n = len(all_anchors)
    cov = _anchors.coverage(all_anchors)
    signal = "B" if n >= _ANCHOR_SET_MIN else None

    return {
        "tier_signal": signal,
        "anchor_count": n,
        "verifiable_coverage": cov,
        "evidence": {
            "scanned_files": scanned,
            "anchor_set_min": _ANCHOR_SET_MIN,
        },
    }
