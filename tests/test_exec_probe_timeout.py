#!/usr/bin/env python3
"""A timeout is the absence of a verdict, not a failing verdict.

Found 2026-08-28 on a real target. The exec probe hardcoded a 60 second pytest timeout and returned
exit code 1 when it expired, with the comment "timeout treated as test failure / signal unavailable".
Those are two different things and the code chose one word for both. The target had 1121 passing
tests and a warm run took 58.6 seconds, so in a cold sandbox worktree the probe expired, reported 1,
and PROFILE downgraded the target to tier C with verifiability_score 0.0. The strongest evidence that
target had was thrown away by a stopwatch, and nothing in the frozen target.json said so.

The second half is worse and was found while fixing the first: `mutation_killed = mutant_code != 0`
counted a TIMEOUT as a kill, so the grader-validity check could pass because it ran out of time
rather than because the suite caught the injected bug. A gate that passes when it did not finish
checking is the failure mode this harness exists to prevent.

These tests pin both, plus the over-rejection controls that keep the fix from being "reject
everything".
"""
from __future__ import annotations

import subprocess

import pytest

from tools.sie.probes import exec_probe as EP


# --------------------------------------------------------------------------- the timeout sentinel
def test_timeout_is_not_reported_as_a_failing_exit_code(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)
    monkeypatch.setattr(EP.subprocess, "run", boom)
    rc = EP._run_pytest("/tmp/whatever")
    assert rc == EP.TIMEOUT_CODE
    assert rc != 1, "a timeout is still masquerading as a test failure"
    assert rc not in (0, 5), "the sentinel collides with a real pytest exit code"


def test_the_sentinel_cannot_collide_with_any_pytest_exit_code():
    """pytest uses 0 through 5. A sentinel inside that range would be indistinguishable from a
    verdict, which is the whole defect."""
    assert EP.TIMEOUT_CODE not in range(0, 6)


def test_a_real_exit_code_is_passed_through_unchanged(monkeypatch):
    """Over-rejection control: the fix must not turn genuine failures into timeouts."""
    for code in (0, 1, 5):
        monkeypatch.setattr(EP.subprocess, "run",
                            lambda *a, _c=code, **k: subprocess.CompletedProcess(
                                args=[], returncode=_c, stdout="", stderr=""))
        assert EP._run_pytest("/tmp/whatever") == code


# --------------------------------------------------------------------------- the budget
def test_the_default_budget_is_large_enough_for_a_real_suite():
    """The measured target's suite takes about 59s warm and more cold. A 60s budget is not a budget,
    it is a coin flip, and losing the flip silently costs the target its strongest signal tier."""
    assert EP._timeout_s() >= 300


def test_the_budget_is_overridable(monkeypatch):
    monkeypatch.setenv("SIE_EXEC_PROBE_TIMEOUT", "42")
    assert EP._timeout_s() == 42.0


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "  "])
def test_a_malformed_budget_falls_back_to_the_default_rather_than_to_zero(monkeypatch, bad):
    """Falling back to 0 or to a tiny value would reintroduce the bug through a typo."""
    monkeypatch.setenv("SIE_EXEC_PROBE_TIMEOUT", bad)
    assert EP._timeout_s() >= 300


# --------------------------------------------------------------------------- mutation validity
def test_a_timed_out_mutation_run_is_not_counted_as_a_kill(monkeypatch, tmp_path):
    """THE dangerous one. `mutant_code != 0` would call a timeout a kill, so grader validity could be
    established by giving up rather than by catching the injected bug."""
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")

    calls = {"n": 0}

    def fake(root):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else EP.TIMEOUT_CODE   # baseline green, mutant times out

    monkeypatch.setattr(EP, "_run_pytest", fake)
    out = EP.run_exec_probe(str(tmp_path))
    assert out["exit_code"] == 0
    assert out["mutation_killed"] is False, "a timeout was counted as proof the suite catches bugs"
    assert "TIMED OUT" in (out["unavailable_reason"] or "")


def test_a_genuinely_killed_mutant_is_still_a_kill(monkeypatch, tmp_path):
    """Over-rejection control: the fix must not stop real kills from registering."""
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    calls = {"n": 0}

    def fake(root):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 1                 # baseline green, mutant red
    monkeypatch.setattr(EP, "_run_pytest", fake)
    out = EP.run_exec_probe(str(tmp_path))
    assert out["mutation_killed"] is True
    assert out["unavailable_reason"] is None


def test_a_mutant_that_stays_green_is_not_a_kill_and_says_why(monkeypatch, tmp_path):
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(EP, "_run_pytest", lambda root: 0)
    out = EP.run_exec_probe(str(tmp_path))
    assert out["mutation_killed"] is False
    assert "GREEN" in (out["unavailable_reason"] or "")


# --------------------------------------------------------------------------- the reason is reported
def test_a_timed_out_baseline_says_it_timed_out_rather_than_looking_broken(monkeypatch, tmp_path):
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(EP, "_run_pytest", lambda root: EP.TIMEOUT_CODE)
    out = EP.run_exec_probe(str(tmp_path))
    assert out["exit_code"] == EP.TIMEOUT_CODE
    reason = out["unavailable_reason"] or ""
    assert "TIMED OUT" in reason and "SIE_EXEC_PROBE_TIMEOUT" in reason


def test_a_failing_baseline_says_it_failed_not_that_it_timed_out(monkeypatch, tmp_path):
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(EP, "_run_pytest", lambda root: 1)
    out = EP.run_exec_probe(str(tmp_path))
    assert "TIMED OUT" not in (out["unavailable_reason"] or "")
    assert "exited 1" in (out["unavailable_reason"] or "")


def test_no_tests_says_so(tmp_path):
    out = EP.run_exec_probe(str(tmp_path))
    assert out["has_tests"] is False
    assert "no test files" in (out["unavailable_reason"] or "")


def test_a_healthy_probe_reports_no_reason(monkeypatch, tmp_path):
    """The field must stay None on the happy path, or "why not tier A" becomes noise nobody reads."""
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    calls = {"n": 0}

    def fake(root):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 1
    monkeypatch.setattr(EP, "_run_pytest", fake)
    out = EP.run_exec_probe(str(tmp_path))
    assert out["unavailable_reason"] is None
    assert out["mutation_killed"] is True
