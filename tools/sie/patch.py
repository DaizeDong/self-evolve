"""patch.py — apply patch to sandbox worktree with AST-level import whitelist and danger gate.

Security contract (M1a):
- import_gate: AST scan; rejects non-whitelisted imports and a baseline set of
  dangerous builtins/module-attribute calls. Full danger call list extended in M1b.
- apply_patch: boundary-first (canonical_in_sandbox), then AST gate, then write.
  Any failure → REJECT with reason; file is never written on rejection.
"""
from __future__ import annotations

import ast
import os

from tools.sie.sandbox import canonical_in_sandbox

# ---------------------------------------------------------------------------
# Baseline dangerous calls — extended in M1b to the full list.
# ---------------------------------------------------------------------------
_DANGER_CALLS = {"eval", "exec", "compile", "__import__"}
_DANGER_ATTR = {("os", "system"), ("os", "popen")}
_DANGER_MODULES = {"subprocess", "socket", "ctypes", "multiprocessing"}

# Modules always allowed regardless of the caller-supplied allow set.
_DEFAULT_ALLOW: frozenset[str] = frozenset({
    "json", "math", "re", "typing", "dataclasses", "collections",
    "itertools", "functools", "pathlib", "datetime", "decimal",
})


def import_gate(source: str, allow: set[str] | None = None) -> tuple[bool, str]:
    """AST scan *source*; return (True, "") on pass or (False, reason) on rejection.

    Rejection conditions (M1a baseline):
    - SyntaxError in source
    - `import X` / `from X import ...` where X (top-level module name) is in
      _DANGER_MODULES — rejected even if the caller whitelists it
    - `import X` / `from X import ...` where X is not in (allow | _DEFAULT_ALLOW)
    - Call nodes matching _DANGER_CALLS (eval/exec/compile/__import__)
    - Attribute-call nodes matching _DANGER_ATTR (os.system, os.popen)
    - `from X import Y` where (X, Y) is in _DANGER_ATTR (blocks symbol smuggling)

    *allow* is merged with _DEFAULT_ALLOW; pass an empty set() to allow only defaults.
    """
    allowed = (set(allow) if allow is not None else set()) | _DEFAULT_ALLOW
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _DANGER_MODULES:
                    return False, f"dangerous module import: {top}"
                if top not in allowed:
                    return False, f"import not in whitelist: {top}"

        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _DANGER_MODULES:
                return False, f"dangerous module import: {top}"
            if top and top not in allowed:
                return False, f"import not in whitelist: {top}"
            # Check for dangerous symbols imported from the module
            if node.module:
                for alias in node.names:
                    # Check by original symbol name (not asname)
                    symbol_name = alias.name
                    if (node.module, symbol_name) in _DANGER_ATTR:
                        return False, f"dangerous import: from {node.module} import {symbol_name}"

        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _DANGER_CALLS:
                return False, f"dangerous builtin call: {fn.id}"
            if (isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and (fn.value.id, fn.attr) in _DANGER_ATTR):
                return False, f"dangerous call: {fn.value.id}.{fn.attr}"

    return True, ""


def apply_patch(
    sandbox_root: str,
    file_rel: str,
    new_content: str,
    allow: set[str] | None = None,
) -> dict:
    """Write *new_content* to *<sandbox_root>/<file_rel>* after passing all gates.

    Gates (in order, IMMUTABLE):
    1. canonical_in_sandbox — boundary hard gate (path traversal / symlink escape)
    2. import_gate (only for .py files) — AST whitelist + danger call check

    Returns:
        {"status": "APPLIED", "reason": "ok"}     — written successfully
        {"status": "REJECT",  "reason": <str>}    — rejected; file NOT written
    """
    target = os.path.normpath(os.path.join(sandbox_root, file_rel))

    # Gate 1: boundary — must run BEFORE any I/O.
    if not canonical_in_sandbox(target, sandbox_root):
        return {"status": "REJECT", "reason": "path outside sandbox boundary"}

    # Gate 2: AST check for Python files.
    if file_rel.endswith(".py"):
        ok, why = import_gate(new_content, allow)
        if not ok:
            return {"status": "REJECT", "reason": f"AST gate: {why}"}

    # All gates passed — write.
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    return {"status": "APPLIED", "reason": "ok"}
