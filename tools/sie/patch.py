"""patch.py — apply patch to sandbox worktree with AST-level import whitelist and danger gate.

Security contract (M1a/M1b):
- import_gate: AST scan; rejects non-whitelisted imports and a baseline set of
  dangerous builtins/module-attribute calls.
- scan_ast_dangerous: full danger call gate (M1b) — covers alias bypass, importlib,
  builtins.__import__/getattr, dangerous module prefixes, sandbox-escaping open().
- apply_patch: boundary-first (canonical_in_sandbox), then import_gate, then
  scan_ast_dangerous, then write.  Any failure → REJECT; file is never written.
"""
from __future__ import annotations

import ast
import os

from tools.sie.sandbox import canonical_in_sandbox

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

# Top-level module prefixes whose import or use is forbidden by default.
DANGEROUS_MODULE_PREFIXES: frozenset[str] = frozenset({
    "subprocess", "socket", "ctypes", "importlib", "imp",
    "requests", "urllib", "httpx", "http", "aiohttp",
    "ftplib", "telnetlib", "smtplib", "asyncio",
    "multiprocessing", "concurrent",
})

# Modules permitted by default without an explicit allow set.
DEFAULT_IMPORT_ALLOW: frozenset[str] = frozenset({
    "os", "sys", "re", "json", "math", "typing", "dataclasses",
    "pathlib", "collections", "itertools", "functools", "datetime",
    "ast", "hashlib", "io", "string", "textwrap", "enum", "abc",
    "decimal", "copy", "pprint", "struct", "time",
})
# Note: "os" is in DEFAULT_IMPORT_ALLOW so patch targets can use os.path etc.,
# but os.system / os.popen are still caught by DANGEROUS_CALLS.


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
    """Return names that are directly bound to a dangerous callable or attribute.

    Tracks assignments of the form:
        fn = eval            # Name bound to a dangerous builtin
        fn = os.system       # Name bound to a dangerous attribute
        g  = importlib.import_module
    The returned set is then used in the call-site scan so that
        fn('x')   or   g('cmd')
    is also rejected.

    Limitation: only direct-assignment bindings are tracked (one level).
    Multi-hop (fn2 = fn) and container-based aliasing are not tracked —
    noted as a known boundary in the task brief.
    """
    tainted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # RHS: a plain Name that is a dangerous call name
        if isinstance(node.value, ast.Name) and node.value.id in DANGEROUS_CALLS:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    tainted.add(t.id)
        # RHS: an attribute chain whose leaf is dangerous, or whose top module
        # is in DANGEROUS_MODULE_PREFIXES.
        elif isinstance(node.value, ast.Attribute):
            chain = _attr_chain(node.value)
            leaf = chain.split(".")[-1]
            top = chain.split(".")[0]
            if leaf in DANGEROUS_CALLS or top in DANGEROUS_MODULE_PREFIXES:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        tainted.add(t.id)
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
    2. Call-site checks:
       - Bare function calls where the callee name is in DANGEROUS_CALLS.
       - Attribute calls whose leaf is in DANGEROUS_CALLS.
       - Attribute calls whose top-level module is in DANGEROUS_MODULE_PREFIXES.
       - Calls to *tainted* names (alias bypass: fn=eval; fn()).
    3. importlib bypass: importlib.import_module / importlib.__import__.
    4. builtins bypass: builtins.__import__(...), getattr(builtins, '__import__').
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
                    if alias.name in DANGEROUS_CALLS:
                        reasons.append(
                            f"dangerous builtins import: from {node.module} import {alias.name}"
                        )

        # ------------------------------------------------------------------
        # Call checks
        # ------------------------------------------------------------------
        elif isinstance(node, ast.Call):
            fn = node.func

            # --- Plain name call: eval(), exec(), __import__(), tainted() ---
            if isinstance(fn, ast.Name):
                name = fn.id
                if name in DANGEROUS_CALLS:
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

                # builtins bypass: builtins.__import__ / __builtins__.__import__
                elif top in ("builtins", "__builtins__") and leaf in DANGEROUS_CALLS:
                    reasons.append(f"builtins bypass: {chain}")

                # Generic dangerous leaf name
                elif leaf in DANGEROUS_CALLS:
                    reasons.append(f"dangerous call: {chain}")

                # Dangerous module prefix (e.g. subprocess.run)
                elif top in DANGEROUS_MODULE_PREFIXES:
                    reasons.append(f"dangerous module call: {chain}")

                # Tainted alias attribute call: tainted_name.something()
                elif top in tainted:
                    reasons.append(f"tainted alias call: {chain} (alias of dangerous callable)")

            # --- getattr bypass: getattr(builtins, '__import__') ---
            elif isinstance(fn, ast.Name) and fn.id == "getattr":
                # Already caught above since 'getattr' itself is not in DANGEROUS_CALLS,
                # but we need to catch getattr(builtins, dangerous_name).
                pass  # handled below via the separate getattr check

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
                if isinstance(attr_arg.value, str) and attr_arg.value in DANGEROUS_CALLS:
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
