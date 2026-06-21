"""sandbox.py — git worktree creation + realpath canonical boundary + action classification.

SECURITY-CRITICAL / IMMUTABLE module.

canonical_in_sandbox:
  Uses os.path.realpath to resolve symlinks and '..' segments before comparing
  against the sandbox root. For paths that do not yet exist (e.g. a file about
  to be written), we walk up to the nearest existing ancestor, resolve that,
  then re-append the remaining segments so the realpath of the parent is used.

action_class:
  OUTWARD_OPS are always "gated" regardless of path or --mode.
  Write/delete ops whose canonical path lands inside the sandbox are "auto".
  Everything else is "gated". This rule is IMMUTABLE.
"""

from __future__ import annotations

import os
import subprocess

# ---------------------------------------------------------------------------
# IMMUTABLE: outward-facing ops are always GATED — not subject to --mode.
# ---------------------------------------------------------------------------
OUTWARD_OPS = frozenset({"push", "merge_main", "send", "delete_outside", "land", "approve"})


def _real(path: str) -> str:
    """Return a normalised, case-folded realpath for *path*.

    For paths that do not yet exist we walk up the directory tree to the
    nearest existing ancestor, call os.path.realpath on that, then re-join
    the remaining non-existent tail segments.  This correctly handles the
    common case where a sandbox write target doesn't exist yet but its
    parent directory is inside the sandbox.
    """
    path = os.path.abspath(path)
    head = path
    tail_parts: list[str] = []
    while head and not os.path.exists(head):
        head, t = os.path.split(head)
        if not t:
            break
        tail_parts.append(t)
    resolved = os.path.realpath(head)
    for t in reversed(tail_parts):
        resolved = os.path.join(resolved, t)
    return os.path.normcase(resolved)


def canonical_in_sandbox(path: str, sandbox_root: str) -> bool:
    """Return True iff the canonical (realpath) form of *path* is inside *sandbox_root*.

    Defends against:
    - symlinks pointing outside the sandbox
    - '..' traversal
    - sibling directories whose name is a prefix of sandbox_root (e.g.
      '/a/sandbox-evil' is NOT inside '/a/sandbox')
    - Windows case-insensitive path comparison via os.path.normcase
    """
    root = os.path.normcase(os.path.realpath(sandbox_root))
    rp = _real(path)
    try:
        common = os.path.commonpath([rp, root])
    except ValueError:
        # Different drives on Windows — definitely outside.
        return False
    return common == root


def action_class(action: dict, sandbox_root: str) -> str:
    """Classify an action as 'auto' (safe, sandbox-internal) or 'gated' (requires approval).

    Rules (IMMUTABLE, not affected by --mode):
    1. op in OUTWARD_OPS  →  'gated'  (always, regardless of path)
    2. canonical(path) inside sandbox  →  'auto'
    3. everything else  →  'gated'
    """
    op = action.get("op", "")
    if op in OUTWARD_OPS:
        return "gated"
    path = action.get("path", "")
    if path and canonical_in_sandbox(path, sandbox_root):
        return "auto"
    return "gated"


def make_worktree(target: str, base_ref: str, run_id: str) -> str:
    """Create (or resume) a git worktree for *run_id* and return its absolute path.

    The worktree is placed at ``<target>/.sie/worktrees/<run_id>`` on a new
    branch ``sie/<run_id>``.  If the worktree already exists it is returned as-is
    (idempotent / resume-safe).

    Raises subprocess.CalledProcessError if git fails.
    """
    target = os.path.abspath(target)
    sandbox_root = os.path.join(target, ".sie", "worktrees", run_id)
    worktrees_dir = os.path.dirname(sandbox_root)
    os.makedirs(worktrees_dir, exist_ok=True)

    # Idempotent: if the worktree's .git file/dir already exists, just return.
    dot_git = os.path.join(sandbox_root, ".git")
    if os.path.exists(dot_git):
        return sandbox_root

    branch = f"sie/{run_id}"
    subprocess.run(
        ["git", "-C", target, "worktree", "add", "-b", branch, sandbox_root, base_ref],
        check=True,
        capture_output=True,
        text=True,
    )
    return sandbox_root
