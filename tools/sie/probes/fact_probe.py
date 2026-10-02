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
import json
from pathlib import Path
from .. import anchors as _anchors

_ANCHOR_SET_MIN = 24


def _find_artifacts(target: str) -> list[str]:
    """Find factual outputs, excluding shipped code, tests and declared fixtures.

    An explicit JSON file is an explicit artifact selection. Directory discovery
    does not treat the tool's own examples and tests as factual runtime evidence.
    """
    if os.path.isfile(target):
        return [target] if target.endswith(".json") else []
    root = Path(target)
    manifest = root / ".dataclass.json"
    declared = []
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for key in ("fixture", "tool"):
            values = data.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise ValueError("Artifact exclusions require path lists: " + key)
            declared.extend(v.rstrip("/") for v in values)
    excluded_dirs = {"tests", "test", "fixtures", "examples", "tools", "guards", "style",
                     ".git", "__pycache__", ".pytest_cache"}

    def excluded(path):
        rel = path.relative_to(root).as_posix()
        return any(rel == item or rel.startswith(item + "/") for item in declared)

    paths = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [name for name in dirs if name not in excluded_dirs
                   and not (base / name).is_symlink() and not excluded(base / name)]
        paths.extend(str(base / name) for name in files
                     if name.endswith(".json") and not (base / name).is_symlink()
                     and not excluded(base / name))
    return sorted(paths)


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
