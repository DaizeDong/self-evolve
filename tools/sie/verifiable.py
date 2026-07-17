"""
tools/sie/verifiable.py — A-grade grader + minimal env + snapshot hash + network/credential isolation.

Public API:
  grade_pytest(sandbox_root: str) -> dict   — run pytest in sandboxed subprocess, return A-grade contract
  snapshot_hash(sandbox_root: str) -> str   — deterministic SHA-256 of evaluation tree contents
  minimal_env() -> dict                     — cleaned env dict: no secrets, SIE_NO_NETWORK=1, HOME jailed
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

_ENV_WHITELIST = {
    "PATH",
    "SYSTEMROOT",
    "SystemRoot",
    "COMSPEC",
    "PATHEXT",
    "PYTHONDONTWRITEBYTECODE",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
}

_SECRET_MARKERS = (
    "TOKEN",
    "KEY",
    "SECRET",
    "CREDENTIAL",
    "API",
    "PASSWORD",
    "AWS",
    "ANTHROPIC",
    "OPENAI",
    "DISCORD",
)

# ---------------------------------------------------------------------------
# sitecustomize payload injected into every grader subprocess.
#
# Network-block design:
#   - socket.create_connection (module-level function) → replaced with blocker.
#   - socket.socket (the class) → replaced with a subclass that overrides
#     connect/connect_ex.  We do NOT replace socket.socket with a plain function
#     because ssl.SSLSocket inherits socket.socket; class replacement must preserve
#     the class interface.  We force-import ssl BEFORE swapping so that
#     SSLSocket's class body executes against the real socket.socket, then we swap.
#
# Exfil-block: builtins.__import__ hook rejects discord_relay / discord.
# ---------------------------------------------------------------------------

_SITE = """\
import socket as _s

def _blocked_fn(*a, **k):
    raise OSError('SIE network disabled (M1 no-network gate)')

_s.create_connection = _blocked_fn

# Subclass preserves the class for ssl.SSLSocket(socket.socket) inheritance.
_OrigSocket = _s.socket

class _BlockedSocket(_OrigSocket):
    def connect(self, *a, **k):
        raise OSError('SIE network disabled (M1 no-network gate)')
    def connect_ex(self, *a, **k):
        raise OSError('SIE network disabled (M1 no-network gate)')
    def sendto(self, *a, **k):
        raise OSError('SIE network disabled (M1 no-network gate)')
    def sendmsg(self, *a, **k):
        raise OSError('SIE network disabled (M1 no-network gate)')
    def sendall(self, *a, **k):
        raise OSError('SIE network disabled (M1 no-network gate)')

# Force ssl to load before we swap socket.socket, so SSLSocket class body
# runs against the real class; then swap for candidate code.
try:
    import ssl as _ssl  # noqa: F401
except Exception:
    pass
_s.socket = _BlockedSocket

# Block exfiltration via discord_relay.
import builtins as _b
_orig_import = _b.__import__

def _imp(name, *a, **k):
    if name.split('.')[0] in ('discord_relay', 'discord'):
        raise ImportError('SIE: candidate forbidden to import discord_relay')
    return _orig_import(name, *a, **k)

_b.__import__ = _imp
"""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def minimal_env() -> dict:
    """Return a cleaned environment dict suitable for sandboxed subprocesses.

    - Only whitelist keys are kept (PATH, SYSTEMROOT, COMSPEC, PATHEXT, TMP/TEMP,
      LANG/LC_ALL, PYTHONDONTWRITEBYTECODE).
    - Any key whose upper-case name contains a _SECRET_MARKERS substring is removed.
    - SIE_NO_NETWORK=1 is injected (signals no-network mode to any cooperative code).
    - HOME and USERPROFILE are pointed at a freshly created empty temporary directory
      so that os.path.expanduser('~') resolves to the jail, making ~/.credentials.json
      unreachable.
    """
    base: dict[str, str] = {}
    for k, v in os.environ.items():
        if k not in _ENV_WHITELIST:
            continue
        if any(m in k.upper() for m in _SECRET_MARKERS):
            continue
        base[k] = v

    base["PYTHONDONTWRITEBYTECODE"] = "1"
    base["SIE_NO_NETWORK"] = "1"

    # Create an empty jail directory for HOME/USERPROFILE.
    # tempfile.mkdtemp returns a directory only readable by the current user,
    # but more importantly it is empty, no .credentials.json can exist there.
    jail = tempfile.mkdtemp(prefix="sie_home_")
    # Note: jail is readable/writable to allow subprocess to create temp files.
    # The security model depends on the jail being initially empty, not on permissions.
    base["HOME"] = jail
    base["USERPROFILE"] = jail  # Windows equivalent of HOME

    return base


def _grader_env(sandbox_root: str) -> tuple[dict, str, str]:
    """Build subprocess env with sitecustomize injected.

    Returns (env_dict, site_dir, jail_dir) — caller owns cleanup of site_dir and jail_dir.
    """
    env = minimal_env()
    jail_dir = env["HOME"]  # Extract jail from minimal_env before it gets shadowed

    # Write sitecustomize.py into a temporary directory that precedes sandbox
    # on PYTHONPATH, so Python loads it before any user code.
    site_dir = tempfile.mkdtemp(prefix="sie_site_")
    with open(os.path.join(site_dir, "sitecustomize.py"), "w", encoding="utf-8") as fh:
        fh.write(_SITE)

    # PYTHONPATH: site_dir first (loads sitecustomize), then sandbox_root
    # (makes sandbox modules importable without install), then the current
    # interpreter's full sys.path so that pytest and all installed packages are
    # reachable in the stripped env.  We strip secret-bearing *env vars*, not
    # the interpreter's own package resolution, so this is intentional.
    # Filter out empty strings and zip files (not useful on PYTHONPATH).
    extra_paths = [
        p for p in sys.path
        if p and not p.endswith(".zip") and os.path.isdir(p)
    ]

    existing = env.get("PYTHONPATH", "")
    parts = [site_dir, sandbox_root] + extra_paths
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)

    return env, site_dir, jail_dir


def grade_pytest(sandbox_root: str) -> dict:
    """Run pytest in a sandboxed subprocess under minimal_env + sitecustomize network block.

    Returns A-grade contract dict:
      {
        "task_passed": bool,
        "grader_exit_code": int,
        "dimensions": [{"name": "pytest", "tier": "A", "score": 0.0|1.0, "weight": 1.0}],
        "anchors": [],
        "verifiable_coverage": 1.0
      }

    score mapping (A-grade binary):
      grader_exit_code == 0  ->  score=1.0, task_passed=True
      otherwise              ->  score=0.0, task_passed=False
    """
    env, site_dir, jail_dir = _grader_env(sandbox_root)

    try:
        # Disable anyio plugin via environment variable to avoid asyncio issues on Windows
        # with the stripped PYTHONPATH.
        grader_env = env.copy()
        grader_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header"],
            cwd=sandbox_root,
            capture_output=True,
            text=True,
            env=grader_env,
        )

        code = proc.returncode
        passed = code == 0
        score = 1.0 if passed else 0.0

        return {
            "task_passed": passed,
            "grader_exit_code": code,
            "dimensions": [
                {"name": "pytest", "tier": "A", "score": score, "weight": 1.0}
            ],
            "anchors": [],
            "verifiable_coverage": 1.0,
        }
    finally:
        # Clean up temporary directories.
        import shutil
        for tmpdir in [site_dir, jail_dir]:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


def snapshot_hash(sandbox_root: str) -> str:
    """Compute a deterministic SHA-256 over all files in sandbox_root.

    Walk order is sorted (directories and filenames), so the hash is stable
    across platforms.  Excludes: .git, __pycache__, .sie directories.

    Each file contributes: its relative path (forward-slash normalised) + raw bytes.
    Returns a 64-char hex string.
    """
    h = hashlib.sha256()

    for dirpath, dirnames, filenames in os.walk(sandbox_root):
        # Mutate in-place to control recursion order and exclude noise dirs.
        dirnames[:] = sorted(
            d for d in dirnames if d not in {".git", "__pycache__", ".sie"}
        )

        for name in sorted(filenames):
            fp = os.path.join(dirpath, name)
            rel = os.path.relpath(fp, sandbox_root).replace("\\", "/")
            h.update(rel.encode("utf-8"))
            try:
                with open(fp, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                # Unreadable file: include the path but no content.
                continue

    return h.hexdigest()


# ---------------------------------------------------------------------------
# Mutation testing, inject_mutants + mutation_validity_gate
# ---------------------------------------------------------------------------

# Operator flip tables for Compare nodes.
_CMP_FLIP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
}


class _Mutator(ast.NodeTransformer):
    """One-shot AST transformer: mutates exactly the mutation site at *target_idx*.

    Sites are counted in DFS order across BinOp (Add↔Sub), Compare (op flip),
    and Constant bool (True↔False) nodes.  *applied* is set to True if the
    target site was reached and mutated.
    """

    def __init__(self, target_idx: int) -> None:
        self.target_idx = target_idx
        self._counter = 0
        self.applied = False

    def _hit(self) -> bool:
        """Return True if the current site index matches target; always increments counter."""
        result = self._counter == self.target_idx
        self._counter += 1
        return result

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Add) and self._hit():
            self.applied = True
            return ast.copy_location(
                ast.BinOp(left=node.left, op=ast.Sub(), right=node.right), node
            )
        if isinstance(node.op, ast.Sub) and self._hit():
            self.applied = True
            return ast.copy_location(
                ast.BinOp(left=node.left, op=ast.Add(), right=node.right), node
            )
        return node

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        # Only handle single-operator comparisons to keep mutants unambiguous.
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_FLIP and self._hit():
            self.applied = True
            flipped = _CMP_FLIP[type(node.ops[0])]()
            return ast.copy_location(
                ast.Compare(left=node.left, ops=[flipped], comparators=node.comparators),
                node,
            )
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        # Bool is a subtype of int in Python; check isinstance(node.value, bool) first.
        if isinstance(node.value, bool) and self._hit():
            self.applied = True
            return ast.copy_location(ast.Constant(value=not node.value), node)
        return node


def _count_mutation_sites(source: str) -> int:
    """Return the number of mutable sites in *source* (does not mutate anything)."""
    counter = _Mutator(target_idx=-1)  # target_idx=-1 → never matches → just counts
    counter.visit(ast.parse(source))
    return counter._counter


def inject_mutants(source: str) -> list[tuple[str, str]]:
    """Apply standard mutations to *source* and return ``[(mutant_id, mutated_source), ...]``.

    Mutation operators:
      - BinOp: ``+`` ↔ ``-``
      - Compare: ``==`` ↔ ``!=``, ``<`` ↔ ``>=``, ``<=`` ↔ ``>``
      - Constant bool: ``True`` ↔ ``False``

    Each mutable site produces exactly one mutant (single-point mutation).
    Mutant IDs are ``mut_0``, ``mut_1``, … in DFS traversal order.

    Returns an empty list if *source* cannot be parsed.
    """
    try:
        ast.parse(source)  # validate syntax before counting
    except SyntaxError:
        return []

    n_sites = _count_mutation_sites(source)
    results: list[tuple[str, str]] = []
    for i in range(n_sites):
        mut = _Mutator(target_idx=i)
        try:
            tree = mut.visit(ast.parse(source))
        except SyntaxError:
            continue
        if mut.applied:
            ast.fix_missing_locations(tree)
            try:
                mutated_src = ast.unparse(tree)
            except Exception:
                continue
            results.append((f"mut_{i}", mutated_src))
    return results


def mutation_validity_gate(
    worktree: str,
    source_files: list[str],
    run_one,
    *,
    min_kill_ratio: float = 1.0,
) -> dict:
    """Check whether the test suite in *worktree* can detect injected bugs.

    Algorithm:
    1. Verify baseline: ``run_one(worktree)`` must return True (tests are green).
       If baseline is not green, the gate has no meaning → return invalid immediately.
    2. For each file in *source_files*, inject each mutant one at a time:
       - Write mutated source to the file.
       - Call ``run_one(worktree)``.
       - If False (tests turned red) → mutant killed (good).
       - If True (tests still green) → mutant survived (grader is too weak).
       - Restore the original file content in a ``try/finally`` block.
    3. Compute ``kill_ratio = killed / total``.
       ``valid = total > 0 and kill_ratio >= min_kill_ratio``.

    Args:
        worktree:      Root directory of the sandbox / task worktree.
        source_files:  List of file paths *relative* to *worktree* to mutate.
        run_one:       Callable ``(worktree: str) -> bool`` — True means all tests green.
        min_kill_ratio: Minimum fraction of mutants that must be killed (default 1.0).

    Returns:
        {
            "valid":      bool,
            "killed":     int,
            "total":      int,
            "kill_ratio": float,
            "survivors":  [mutant_id, ...],   # format: "<rel_path>:<mut_id>"
        }
    """
    # --- Step 1: baseline check ---
    try:
        baseline_green = bool(run_one(worktree))
    except Exception:
        baseline_green = False

    if not baseline_green:
        return {
            "valid": False,
            "killed": 0,
            "total": 0,
            "kill_ratio": 0.0,
            "survivors": [],
        }

    killed = 0
    total = 0
    survivors: list[str] = []

    for rel in source_files:
        abs_path = os.path.join(worktree, rel)
        with open(abs_path, encoding="utf-8") as fh:
            original = fh.read()

        mutants = inject_mutants(original)
        if not mutants:
            continue

        for mut_id, mut_src in mutants:
            total += 1
            # Write mutant, run, restore, always restore in finally.
            try:
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(mut_src)
                try:
                    still_green = bool(run_one(worktree))
                except Exception:
                    still_green = False  # crash = mutant detected = killed

                if still_green:
                    survivors.append(f"{rel}:{mut_id}")
                else:
                    killed += 1
            finally:
                # Unconditionally restore original content.
                with open(abs_path, "w", encoding="utf-8") as fh:
                    fh.write(original)

    kill_ratio = (killed / total) if total > 0 else 0.0
    valid = total > 0 and kill_ratio >= min_kill_ratio

    return {
        "valid": valid,
        "killed": killed,
        "total": total,
        "kill_ratio": kill_ratio,
        "survivors": survivors,
    }
