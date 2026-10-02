"""archive.py — lineage append-only + version snapshots + rollback.

Public API (contract-locked, do not rename):
  add_version(run_dir, vid, scores, parent_vid) -> None
  snapshot_version(archive_dir, vid, sandbox_root) -> None
  lineage(archive_dir) -> list[dict]
  rollback(archive_dir, vid) -> None
  pareto_front(archive_dir) -> list[str]   # M3.8: full multi-dim Pareto front
  retire_stale(archive_dir, active_cap) -> None  # M3.8: Library Drift, cold-store not delete
  selectable_parents(archive_dir) -> list[str]  # M3.8: front members passing hard-dim gate
"""
from __future__ import annotations

import json
import os
import statistics
import math
from . import business_tree, runtime_data

LINEAGE = "lineage.json"
RETIRED = "retired.jsonl"

# Hard dimensions: objectively verifiable metrics (A-score and frozen anchors).
# Soft dimensions: subjective judge scores.
_HARD_DIMS = ("A", "anchor")
_SOFT_DIMS = ("judge",)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _arch_dir(run_dir: str) -> str:
    """Return (and create) the archive directory nested inside *run_dir*."""
    d = os.path.join(run_dir, "archive")
    runtime_data.make_directory(os.path.join(d, "versions"))
    return d



def _score_record(scores):
    """Normalize Pareto coordinates while retaining every task identity separately."""
    def number(value):
        if type(value) not in (int, float):
            raise ValueError("Archive scores must be numeric")
        try:
            valid = math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Archive scores must be finite")
        return value

    if isinstance(scores, dict):
        if any(not isinstance(key, str) or not key for key in scores):
            raise ValueError("Archive score names must be nonempty strings")
        result = {key: number(value) for key, value in scores.items()}
        if "pytest" in result and "A" not in result:
            result["A"] = result["pytest"]
        return result, []
    if not isinstance(scores, list):
        raise ValueError("Archive scores must be a coordinate mapping or task dimensions")
    dimensions, groups, names = [], {}, set()
    for item in scores:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
            raise ValueError("Archive task dimensions require a named record")
        if item["name"] in names:
            raise ValueError("Archive task names must be unique")
        names.add(item["name"])
        score, weight = number(item.get("score")), number(item.get("weight", 1.0))
        if not 0.0 <= score <= 1.0 or weight <= 0:
            raise ValueError("Archive task correctness and weight are invalid")
        tier = item.get("tier", "A")
        coordinate = {"A": "A", "B": "anchor", "C": "judge",
                      "anchor": "anchor", "judge": "judge"}.get(tier)
        if coordinate is None:
            raise ValueError("Archive task tier is unsupported")
        groups.setdefault(coordinate, []).append((score, weight))
        dimensions.append(dict(item))
    result = {key: sum(score * weight for score, weight in values) / sum(weight for _, weight in values)
              for key, values in groups.items()}
    return result, dimensions


def _version_record(entry):
    """Validate an archive reader record, including legacy dimension-list entries."""
    if not isinstance(entry, dict) or not isinstance(entry.get("vid"), str) or not entry["vid"]:
        raise ValueError("Archive version requires a nonempty identity")
    coordinates, dimensions = _score_record(entry.get("scores"))
    if "task_dimensions" in entry:
        task_coordinates, dimensions = _score_record(entry["task_dimensions"])
        if not isinstance(entry["task_dimensions"], list):
            raise ValueError("Archive task_dimensions must be a list")
        if any(coordinates.get(key) != value for key, value in task_coordinates.items()):
            raise ValueError("Archive task scores disagree with Pareto coordinates")
    return dict(entry, score_schema=1, scores=coordinates, task_dimensions=dimensions)

def _load_versions(archive_dir: str) -> list[dict]:
    """Load version entries from lineage.json (plain list format)."""
    path = os.path.join(archive_dir, LINEAGE)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Support both plain list (M1a add_version format) and
    # dict-with-versions-key (legacy/alt format).
    entries = data if isinstance(data, list) else data.get("versions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Archive lineage must contain a version list")
    versions = [_version_record(entry) for entry in entries]
    if len({entry["vid"] for entry in versions}) != len(versions):
        raise ValueError("Archive version identities must be unique")
    return versions


def _dominates(a: dict, b: dict, dims: tuple) -> bool:
    """Return True if *a* Pareto-dominates *b* across *dims*."""
    a_scores = a.get("scores", {})
    b_scores = b.get("scores", {})
    ge = all(a_scores.get(d, 0) >= b_scores.get(d, 0) for d in dims)
    gt = any(a_scores.get(d, 0) > b_scores.get(d, 0) for d in dims)
    return ge and gt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_version(
    run_dir: str,
    vid: str,
    scores: dict,
    parent_vid: str | None,
) -> None:
    """Register *vid* in the lineage (append-only) and create its version dir.

    The lineage file is rewritten atomically so that the semantic contract
    "append-only" holds: entries are never removed or reordered, only new
    entries are appended.
    """
    runtime_data.validate_run_id(vid)
    coordinates, dimensions = _score_record(scores)
    arch = os.path.join(run_dir, 'archive')
    runtime_data.private_file_path(os.path.join(arch, LINEAGE))
    current = lineage(arch)
    if any(entry['vid'] == vid for entry in current):
        raise ValueError('An accepted version ID cannot be reused')
    runtime_data.make_directory(os.path.join(arch, 'versions', vid))
    current.append({"vid": vid, "parent_vid": parent_vid, "score_schema": 1,
                    "scores": coordinates, "task_dimensions": dimensions})

    runtime_data.write_json(os.path.join(arch, LINEAGE), current)


def lineage(archive_dir: str) -> list[dict]:
    """Return validated coordinate maps with separate measured task dimensions."""
    return _load_versions(archive_dir)


def snapshot_version(archive_dir: str, vid: str, sandbox_root: str) -> None:
    """Copy *sandbox_root* into ``<archive_dir>/versions/<vid>/snapshot/``.

    Ignores ``.git``, ``__pycache__``, and ``.sie`` directories.
    If a snapshot already exists it is replaced.
    """
    runtime_data.validate_run_id(vid)
    dst = os.path.join(archive_dir, "versions", vid, "snapshot")
    if os.path.exists(dst):
        raise FileExistsError('An accepted snapshot cannot be replaced')
    business_tree.snapshot(sandbox_root, dst)


def next_version_id(run_dir: str) -> str:
    """Choose a fresh persistent identity, including when resuming a run."""
    versions = lineage(os.path.join(run_dir, 'archive'))
    numbers = [int(v['vid'][1:]) for v in versions
               if v['vid'].startswith('v') and v['vid'][1:].isdigit()]
    return f'v{max(numbers, default=0)+1}'


def rollback(archive_dir: str, vid: str) -> None:
    """Restore the snapshot of *vid* into ``<archive_dir>/current/``.

    Raises ``FileNotFoundError`` when no snapshot exists for *vid*.
    """
    runtime_data.validate_run_id(vid)
    src = os.path.join(archive_dir, "versions", vid, "snapshot")
    if not os.path.isdir(src):
        raise FileNotFoundError(
            f"rollback: no snapshot found for version '{vid}' at {src!r}"
        )
    cur = os.path.join(archive_dir, "current")
    business_tree.snapshot(src, cur)


def pareto_front(archive_dir: str) -> list[str]:
    """Return the list of non-dominated version IDs across all dimensions.

    M3.8: Full multi-objective Pareto filtering across both hard dims (A, anchor)
    and soft dims (judge).  A version is on the front if no other version
    dominates it (i.e., is >= on every dimension and strictly > on at least one).
    """
    vs = _load_versions(archive_dir)
    if not vs:
        return []
    dims = _HARD_DIMS + _SOFT_DIMS
    front = []
    for v in vs:
        dominated = any(
            _dominates(other, v, dims)
            for other in vs
            if other["vid"] != v["vid"]
        )
        if not dominated:
            front.append(v["vid"])
    return front


def selectable_parents(archive_dir: str) -> list[str]:
    """Return version IDs that are both on the Pareto front AND pass the hard-dim gate.

    Hard-dim gate: a front member is selectable only if its score on every hard
    dimension (A, anchor) is >= the median of those dimensions across ALL front
    members.  This prevents "soft-only winners" (high judge but low A/anchor)
    from becoming parents — they are cold-stored, not selectable.
    """
    vs = {v["vid"]: v for v in _load_versions(archive_dir)}
    front = pareto_front(archive_dir)
    if not front:
        return []
    # Compute per-dimension median across the full Pareto front.
    medians = {
        d: statistics.median([vs[f]["scores"].get(d, 0) for f in front])
        for d in _HARD_DIMS
    }
    return [
        f for f in front
        if all(vs[f]["scores"].get(d, 0) >= medians[d] for d in _HARD_DIMS)
    ]


def retire_stale(archive_dir: str, active_cap: int) -> None:
    """Cold-store stale versions when the active count exceeds *active_cap*.

    M3.8 Library Drift semantics:
    - Selectable parents (hard-dim front members) are preferred to keep, but
      non-selectable candidates are retired first.
    - Among candidates, the oldest (lowest last_used_round) are retired first.
    - If non-selectable candidates are insufficient, the oldest selectable
      parents are retired too (Library Drift must enforce the cap).
    - Retirement = append to ``retired.jsonl``; the original lineage.json is
      NEVER modified (cold-store, not delete).
    """
    vs = _load_versions(archive_dir)
    if len(vs) <= active_cap:
        return
    n_retire = len(vs) - active_cap
    keep = set(selectable_parents(archive_dir))
    # Non-selectable candidates retire first (oldest → lowest last_used_round).
    non_sel = [v for v in vs if v["vid"] not in keep]
    non_sel.sort(key=lambda v: v.get("last_used_round", 0))
    # Selectable parents retire only if non-selectable pool is exhausted.
    sel_candidates = [v for v in vs if v["vid"] in keep]
    sel_candidates.sort(key=lambda v: v.get("last_used_round", 0))
    retirement_order = non_sel + sel_candidates
    retired_entries = retirement_order[:n_retire]
    if not retired_entries:
        return
    retired_path = os.path.join(archive_dir, RETIRED)
    for v in retired_entries:
        runtime_data.write_json(retired_path, {"vid": v["vid"], "reason": "stale_active_cap"}, append=True)


def _read_retired(archive_dir: str) -> list[dict]:
    """Read retired.jsonl, skipping corrupted lines (robust to crash-time half-writes)."""
    path = os.path.join(archive_dir, RETIRED)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Corrupted/half-written line: skip silently
                continue
    return out
