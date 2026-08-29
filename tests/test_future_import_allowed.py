#!/usr/bin/env python3
"""The import gate must not refuse the language itself.

Measured 2026-08-29 on a real target. Every proposal in every round of four separate runs was
refused at the PATCH gate with:

    AST gate: import not in whitelist: __future__

`from __future__ import annotations` opens 27 of that target's 80 source files, including every file
the proposer wanted to touch, so no patch could ever be applied and the harness reported eight
rounds of static rejection. It was not declining bad changes; it was declining modern Python.

Allowing it is safe on its own terms, and that is worth pinning rather than asserting: `__future__`
is a compile-time directive, not a capability. It changes how the parser treats the module and
exposes nothing that can execute, read a file or open a socket. The whole importable surface is a
handful of feature flags plus a `_Feature` record.

These tests pin that the gate accepts it, that accepting it did not soften anything else, and that a
patch which merely happens to contain the line is still judged on its real content.
"""
from __future__ import annotations

import pytest

from tools.sie.patch import DEFAULT_IMPORT_ALLOW, import_gate


def test_future_is_in_the_default_allow_set():
    assert "__future__" in DEFAULT_IMPORT_ALLOW


def test_the_exact_line_that_blocked_every_patch_is_accepted():
    ok, why = import_gate("from __future__ import annotations\n\nX = 1\n", None)
    assert ok, why


@pytest.mark.parametrize("src", [
    "from __future__ import annotations\nimport json\n",
    "from __future__ import annotations\nfrom typing import Any\n\ndef f(x: Any) -> Any:\n    return x\n",
    "from __future__ import annotations, division\n",
])
def test_realistic_module_headers_pass(src):
    ok, why = import_gate(src, None)
    assert ok, why


# --------------------------------------------------------------------------- nothing else loosened
@pytest.mark.parametrize("bad,needle", [
    ("from __future__ import annotations\nimport subprocess\n", "subprocess"),
    ("from __future__ import annotations\nimport socket\n", "socket"),
    ("from __future__ import annotations\nimport ctypes\n", "ctypes"),
    ("from __future__ import annotations\nimport importlib\n", "importlib"),
    ("from __future__ import annotations\nimport urllib.request\n", "urllib"),
])
def test_a_future_header_does_not_smuggle_a_dangerous_import_past_the_gate(bad, needle):
    """The gate walks the whole tree, so an allowed first line must not act as a pass for the rest.
    This is the over-rejection control inverted: proving the fix did not become a hole."""
    ok, why = import_gate(bad, None)
    assert not ok
    assert needle in why


def test_an_unlisted_ordinary_module_is_still_refused():
    ok, why = import_gate("from __future__ import annotations\nimport yaml\n", None)
    assert not ok
    assert "yaml" in why


def test_a_syntax_error_is_still_refused():
    ok, why = import_gate("from __future__ import annotations\ndef (:\n", None)
    assert not ok
    assert "syntax" in why.lower()


def test_future_is_a_directive_not_a_capability():
    """The justification for allowing it, asserted rather than assumed. Nothing importable from
    __future__ is callable, so there is no dangerous symbol for the gate to have to catch."""
    import __future__ as fut
    exported = [n for n in dir(fut) if not n.startswith("_")]
    assert exported, "sanity: __future__ exports its feature flags"
    for name in exported:
        obj = getattr(fut, name)
        assert not callable(obj), f"__future__.{name} is callable, so this justification is wrong"


# --------------------------------------------------------------------------- the two lists again
# `__future__` was one symptom; this is the mechanism. apply_patch's docstring has always said it
# uses "DEFAULT_IMPORT_ALLOW | allow_imports", and it did not: `allow` arrives as None from the
# state machine, so import_gate fell back to _DEFAULT_ALLOW, a narrower list. Measured 2026-08-29 on
# a real target, 42 files import sys and 32 import os, so almost nothing was patchable and the runs
# reported static rejection as though the proposals were unsafe.
import os as _os
import tempfile as _tempfile

from tools.sie.patch import _DEFAULT_ALLOW, apply_patch


def _sandbox():
    d = _tempfile.mkdtemp(prefix="sie-patch-test-")
    return d


@pytest.mark.parametrize("mod", sorted(set(DEFAULT_IMPORT_ALLOW) - set(_DEFAULT_ALLOW)))
def test_every_documented_module_is_actually_patchable(mod):
    """The gap between the documented list and the effective one, asserted module by module so a
    future divergence names the module it broke."""
    sb = _sandbox()
    res = apply_patch(sb, "m.py", "from __future__ import annotations\nimport %s\n" % mod)
    assert res["status"] == "APPLIED", f"{mod} is documented as allowed but was rejected: {res}"


def test_the_measured_failure_reproduces_as_a_pass_now():
    """The literal rejection seen in the run: 'import not in whitelist: hashlib' on a file that has
    always imported hashlib."""
    sb = _sandbox()
    src = "from __future__ import annotations\nimport hashlib\n\ndef k(s: str) -> str:\n    return hashlib.sha256(s.encode()).hexdigest()[:16]\n"
    res = apply_patch(sb, "skills/x/scripts/lib.py", src)
    assert res["status"] == "APPLIED", res
    assert _os.path.isfile(_os.path.join(sb, "skills", "x", "scripts", "lib.py"))


@pytest.mark.parametrize("mod", ["subprocess", "socket", "ctypes", "multiprocessing"])
def test_danger_modules_are_still_refused_even_though_the_list_widened(mod):
    """The over-rejection control inverted. Widening the allow list must not widen the danger
    surface; _DANGER_MODULES is refused even when a caller whitelists it."""
    sb = _sandbox()
    res = apply_patch(sb, "m.py", "import %s\n" % mod)
    assert res["status"] == "REJECT"
    assert mod in res["reason"]


def test_an_undocumented_module_is_still_refused():
    sb = _sandbox()
    res = apply_patch(sb, "m.py", "import yaml\n")
    assert res["status"] == "REJECT"
    assert "yaml" in res["reason"]


def test_dangerous_calls_are_still_refused():
    sb = _sandbox()
    res = apply_patch(sb, "m.py", "import os\neval('1+1')\n")
    assert res["status"] == "REJECT"
