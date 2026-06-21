"""
End-to-end tests for M1a statemachine + cli.

Covers:
  - test_select_parent_cold_start: archive empty -> "base"
  - test_e2e_accept_and_rollback: full loop with _injected_fix -> ACCEPT + rollback
  - test_e2e_crash_replay_consistent: delete state.json, replay from events must be identical
  - test_cli_full_flow: init|run|status|replay via cli.main
"""
from __future__ import annotations
import os
import subprocess as sp
import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _broken_repo(tmp_path):
    """A repo where test_add fails (add returns a-b instead of a+b)."""
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "mod.py").write_text("def add(a, b):\n    return a - b\n")  # bug
    (r / "test_mod.py").write_text(
        "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    return str(r)


# ---------------------------------------------------------------------------
# Step 1 tests — these should FAIL before statemachine.py exists
# ---------------------------------------------------------------------------

def test_select_parent_cold_start(tmp_path):
    from tools.sie.statemachine import select_parent
    from tools.sie.state import RunState

    rd = str(tmp_path / "run")
    st = RunState(run_id="r", phase="SELECT", round=0, parent_vid=None, tier="A")
    assert select_parent(rd, st) == "base"  # archive empty -> base ref


def test_e2e_accept_and_rollback(tmp_path):
    from tools.sie.statemachine import run_loop
    from tools.sie import archive

    tgt = _broken_repo(tmp_path)
    fix = "def add(a, b):\n    return a + b\n"
    summary = run_loop(
        tgt, "HEAD", "rune2e", max_rounds=2, mode="auto",
        _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                       "target_failure": "add a-b should be a+b"},
    )
    assert summary["accepted_versions"], summary

    arch = os.path.join(tgt, ".sie", "runs", "rune2e", "archive")
    lin = archive.lineage(arch)
    assert lin, "lineage should have at least one accepted version"

    # Rollback to first accepted version
    vid = lin[0]["vid"]
    archive.rollback(arch, vid)
    assert os.path.isdir(os.path.join(arch, "current"))


def test_e2e_crash_replay_consistent(tmp_path):
    from tools.sie.statemachine import run_loop
    from tools.sie.state import load_state
    from tools.sie.events import replay

    tgt = _broken_repo(tmp_path)
    fix = "def add(a, b):\n    return a + b\n"
    run_loop(
        tgt, "HEAD", "runcrash", max_rounds=1, mode="auto",
        _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                       "target_failure": "fix add"},
    )
    run_dir = os.path.join(tgt, ".sie", "runs", "runcrash")
    saved = load_state(run_dir)
    # Simulate crash: delete state.json
    os.remove(os.path.join(run_dir, "state.json"))
    # Replay from events.jsonl must produce identical state
    rebuilt = replay(run_dir)
    # The crash-replay hard invariant: rebuilt == saved
    assert rebuilt == saved, (
        f"Crash replay inconsistent!\nsaved={saved}\nrebuilt={rebuilt}"
    )


# ---------------------------------------------------------------------------
# Step 4 tests — CLI flow
# ---------------------------------------------------------------------------

def test_cli_full_flow(tmp_path, capsys):
    from tools.sie.cli import main as cli_main

    tgt = _broken_repo(tmp_path)

    assert cli_main(["init", "--target", tgt, "--run-id", "cli1"]) == 0
    capsys.readouterr()  # clear

    # run without injected fix: builtin produces nothing -> no ACCEPT, but loop completes
    assert cli_main(["run", "--target", tgt, "--run-id", "cli1",
                     "--base-ref", "HEAD", "--max-rounds", "1"]) == 0
    capsys.readouterr()  # clear

    assert cli_main(["status", "--target", tgt, "--run-id", "cli1"]) == 0
    out = capsys.readouterr().out
    assert "phase" in out

    assert cli_main(["replay", "--target", tgt, "--run-id", "cli1"]) == 0
    rout = capsys.readouterr().out
    assert "run_id" in rout
