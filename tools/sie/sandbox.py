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
# IMMUTABLE: outward-facing ops are always GATED, not subject to --mode.
# Ops: push (VCS push), merge_main (main merge), send (external dispatch),
# delete_outside (boundary deletion), land (human-initiated landing),
# approve (human-initiated approval).
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
        # Different drives on Windows, definitely outside.
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


def _windows_short_path(path: str) -> str | None:
    import ctypes

    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_short.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    size = get_short(path, buffer, len(buffer))
    return buffer.value if 0 < size < len(buffer) else None


def _git_path(path: str) -> str:
    """Use a verified short spelling when Windows Git cannot open the full path."""
    def fits(value):
        return len((value + os.sep + ".git").encode("utf-16-le")) // 2 < 260

    if os.name != "nt" or fits(path):
        return path
    existing = path if os.path.exists(path) else os.path.dirname(path)
    short = _windows_short_path(existing)
    if short is None:
        raise RuntimeError(
            "Git for Windows cannot use this path; configure a shorter PRIVATE data directory.")
    if not os.path.samefile(existing, short):
        raise RuntimeError("Windows short path does not identify the verified directory")
    native = short if existing == path else os.path.join(short, os.path.basename(path))
    if not fits(native):
        raise RuntimeError(
            "Git for Windows cannot use this path; configure a shorter PRIVATE data directory.")
    return native


def native_cwd(path: str) -> str:
    """Return the same directory in a form accepted by native process startup."""
    absolute = os.path.abspath(path)
    if not os.path.isdir(absolute):
        raise NotADirectoryError(absolute)
    if os.name != "nt" or len(absolute.encode("utf-16-le")) // 2 < 260:
        return absolute
    return _git_path(absolute)


def make_worktree(target: str, base_ref: str, run_id: str) -> str:
    """Create (or resume) a git worktree for *run_id* and return its absolute path.

    New worktrees use detached HEAD under the verified private target namespace.
    An existing worktree is returned as-is, preserving its checkout and edits
    (idempotent / resume-safe).

    Raises subprocess.CalledProcessError if git fails.
    """
    from tools.sie.runtime_data import worktree_directory
    target = os.path.realpath(target)
    sandbox_root = str(worktree_directory(target, run_id))
    worktrees_dir = os.path.dirname(sandbox_root)
    os.makedirs(worktrees_dir, exist_ok=True)

    # Resume only a worktree belonging to this target's Git repository.
    dot_git = os.path.join(sandbox_root, ".git")
    if os.path.isfile(dot_git):
        def common_dir(path):
            native = _git_path(path)
            # getcwd expands a short spelling back to the long path. Keep long
            # worktree discovery outside that directory with an explicit Gitdir.
            location = ['-C', path] if native == path else ['--git-dir=' + os.path.join(native, '.git')]
            result = subprocess.run(
                ['git', '-c', 'core.longpaths=true', *location,
                 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                check=True, capture_output=True, text=True, encoding='utf-8')
            return os.path.realpath(result.stdout.strip())
        if common_dir(target) != common_dir(sandbox_root):
            raise RuntimeError('Existing candidate worktree belongs to another repository')
        return sandbox_root

    git_destination = _git_path(sandbox_root)
    git_target = _git_path(target)
    try:
        relative = os.path.relpath(git_destination, git_target)
    except ValueError:
        pass
    else:
        if len(relative) < len(git_destination):
            git_destination = relative
    subprocess.run(
        ["git", "-c", "core.longpaths=true", "-C", git_target, "worktree", "add", "--detach", git_destination, base_ref],
        check=True,
        capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return sandbox_root
