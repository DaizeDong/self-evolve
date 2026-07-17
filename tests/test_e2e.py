"""
End-to-end tests for M1a statemachine + cli.

Covers:
  - test_select_parent_cold_start: archive empty -> "base"
  - test_e2e_accept_and_rollback: full loop with _injected_fix -> ACCEPT + rollback
  - test_e2e_crash_replay_consistent: delete state.json, replay from events must be identical
  - test_cli_full_flow: init|run|status|replay via cli.main

M1b.3 note: e-process replaces no-regression gate as primary decision rule.
  For ACCEPT, the profiler must assign tier A (baseline tests all green + mutation killed),
  and the fix must produce enough (before, after) pairs to reach e-value >= 1/α=20.
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
    """Repo with a correct add() and a buggy mul() — but ONLY add tests in baseline.

    M1b.3 e-process design:
    - Baseline tests: 3 add() tests — all PASS -> profiler sees green -> tier A.
    - After injected fix (mul returns a*b), the grader runs ALL tests including
      the 15 mul tests that are now in the test file (injected alongside the fix).
    - BUT: injected_fix only patches mod.py, not test_mod.py.
      So the mul tests must already be in test_mod.py at baseline time.

    Problem: if mul tests are in test_mod.py at baseline, they fail -> tier C.

    Solution: use a repo where baseline is fully green. The "fix" rewrites the
    file to correct a subtle bug that only causes failures under specific inputs.
    Those specific inputs are already tested in test_mod.py and currently FAIL
    because of the bug — but wait, that means baseline is red again.

    REAL SOLUTION: use pytest's parametrize + xfail to have tests that are
    expected-to-fail in baseline (xfail) and become PASS after the fix. But
    xfail tests still count as "passed" for exit_code purposes.

    Simplest correct approach: baseline has ONLY add() tests (all pass -> tier A).
    After the fix is applied (which replaces mod.py content with add+mul),
    evaluate uses base_result=None so before=0.0 for all dims. But we only have
    the 3 add tests... not enough signal.

    ACTUAL fix: generate 15 add tests in baseline (all pass -> tier A), then
    the fix is a refactoring of add() that still passes all tests. But that
    gives all diff=0 -> wealth=1 -> REJECT.

    THE FINAL ANSWER: for e2e ACCEPT test, the evaluate baseline (base_result=None)
    gives before=0.0 for all dims. After fix that makes all N tests pass, we get
    N pairs of (0.0, 1.0) — all improvements. With N=15, wealth >> 20 -> ACCEPT.
    This works IF the baseline tests all PASS (tier A). The "fix" corrects a bug
    in a secondary function that was broken in baseline.

    We achieve this by having the baseline already run with ONLY the secondary
    function's tests failing — wait, that's tier C again.

    CLEAN SOLUTION: separate pass/fail with xfail marks.
    """
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)

    # Baseline: add() is CORRECT, mul() is buggy.
    # Tests: 3 add tests (pass) + 15 mul tests marked @pytest.mark.xfail (expected fail).
    # pytest exit_code=0 even when xfail tests fail (they are expected to fail).
    # After fix: mul() becomes correct, xfail tests unexpectedly PASS -> xpass.
    # xpass = "unexpected pass" = score 1.0 in our binary grader (exit_code still 0).
    (r / "mod.py").write_text(
        "def add(a, b):\n    return a + b\n"
        "def mul(a, b):\n    return a - b  # BUG: should be a*b\n"
    )

    add_tests = "\n".join(
        f"def test_add_{i}():\n    assert add({i}, {i+1}) == {2*i+1}\n"
        for i in range(1, 4)
    )
    # xfail: expected to fail in baseline; xpass (unexpectedly pass) after fix.
    # strict=False: xpass is treated as a pass (exit_code=0), score=1.0.
    mul_tests = "\n".join(
        f"@pytest.mark.xfail(strict=False, reason='mul bug')\n"
        f"def test_mul_{i}():\n    assert mul({i}, {i+1}) == {i*(i+1)}\n"
        for i in range(1, 16)
    )
    test_src = f"import pytest\nfrom mod import add, mul\n\n{add_tests}\n{mul_tests}"
    (r / "test_mod.py").write_text(test_src)

    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    return str(r)


# ---------------------------------------------------------------------------
# Step 1 tests, these should FAIL before statemachine.py exists
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
    # Fix mul() so 15 xfail mul tests become xpass (unexpected pass) -> score=1.0
    fix = "def add(a, b):\n    return a + b\ndef mul(a, b):\n    return a * b\n"
    summary = run_loop(
        tgt, "HEAD", "rune2e", max_rounds=2, mode="auto",
        _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                       "target_failure": "mul a-b should be a*b"},
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
    fix = "def add(a, b):\n    return a + b\ndef mul(a, b):\n    return a * b\n"
    run_loop(
        tgt, "HEAD", "runcrash", max_rounds=1, mode="auto",
        _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                       "target_failure": "fix mul"},
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
# Step 4 tests, CLI flow
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
