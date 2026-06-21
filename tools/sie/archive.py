"""archive.py — lineage append-only + version snapshots + rollback.

Public API (contract-locked, do not rename):
  add_version(run_dir, vid, scores, parent_vid) -> None
  snapshot_version(archive_dir, vid, sandbox_root) -> None
  lineage(archive_dir) -> list[dict]
  rollback(archive_dir, vid) -> None
  pareto_front(archive_dir) -> list[str]   # M1a placeholder; full Pareto → M3
  retire_stale(archive_dir, active_cap) -> None  # M1a placeholder
"""
from __future__ import annotations

import json
import os
import shutil

LINEAGE = "lineage.json"
RETIRED = "retired.jsonl"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _arch_dir(run_dir: str) -> str:
    """Return (and create) the archive directory nested inside *run_dir*."""
    d = os.path.join(run_dir, "archive")
    os.makedirs(os.path.join(d, "versions"), exist_ok=True)
    return d


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
    """Return the list of active (non-dominated) version IDs.

    M1a placeholder — returns *all* recorded vids.
    Full multi-objective Pareto filtering is gated to M3.
    """
    return [e["vid"] for e in lineage(archive_dir)]


def retire_stale(archive_dir: str, active_cap: int) -> None:
    """Append stale entries to ``retired.jsonl`` when lineage exceeds *active_cap*.

    M1a placeholder — the oldest ``len(lineage) - active_cap`` entries are
    written to the retired log.  No snapshot deletion occurs here; that is
    also gated to M3.
    """
    lin = lineage(archive_dir)
    if len(lin) <= active_cap:
        return
    stale = lin[: len(lin) - active_cap]
    retired_path = os.path.join(archive_dir, RETIRED)
    with open(retired_path, "a", encoding="utf-8") as fh:
        for entry in stale:
            fh.write(json.dumps({"vid": entry["vid"], "reason": "active_cap"}) + "\n")
