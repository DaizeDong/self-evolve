"""tests/test_patch_ast_gate.py — M1b.1: AST danger gate full coverage.

Tests cover:
- All dangerous snippet categories from the brief (parametrized).
- Three M1a.6 bypass classes now blocked:
    1. Alias bypass: fn = eval; fn('x'), g = os.system; g('x')
    2. importlib bypass: importlib.import_module, importlib.__import__
    3. builtins bypass: builtins.__import__(), getattr(builtins, '__import__')
- __builtins__[...] subscript bypass: __builtins__['eval']('x') (M1b.1 fix)
- Multi-hop alias: fn1=eval; fn2=fn1; fn2('x') (M1b.1 fix, fixed-point iteration)
- Legitimate code not misidentified (no false positives including app.run(), client.get())
- apply_patch integration: dangerous content rejected before write.
"""
import os

import pytest

from tools.sie.patch import apply_patch, scan_ast_dangerous

# ---------------------------------------------------------------------------
# Dangerous snippet parametrize table (from brief + bypass extensions)
# ---------------------------------------------------------------------------

DANGEROUS_SNIPPETS = {
    # Standard dangerous calls
    "os.system":        "import os\nos.system('rm -rf /')\n",
    "subprocess.run":   "import subprocess\nsubprocess.run(['ls'])\n",
    "subprocess.Popen": "import subprocess\nsubprocess.Popen(['ls'])\n",
    "popen":            "import os\nos.popen('ls')\n",
    "socket":           "import socket\ns = socket.socket()\n",
    "ctypes":           "import ctypes\nctypes.CDLL('libc.so.6')\n",
    "eval":             "eval('1+1')\n",
    "exec":             "exec('x=1')\n",
    "compile":          "compile('1', '<s>', 'eval')\n",
    "__import__":       "m = __import__('os')\n",
    "importlib":        "import importlib\nimportlib.import_module('os')\n",
    "net_requests":     "import requests\nrequests.get('http://x')\n",
    "net_urllib":       "import urllib.request\nurllib.request.urlopen('http://x')\n",
    "net_httpx":        "import httpx\nhttpx.get('http://x')\n",
    # ---- M1a.6 bypass class 1: alias to dangerous bare name ----
    "alias_eval":       "fn = eval\nfn('x')\n",
    "alias_exec":       "fn = exec\nfn('x=1')\n",
    # ---- M1a.6 bypass class 1: alias to dangerous attribute ----
    "alias_os_system":  "import os\ng = os.system\ng('cmd')\n",
    "alias_os_popen":   "import os\ng = os.popen\ng('ls')\n",
    # ---- M1a.6 bypass class 2: importlib dynamic import ----
    "importlib_module": "import importlib\nimportlib.import_module('subprocess')\n",
    "importlib_dunder": "import importlib\nimportlib.__import__('os')\n",
    # ---- M1a.6 bypass class 3: builtins.__import__ / getattr form ----
    "builtins_import":  "import builtins\nbuiltins.__import__('os')\n",
    "getattr_builtins": "import builtins\ngetattr(builtins, '__import__')('os')\n",
    "getattr_builtins2": "import builtins\ngetattr(builtins, 'eval')('1+1')\n",
    # ---- M1b.1 fix: __builtins__[...] subscript bypass ----
    "builtins_subscript_eval":  "__builtins__['eval']('x')\n",
    "builtins_subscript_exec":  "builtins['exec']('x=1')\n",
    # ---- M1b.1 fix: multi-hop alias (two-hop chain) ----
    "alias_multihop_eval":  "fn1 = eval\nfn2 = fn1\nfn2('x')\n",
    "alias_multihop_os":    "import os\ng1 = os.system\ng2 = g1\ng2('cmd')\n",
}


@pytest.mark.parametrize("name,src", list(DANGEROUS_SNIPPETS.items()))
def test_dangerous_call_rejected(name: str, src: str) -> None:
    """Every snippet in the table must produce at least one rejection reason."""
    reasons = scan_ast_dangerous(src)
    assert reasons, f"{name!r} should be rejected but scan_ast_dangerous returned []"


# ---------------------------------------------------------------------------
# Legitimate code must NOT be rejected (no false positives)
# ---------------------------------------------------------------------------

def test_clean_function_passes() -> None:
    src = "def add(a, b):\n    return a + b\n"
    assert scan_ast_dangerous(src) == []


def test_clean_class_passes() -> None:
    src = (
        "class Foo:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "    def bar(self):\n"
        "        return self.x\n"
    )
    assert scan_ast_dangerous(src) == []


def test_os_path_passes() -> None:
    """os.path.join is safe and must not be blocked."""
    src = "import os\nresult = os.path.join('a', 'b')\n"
    assert scan_ast_dangerous(src) == []


def test_from_os_path_import_join_passes() -> None:
    """from os.path import join is safe."""
    src = "from os.path import join\np = join('a', 'b')\n"
    assert scan_ast_dangerous(src) == []


def test_default_allow_imports_pass() -> None:
    """Modules in DEFAULT_IMPORT_ALLOW should be accepted without explicit allow."""
    src = (
        "import re\nimport json\nimport math\n"
        "import pathlib\nimport datetime\nimport ast\n"
    )
    assert scan_ast_dangerous(src) == []


# ---------------------------------------------------------------------------
# Import whitelist behaviour
# ---------------------------------------------------------------------------

def test_import_default_deny_non_whitelist() -> None:
    """pandas is not in DEFAULT_IMPORT_ALLOW → rejected by default."""
    assert scan_ast_dangerous("import pandas as pd\n")


def test_import_explicit_allow_passes() -> None:
    """Explicit allow_imports overrides the deny."""
    assert scan_ast_dangerous("import pandas as pd\n", allow_imports={"pandas"}) == []


def test_import_dangerous_module_prefix_hard_blocked() -> None:
    """Even if the caller whitelists subprocess, the import must be rejected."""
    reasons = scan_ast_dangerous("import subprocess\n", allow_imports={"subprocess"})
    assert reasons, "subprocess should be hard-blocked"


# ---------------------------------------------------------------------------
# Sandbox-escaping open() checks
# ---------------------------------------------------------------------------

def test_sandbox_outside_open_rejected() -> None:
    src = "open('C:/Windows/system32/x.txt', 'w')\n"
    reasons = scan_ast_dangerous(
        src,
        sandbox_root="C:/sbx",
        target_path="C:/sbx/tools/sie/patch.py",
    )
    assert any("open" in r for r in reasons), f"Expected open rejection, got: {reasons}"


def test_sandbox_inside_open_relative_allowed() -> None:
    """Relative path resolves inside sandbox — should pass."""
    src = "open('data.txt', 'r')\n"
    reasons = scan_ast_dangerous(
        src,
        sandbox_root="C:/sbx",
        target_path="C:/sbx/tools/sie/patch.py",
    )
    assert reasons == [], f"Unexpected rejection: {reasons}"


def test_open_no_sandbox_passes() -> None:
    """open() with no sandbox_root configured should not trigger sandbox check."""
    src = "open('anything.txt', 'r')\n"
    assert scan_ast_dangerous(src) == []


# ---------------------------------------------------------------------------
# apply_patch integration test
# ---------------------------------------------------------------------------

def test_apply_patch_rejects_dangerous(tmp_path) -> None:
    """apply_patch must reject a file containing subprocess.run before writing it."""
    wt = str(tmp_path)
    os.makedirs(os.path.join(wt, "tools", "sie"), exist_ok=True)
    patch_result = apply_patch(
        wt,
        "tools/sie/x.py",
        "import subprocess\nsubprocess.run(['ls'])\n",
    )
    assert patch_result["status"] == "REJECT", f"Expected REJECT, got: {patch_result}"
    assert "subprocess" in patch_result["reason"], patch_result["reason"]
    # File must NOT have been written.
    assert not os.path.exists(os.path.join(wt, "tools", "sie", "x.py"))


def test_apply_patch_rejects_alias_bypass(tmp_path) -> None:
    """apply_patch must reject alias bypass (fn = eval; fn()) via scan_ast_dangerous."""
    wt = str(tmp_path)
    patch_result = apply_patch(wt, "alias_test.py", "fn = eval\nfn('x')\n")
    assert patch_result["status"] == "REJECT"


def test_apply_patch_rejects_importlib_bypass(tmp_path) -> None:
    """apply_patch must reject importlib.import_module bypass."""
    wt = str(tmp_path)
    src = "import importlib\nimportlib.import_module('subprocess')\n"
    patch_result = apply_patch(wt, "importlib_test.py", src)
    assert patch_result["status"] == "REJECT"


def test_apply_patch_allows_clean_file(tmp_path) -> None:
    """apply_patch must accept safe Python source."""
    wt = str(tmp_path)
    src = "import json\n\ndef load(s):\n    return json.loads(s)\n"
    patch_result = apply_patch(wt, "clean.py", src, allow={"json"})
    assert patch_result["status"] == "APPLIED", f"Unexpected rejection: {patch_result}"
    assert os.path.isfile(os.path.join(wt, "clean.py"))


# ---------------------------------------------------------------------------
# M1b.1: No false positives, common method names on safe receivers must pass
# ---------------------------------------------------------------------------

def test_client_get_passes() -> None:
    """client.get('/url') — 'get' on arbitrary receiver must NOT be rejected."""
    src = "result = client.get('/users')\n"
    assert scan_ast_dangerous(src) == [], f"client.get should pass: {scan_ast_dangerous(src)}"


def test_db_run_passes() -> None:
    """db.run(q) — 'run' on arbitrary receiver must NOT be rejected."""
    src = "db.run('SELECT 1')\n"
    assert scan_ast_dangerous(src) == [], f"db.run should pass: {scan_ast_dangerous(src)}"


def test_app_run_passes() -> None:
    """app.run() — 'run' on arbitrary receiver must NOT be rejected."""
    src = "app.run(debug=True)\n"
    assert scan_ast_dangerous(src) == [], f"app.run should pass: {scan_ast_dangerous(src)}"


def test_session_post_passes() -> None:
    """session.post(data) — 'post' on arbitrary receiver must NOT be rejected."""
    src = "session.post({'key': 'value'})\n"
    assert scan_ast_dangerous(src) == [], f"session.post should pass: {scan_ast_dangerous(src)}"


def test_obj_call_passes() -> None:
    """self.call(fn) — 'call' on arbitrary receiver must NOT be rejected."""
    src = "class Foo:\n    def bar(self):\n        return self.call(lambda: 1)\n"
    assert scan_ast_dangerous(src) == [], f"self.call should pass: {scan_ast_dangerous(src)}"



# ---------------------------------------------------------------------------
# M1b.1: Confirm dangerous calls are still rejected (positive/negative cross-check)
# ---------------------------------------------------------------------------

def test_subprocess_run_still_rejected() -> None:
    """subprocess.run must still be rejected via DANGEROUS_MODULE_PREFIXES."""
    reasons = scan_ast_dangerous("import subprocess\nsubprocess.run(['ls'])\n")
    assert reasons, "subprocess.run must be rejected"


def test_requests_get_still_rejected() -> None:
    """requests.get must still be rejected via DANGEROUS_MODULE_PREFIXES."""
    reasons = scan_ast_dangerous("import requests\nrequests.get('http://x')\n")
    assert reasons, "requests.get must be rejected"


def test_socket_socket_still_rejected() -> None:
    """socket.socket() must still be rejected via DANGEROUS_MODULE_PREFIXES."""
    reasons = scan_ast_dangerous("import socket\ns = socket.socket()\n")
    assert reasons, "socket.socket() must be rejected"


def test_eval_bare_still_rejected() -> None:
    """eval('x') must still be rejected as bare dangerous builtin."""
    reasons = scan_ast_dangerous("eval('x')\n")
    assert reasons, "eval() must be rejected"


def test_builtins_subscript_eval_still_rejected() -> None:
    """__builtins__['eval']('x') must be rejected by subscript check."""
    reasons = scan_ast_dangerous("__builtins__['eval']('x')\n")
    assert reasons, "__builtins__['eval'] subscript bypass must be rejected"


def test_builtins_subscript_exec_still_rejected() -> None:
    """builtins['exec']('x') must be rejected by subscript check."""
    reasons = scan_ast_dangerous("builtins['exec']('x=1')\n")
    assert reasons, "builtins['exec'] subscript bypass must be rejected"


def test_multihop_alias_rejected() -> None:
    """Multi-hop alias fn1=eval; fn2=fn1; fn2('x') must be rejected via fixed-point taint."""
    reasons = scan_ast_dangerous("fn1 = eval\nfn2 = fn1\nfn2('x')\n")
    assert reasons, "multi-hop alias fn2=fn1 where fn1=eval must be rejected"


# ---------------------------------------------------------------------------
# M1b.1: asyncio / concurrent are no longer hard-blocked
# ---------------------------------------------------------------------------

def test_asyncio_import_passes() -> None:
    """asyncio is a normal concurrency module — must not be hard-blocked."""
    reasons = scan_ast_dangerous("import asyncio\n", allow_imports={"asyncio"})
    assert reasons == [], f"asyncio import should pass with allow: {reasons}"


def test_concurrent_import_passes() -> None:
    """concurrent.futures is a normal concurrency module — must not be hard-blocked."""
    reasons = scan_ast_dangerous(
        "import concurrent.futures\n", allow_imports={"concurrent"}
    )
    assert reasons == [], f"concurrent import should pass with allow: {reasons}"
