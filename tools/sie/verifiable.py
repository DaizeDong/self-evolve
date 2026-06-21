"""
tools/sie/verifiable.py — A-grade grader + minimal env + snapshot hash + network/credential isolation.

Public API:
  grade_pytest(sandbox_root: str) -> dict   — run pytest in sandboxed subprocess, return A-grade contract
  snapshot_hash(sandbox_root: str) -> str   — deterministic SHA-256 of evaluation tree contents
  minimal_env() -> dict                     — cleaned env dict: no secrets, SIE_NO_NETWORK=1, HOME jailed
"""
from __future__ import annotations

import hashlib
import os
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
    # but more importantly it is empty — no .credentials.json can exist there.
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
    # reachable in the stripped env.  We strip secret-bearing *env vars* — not
    # the interpreter's own package resolution — so this is intentional.
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
