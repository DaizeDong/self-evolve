"""patch.py — apply patch to sandbox worktree with AST-level import whitelist and danger gate.

Security contract (M1a/M1b):
- import_gate: AST scan; rejects non-whitelisted imports and a baseline set of
  dangerous builtins/module-attribute calls.
- scan_ast_dangerous: full danger call gate (M1b) — covers alias bypass, importlib,
  builtins.__import__/getattr/__builtins__[...] subscript, dangerous module prefixes,
  sandbox-escaping open().
- apply_patch: boundary-first (canonical_in_sandbox), then import_gate, then
  scan_ast_dangerous, then write.  Any failure → REJECT; file is never written.
"""
from __future__ import annotations

import ast
import os

from tools.sie.sandbox import canonical_in_sandbox
from tools.sie import immutable as _im

# ---------------------------------------------------------------------------
# Baseline dangerous calls — used by import_gate (M1a baseline).
# ---------------------------------------------------------------------------
_DANGER_CALLS = {"eval", "exec", "compile", "__import__"}
_DANGER_ATTR = {("os", "system"), ("os", "popen")}
_DANGER_MODULES = {"subprocess", "socket", "ctypes", "multiprocessing"}

# Modules always allowed regardless of the caller-supplied allow set.
_DEFAULT_ALLOW: frozenset[str] = frozenset({
    "json", "math", "re", "typing", "dataclasses", "collections",
    "itertools", "functools", "pathlib", "datetime", "decimal",
})

# ---------------------------------------------------------------------------
# M1b public constants — full danger surface for scan_ast_dangerous.
# ---------------------------------------------------------------------------

# Dangerous bare names / attribute leaf names when called.
DANGEROUS_CALLS: frozenset[str] = frozenset({
    # builtins
    "eval", "exec", "compile", "__import__",
    # os / subprocess execution
    "system", "popen", "spawn", "spawnl", "spawnv", "spawnle", "spawnve",
    "execv", "execve", "execl", "execle", "execlp", "execlpe",
    "Popen", "run", "call", "check_call", "check_output", "getoutput",
    # ctypes loading
    "CDLL", "WinDLL", "cdll", "windll",
    # dynamic import
    "import_module",
    # network
    "socket", "create_connection", "create_server",
    "urlopen", "get", "post", "put", "delete", "patch", "request", "head",
})

# Subset of DANGEROUS_CALLS that are dangerous as *bare* names (no receiver).
# run/get/post/delete/etc. are only dangerous via a dangerous module receiver;
# they must NOT be blocked as bare names to avoid false positives on app.run(), db.run().
_BARE_DANGEROUS_CALLS: frozenset[str] = frozenset({"eval", "exec", "compile", "__import__"})

# Specific (top_module, method) pairs that are dangerous even when the top module is
# in DEFAULT_IMPORT_ALLOW (e.g., os is allowed but os.system/os.popen are not).
_DANGEROUS_MODULE_METHOD_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("os", "system"),
    ("os", "popen"),
    ("os", "execv"),
    ("os", "execve"),
    ("os", "execl"),
    ("os", "execle"),
    ("os", "execlp"),
    ("os", "execlpe"),
    ("os", "spawnl"),
    ("os", "spawnv"),
    ("os", "spawnle"),
    ("os", "spawnve"),
})

# Top-level module prefixes whose import or use is forbidden by default.
# asyncio and concurrent are removed: they are normal concurrency primitives and
# do not directly exec code or exfiltrate data.  The genuinely dangerous net/exec/proc
# modules (subprocess, socket, ctypes, multiprocessing, importlib, requests, urllib,
# httpx, http, aiohttp, ftplib, telnetlib, smtplib) remain.
DANGEROUS_MODULE_PREFIXES: frozenset[str] = frozenset({
    "subprocess", "socket", "ctypes", "importlib", "imp",
    "requests", "urllib", "httpx", "http", "aiohttp",
    "ftplib", "telnetlib", "smtplib",
    "multiprocessing",
})

# Modules permitted by default without an explicit allow set.
DEFAULT_IMPORT_ALLOW: frozenset[str] = frozenset({
    "os", "sys", "re", "json", "math", "typing", "dataclasses",
    "pathlib", "collections", "itertools", "functools", "datetime",
    "ast", "hashlib", "io", "string", "textwrap", "enum", "abc",
    "decimal", "copy", "pprint", "struct", "time",
})
# Note: "os" is in DEFAULT_IMPORT_ALLOW so patch targets can use os.path etc.,
# but os.system / os.popen are still caught by _DANGEROUS_MODULE_METHOD_PAIRS.


# ---------------------------------------------------------------------------
# Helpers for scan_ast_dangerous.
# ---------------------------------------------------------------------------

def _attr_chain(node: ast.AST) -> str:
    """Return dotted attribute chain for an Attribute node, e.g. 'os.path.join'."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_outside_sandbox(literal: str, sandbox_root: str, target_path: str) -> bool:
    """Return True if *literal* (a path string) resolves outside *sandbox_root*."""
    if not (sandbox_root and target_path):
        return False
    root = os.path.realpath(sandbox_root)
    if os.path.isabs(literal) or (len(literal) > 1 and literal[1] == ":"):
        cand = os.path.realpath(literal)
    else:
        base = os.path.dirname(os.path.realpath(target_path))
        cand = os.path.realpath(os.path.join(base, literal))
    try:
        return os.path.commonpath([root, cand]) != root
    except ValueError:
        # Different drive letters on Windows → definitely outside.
        return True


def _collect_tainted_names(tree: ast.AST) -> set[str]:
    """Return names that are directly or transitively bound to a dangerous callable.

    Tracks assignments of the form:
        fn = eval            # Name bound to a dangerous builtin
        fn = os.system       # Name bound to a dangerous attribute
        g  = importlib.import_module
        fn2 = fn             # Multi-hop: RHS is already tainted (fixed-point iteration)
    The returned set is then used in the call-site scan so that
        fn('x')   or   g('cmd')   or   fn2('x')
    is also rejected.

    Uses fixed-point iteration so that multi-hop chains like
        fn1 = eval; fn2 = fn1; fn2('x')
    are all caught.

    Container-based aliasing (lst=[eval]; lst[0]()) is not tracked —
    cannot be solved statically in general.
    """
    # Collect all assignments first; then iterate to fixed point.
    assignments: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assignments.append((t.id, node.value))

    # Seed: direct references to DANGEROUS_CALLS names or dangerous attribute chains.
    tainted: set[str] = set()
    for name, rhs in assignments:
        if isinstance(rhs, ast.Name) and rhs.id in DANGEROUS_CALLS:
            tainted.add(name)
        elif isinstance(rhs, ast.Attribute):
            chain = _attr_chain(rhs)
            leaf = chain.split(".")[-1]
            top = chain.split(".")[0]
            if leaf in DANGEROUS_CALLS or top in DANGEROUS_MODULE_PREFIXES:
                tainted.add(name)

    # Fixed-point: propagate taint through Name-to-Name assignments.
    changed = True
    while changed:
        changed = False
        for name, rhs in assignments:
            if name not in tainted and isinstance(rhs, ast.Name) and rhs.id in tainted:
                tainted.add(name)
                changed = True

    return tainted


# ---------------------------------------------------------------------------
# M1b public gate function.
# ---------------------------------------------------------------------------

def scan_ast_dangerous(
    source: str,
    *,
    allow_imports: set[str] | None = None,
    sandbox_root: str | None = None,
    target_path: str | None = None,
) -> list[str]:
    """Full-spectrum AST danger scan (M1b gate).

    Returns a list of human-readable violation reasons; empty list means the
    source passed all checks.

    Checks performed:
    1. Import whitelist (DEFAULT_IMPORT_ALLOW | allow_imports).
       - Any top-level module not in that set → rejected.
       - Any top-level module in DANGEROUS_MODULE_PREFIXES → rejected even if
         the caller adds it to allow_imports (hard block).
    2. Call-site checks — two distinct paths to avoid over-blocking:
       a. Bare function calls (ast.Name func, no receiver):
          Only eval/exec/compile/__import__ are blocked here.  Names like
          run/get/post are only meaningful as dangerous when called on a
          dangerous module, so they are NOT blocked as bare names (to avoid
          false positives on app.run(), db.run(q), etc.).
       b. Attribute calls (x.method(), ast.Attribute func):
          - importlib bypass: importlib.import_module / importlib.__import__.
          - builtins bypass: builtins.<dangerous> / __builtins__.<dangerous>.
          - Dangerous module prefix (e.g. subprocess.run, requests.get) via
            top ∈ DANGEROUS_MODULE_PREFIXES — this is the primary mechanism
            for names like run/get/post/delete/socket etc.
          - Tainted alias attribute call.
          Note: generic "leaf ∈ DANGEROUS_CALLS" is NOT used for arbitrary
          receivers — that caused false positives on client.get(), db.run() etc.
       c. Subscript calls: __builtins__['eval']('x') and builtins['exec']('x').
       d. Tainted alias bare calls: fn=eval; fn().
    3. importlib bypass: importlib.import_module / importlib.__import__.
    4. builtins bypass: builtins.__import__(...), getattr(builtins, '__import__'),
       builtins['eval'](...) subscript form.
    5. Sandbox-escaping open(): literal absolute paths outside sandbox_root.
       When sandbox_root is given but the path is non-literal → rejected
       (cannot be statically proven safe).
    """
    allow = set(DEFAULT_IMPORT_ALLOW) | set(allow_imports or set())
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"unparseable source: {e}"]

    reasons: list[str] = []

    # Pass 1: collect alias-tainted names (must precede call-site scan).
    tainted = _collect_tainted_names(tree)

    for node in ast.walk(tree):
        # ------------------------------------------------------------------
        # Import checks
        # ------------------------------------------------------------------
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in DANGEROUS_MODULE_PREFIXES:
                    reasons.append(f"dangerous module import: {alias.name}")
                elif top not in allow:
                    reasons.append(f"import not in allowlist: {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in DANGEROUS_MODULE_PREFIXES:
                reasons.append(f"dangerous module import: {node.module}")
            elif top and top not in allow:
                reasons.append(f"import-from not in allowlist: {node.module}")
            # Symbol-level check: from builtins import __import__ etc.
            if node.module in ("builtins", "__builtins__"):
                for alias in node.names:
                    if alias.name in _BARE_DANGEROUS_CALLS:
                        reasons.append(
                            f"dangerous builtins import: from {node.module} import {alias.name}"
                        )

        # ------------------------------------------------------------------
        # Call checks
        # ------------------------------------------------------------------
        elif isinstance(node, ast.Call):
            fn = node.func

            # --- Bare name call: eval(), exec(), compile(), __import__() ---
            # Only real dangerous builtins are blocked here (not run/get/post/etc.,
            # which are only dangerous when called on a dangerous module — those are
            # caught via DANGEROUS_MODULE_PREFIXES in the Attribute branch below).
            if isinstance(fn, ast.Name):
                name = fn.id
                if name in _BARE_DANGEROUS_CALLS:
                    reasons.append(f"dangerous call: {name}")
                elif name in tainted:
                    reasons.append(f"tainted alias call: {name} (alias of dangerous callable)")

            # --- Attribute call: a.b.c() ---
            elif isinstance(fn, ast.Attribute):
                chain = _attr_chain(fn)
                leaf = chain.split(".")[-1] if chain else ""
                top = chain.split(".")[0] if chain else ""

                # importlib bypass: importlib.import_module / importlib.__import__
                if top == "importlib" and leaf in ("import_module", "__import__"):
                    reasons.append(f"importlib bypass: {chain}")

                # builtins bypass: builtins.<dangerous> / __builtins__.<dangerous>
                elif top in ("builtins", "__builtins__") and leaf in _BARE_DANGEROUS_CALLS:
                    reasons.append(f"builtins bypass: {chain}")

                # Specific dangerous (module, method) pairs on otherwise-allowed modules
                # (e.g. os.system, os.popen — os itself is allowed but these methods are not).
                elif (top, leaf) in _DANGEROUS_MODULE_METHOD_PAIRS:
                    reasons.append(f"dangerous call: {chain}")

                # Dangerous module prefix (e.g. subprocess.run, requests.get, socket.socket).
                # This is the primary mechanism for run/get/post/delete/socket/etc.
                elif top in DANGEROUS_MODULE_PREFIXES:
                    reasons.append(f"dangerous module call: {chain}")

                # Tainted alias attribute call: tainted_name.something()
                elif top in tainted:
                    reasons.append(f"tainted alias call: {chain} (alias of dangerous callable)")

                # Note: generic "leaf in DANGEROUS_CALLS" is intentionally NOT used for
                # arbitrary receivers to avoid false positives (client.get, db.run, app.run).

            # --- Subscript call: __builtins__['eval']('x') or builtins['exec']('x') ---
            elif isinstance(fn, ast.Subscript):
                sub_val = fn.value
                sub_slice = fn.slice
                # Unwrap Index node for Python < 3.9 compatibility
                if isinstance(sub_slice, ast.Index):
                    sub_slice = sub_slice.value  # type: ignore[attr-defined]
                if (
                    isinstance(sub_val, ast.Name)
                    and sub_val.id in ("builtins", "__builtins__")
                    and isinstance(sub_slice, ast.Constant)
                    and isinstance(sub_slice.value, str)
                    and sub_slice.value in _BARE_DANGEROUS_CALLS
                ):
                    reasons.append(
                        f"builtins subscript bypass: {sub_val.id}['{sub_slice.value}']"
                    )

        # ------------------------------------------------------------------
        # getattr(builtins, '__import__') / getattr(obj, 'eval') bypass
        # ------------------------------------------------------------------
        # Detect: getattr(<builtins_ref>, <dangerous_name_literal>)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            obj_arg = node.args[0]
            attr_arg = node.args[1]
            obj_is_builtins = (
                isinstance(obj_arg, ast.Name)
                and obj_arg.id in ("builtins", "__builtins__")
            ) or (
                isinstance(obj_arg, ast.Attribute)
                and _attr_chain(obj_arg).split(".")[0] in ("builtins", "__builtins__")
            )
            if obj_is_builtins and isinstance(attr_arg, ast.Constant):
                if isinstance(attr_arg.value, str) and attr_arg.value in _BARE_DANGEROUS_CALLS:
                    reasons.append(
                        f"builtins getattr bypass: getattr(builtins, '{attr_arg.value}')"
                    )

        # ------------------------------------------------------------------
        # open() sandbox escape check
        # ------------------------------------------------------------------
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            and node.args
        ):
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                if sandbox_root and _is_outside_sandbox(arg0.value, sandbox_root, target_path or ""):
                    reasons.append(f"open outside sandbox: {arg0.value!r}")
            elif sandbox_root:
                # Dynamic path — cannot prove in-sandbox statically.
                reasons.append("open with non-literal path (cannot prove in-sandbox)")

    return reasons


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


def immutable_gate(target_relpaths: list[str], enforce: bool) -> dict | None:
    """自举/enforce 时拦截命中 IMMUTABLE 裁决路径的 patch。

    Args:
        target_relpaths: 本次 patch 要写入的相对路径列表。
        enforce: True → 命中即返回 REJECT dict；False → 全放行返回 None。

    Returns:
        {"decision": "REJECT", "reason": "immutable_hit", "paths": [...]} 命中时；
        None 未命中或 enforce=False 时（放行，继续后续门）。
    """
    if not enforce:
        return None
    hits = [p for p in target_relpaths if _im.is_immutable_relpath(p)]
    if hits:
        return {"decision": "REJECT", "reason": "immutable_hit", "paths": hits}
    return None


def apply_patch(
    sandbox_root: str,
    file_rel: str,
    new_content: str,
    allow: set[str] | None = None,
    enforce_immutable: bool = False,
) -> dict:
    """Write *new_content* to *<sandbox_root>/<file_rel>* after passing all gates.

    Gates (in order):
    0. immutable_gate (M4.3) — IMMUTABLE 路径硬拒（仅 enforce_immutable=True 时生效）
    1. canonical_in_sandbox — boundary hard gate (path traversal / symlink escape)
    2. import_gate (only for .py files) — AST whitelist + danger call check
    3. scan_ast_dangerous (M1b) — full danger surface

    Args:
        sandbox_root: Root directory of the sandbox worktree.
        file_rel: Relative path within sandbox_root to write.
        new_content: New file content (text).
        allow: Extra import module names to whitelist for AST gates.
        enforce_immutable: When True (self-bootstrap mode), any write to an
            IMMUTABLE path is rejected before all other gates. Default False
            preserves backward compatibility with existing callers.

    Returns:
        {"status": "APPLIED", "reason": "ok"}     — written successfully
        {"status": "REJECT",  "reason": <str>}    — rejected; file NOT written
    """
    # Gate 0: IMMUTABLE 硬拒门（独立于 AST 门，先于一切应用）。
    # enforce_immutable=False（默认）时跳过，向后兼容 M1/M3 调用方。
    _gate = immutable_gate([file_rel], enforce_immutable)
    if _gate is not None:
        paths_str = ", ".join(_gate["paths"])
        return {"status": "REJECT", "reason": f"immutable_hit: {paths_str}"}

    target = os.path.normpath(os.path.join(sandbox_root, file_rel))

    # Gate 1: boundary — must run BEFORE any I/O.
    if not canonical_in_sandbox(target, sandbox_root):
        return {"status": "REJECT", "reason": "path outside sandbox boundary"}

    # Gate 2: import_gate (M1a baseline whitelist + baseline danger calls).
    if file_rel.endswith(".py"):
        ok, why = import_gate(new_content, allow)
        if not ok:
            return {"status": "REJECT", "reason": f"AST gate: {why}"}

    # Gate 3: scan_ast_dangerous (M1b full danger surface — alias bypass,
    # importlib, builtins, sandbox-escaping open).
    if file_rel.endswith(".py"):
        ast_reasons = scan_ast_dangerous(
            new_content,
            allow_imports=set(allow) if allow is not None else None,
            sandbox_root=sandbox_root,
            target_path=os.path.join(sandbox_root, file_rel),
        )
        if ast_reasons:
            return {"status": "REJECT", "reason": f"AST danger gate: {'; '.join(ast_reasons)}"}

    # All gates passed — write.
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    return {"status": "APPLIED", "reason": "ok"}
