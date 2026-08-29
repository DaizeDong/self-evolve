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
