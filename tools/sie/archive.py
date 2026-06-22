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
import shutil
import statistics

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
    os.makedirs(os.path.join(d, "versions"), exist_ok=True)
    return d


def _load_versions(archive_dir: str) -> list[dict]:
    """Load version entries from lineage.json (plain list format)."""
    path = os.path.join(archive_dir, LINEAGE)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Support both plain list (M1a add_version format) and
    # dict-with-versions-key (legacy/alt format).
    if isinstance(data, list):
        return data
    return data.get("versions", [])


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
    arch = _arch_dir(run_dir)
    os.makedirs(os.path.join(arch, "versions", vid), exist_ok=True)

    current = lineage(arch)
    current.append({"vid": vid, "parent_vid": parent_vid, "scores": scores})

    path = os.path.join(arch, LINEAGE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic rename preserves append-only semantics


def lineage(archive_dir: str) -> list[dict]:
    """Return the full ordered list of lineage entries from *archive_dir*."""
    path = os.path.join(archive_dir, LINEAGE)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def snapshot_version(archive_dir: str, vid: str, sandbox_root: str) -> None:
    """Copy *sandbox_root* into ``<archive_dir>/versions/<vid>/snapshot/``.

    Ignores ``.git``, ``__pycache__``, and ``.sie`` directories.
    If a snapshot already exists it is replaced.
    """
    dst = os.path.join(archive_dir, "versions", vid, "snapshot")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(
        sandbox_root,
        dst,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".sie"),
    )


def rollback(archive_dir: str, vid: str) -> None:
    """Restore the snapshot of *vid* into ``<archive_dir>/current/``.

    Raises ``FileNotFoundError`` when no snapshot exists for *vid*.
    """
    src = os.path.join(archive_dir, "versions", vid, "snapshot")
    if not os.path.isdir(src):
        raise FileNotFoundError(
            f"rollback: no snapshot found for version '{vid}' at {src!r}"
        )
    cur = os.path.join(archive_dir, "current")
    if os.path.exists(cur):
        shutil.rmtree(cur)
    shutil.copytree(src, cur)


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
    with open(retired_path, "a", encoding="utf-8") as fh:
        for v in retired_entries:
            fh.write(json.dumps({"vid": v["vid"], "reason": "stale_active_cap"}) + "\n")


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
