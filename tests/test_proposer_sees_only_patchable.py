#!/usr/bin/env python3
"""The proposer must not be shown a file the gate will refuse no matter what it writes.

The gate permanently refuses a file whose imports or calls carry capability a self-improving loop
must not edit unsupervised: subprocess, socket, importlib, a non-literal open(). That boundary is
correct and stays. What was wrong is that it was INVISIBLE to the component obliged to respect it.

Measured on a live target: 9 of its 17 core modules sit in the refused set, so more than half of all
proposals were unlandable before they were written, and the run reported STATIC_REJECT as though the
proposer kept producing unsafe changes. The first fully completed round of the harness spent itself
proposing a change to redact.py, which cannot be patched at all.

Checking the file AS IT STANDS is the right test: the gate reads content, and a proposal keeps the
imports it found. A file that cannot pass today cannot be made to pass by an edit that leaves its
subprocess call in place.
"""
from __future__ import annotations

import io
import os

import pytest

from tools.sie.backends.llm import _gather_sources, _patchable


def _mk(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(text)
    return p


@pytest.fixture()
def sandbox(tmp_path):
    r = str(tmp_path / "sb")
    os.makedirs(r)
    _mk(r, "pkg/pure.py", "from __future__ import annotations\nimport json\n\nX = 1\n")
    _mk(r, "pkg/shells_out.py", "import subprocess\n\ndef go():\n    subprocess.run(['ls'])\n")
    _mk(r, "pkg/networks.py", "import socket\n")
    _mk(r, "pkg/dynamic.py", "import importlib\n")
    _mk(r, "pkg/sibling_user.py",
        "from __future__ import annotations\nfrom pure import X\n")
    return r


# --------------------------------------------------------------------------- the filter
def test_a_capability_bearing_file_is_not_offered_to_the_proposer(sandbox):
    files = _gather_sources(sandbox)
    assert "pkg/shells_out.py" not in files
    assert "pkg/networks.py" not in files
    assert "pkg/dynamic.py" not in files


def test_a_patchable_file_is_still_offered(sandbox):
    """Over-rejection control. A filter that hid everything would starve the proposer, and an empty
    candidate set is reported the same way as a model with no ideas."""
    files = _gather_sources(sandbox)
    assert "pkg/pure.py" in files
    assert "pkg/sibling_user.py" in files, "a first-party import made the file look unpatchable"


def test_the_reason_travels_with_the_exclusion(sandbox):
    """A file dropped without a reason is the same silence this whole change is about."""
    skipped: list = []
    _gather_sources(sandbox, skipped)
    reasons = {rel: why for rel, why in skipped}
    assert "pkg/shells_out.py" in reasons
    assert "subprocess" in reasons["pkg/shells_out.py"]
    assert "gate" in reasons["pkg/shells_out.py"].lower()


def test_the_filter_never_empties_a_healthy_candidate_set(sandbox):
    files = _gather_sources(sandbox)
    assert len(files) >= 2, "the patchability filter starved the proposer"


# --------------------------------------------------------------------------- the check itself
def test_patchable_agrees_with_the_real_gate(sandbox):
    """It must call the real gates rather than re-implement their rules, or the proposer's view and
    the gate's verdict drift apart and we are back to blind proposals."""
    from tools.sie.patch import apply_patch
    for rel in ("pkg/pure.py", "pkg/shells_out.py", "pkg/networks.py", "pkg/sibling_user.py"):
        content = io.open(os.path.join(sandbox, *rel.split("/")), encoding="utf-8").read()
        ok, _why = _patchable(sandbox, rel, content)
        applied = apply_patch(sandbox, rel, content)["status"] == "APPLIED"
        assert ok == applied, f"{rel}: filter says {ok}, gate says {applied}"


def test_a_broken_check_includes_the_file_rather_than_dropping_it(sandbox, monkeypatch):
    """Fail toward showing the file. If the check itself breaks, the proposer must still get
    candidates; silently emptying the set would read as 'the model had no ideas'."""
    import tools.sie.backends.llm as L

    def boom(*a, **k):
        raise RuntimeError("gate exploded")
    monkeypatch.setattr("tools.sie.patch.import_gate", boom)
    ok, _why = L._patchable(sandbox, "pkg/pure.py", "import json\n")
    assert ok is True
