"""The A-tier gate must be able to REJECT something the loop could actually hand it.

WHY THIS FILE EXISTS. Four calibration runs put 22 proposals through the acceptor and produced ZERO
REJECT events. The reflectors noticed on their own and said so: "6 rounds all accepted with no
failures, the sample has no counterexample, so there is no way to tell whether the eval gate
discriminates or is merely decorative."

They were right, and the mechanism is not subtle. run_loop calls
`evaluate(sandbox_root, prof["tier"], base_result=None)` with the baseline HARDCODED to None, so the
A-tier path always takes its cold-start branch, where `before = 0.0` for every task. Two things
follow, and both were measured, not reasoned:

  1. Every passing test in the target scores as an improvement over a "everything failed" baseline,
     so with 1160 tests the e-value is literally inf and ACCEPT is unconditional.
  2. The no-regression hard gate tests `before >= 1.0 > after`. With before pinned at 0.0 that is
     never true, so the hard gate cannot fire at all. A proposal that turns three tests RED was
     measured at e-value inf and ACCEPT.

The acceptor itself is fine. tests/test_acceptor.py drives `decide()` with hand written pairs and
covers the hard gate and the e-process carefully, and all of it passes. What nothing covered was
what the production path FEEDS it. That is the fourth time in this codebase that a gate was correct
in its unit test and inert in production because the test supplied its own input.

These tests are written against the shape the loop produces. They were the specification of the
fix, and now they guard it.
"""
from __future__ import annotations

import inspect

import pytest

from tools.sie.acceptor import decide
from tools.sie.state import RunState
from tools.sie.statemachine import run_loop


def _st():
    return RunState(run_id="r", phase="JUDGE", round=1, parent_vid=None, tier="A")


P = {"alpha": 0.05}


def test_the_cold_start_baseline_makes_the_gate_unconditional():
    """Characterization, and the reason the rest of this file exists. Documents today's behavior."""
    cold = [(0.0, 1.0)] * 1160
    d = decide(cold, "A", _st(), P)
    assert d["decision"] == "ACCEPT"
    assert d["evalue"] == float("inf"), (
        "a 'nothing passed before' baseline should make every green test read as an improvement; "
        "if this no longer holds the analysis behind this file needs redoing")


def test_a_proposal_that_turns_tests_red_is_accepted_under_a_cold_baseline():
    """The damage. Same shape, three tasks regressed, and the hard gate cannot see them."""
    bad = [(0.0, 1.0)] * 1157 + [(0.0, 0.0)] * 3
    d = decide(bad, "A", _st(), P)
    assert d["decision"] == "ACCEPT", "behavior changed; re-read this file's docstring"
    # The hard gate needs before >= 1.0 to fire, and a cold baseline never supplies it.
    regressed = [i for i, (b, a) in enumerate(bad) if b >= 1.0 > a]
    assert regressed == [], "the hard gate could fire here; the cold-start analysis is wrong"


def test_the_hard_gate_does_fire_when_the_baseline_is_real():
    """The acceptor is not the defect. Given a truthful before/after it refuses immediately."""
    real = [(1.0, 1.0)] * 1157 + [(1.0, 0.0)] * 3
    d = decide(real, "A", _st(), P)
    assert d["decision"] == "REJECT"
    assert "no-regression" in d["reason"]


def test_the_loop_threads_a_real_baseline_into_evaluate():
    """THE LOAD BEARING TEST. Reads the call site, because the defect was IN the call site.

    This was a strict xfail while the defect stood. When the fix landed, pytest reported XPASS as a
    failure and forced the marker off, which is the point of strict: a repaired defect does not get
    to keep a "known broken" label.
    """
    src = inspect.getsource(run_loop)
    assert "base_result=None" not in src, (
        "run_loop is back to hardcoding base_result=None, so the A-tier acceptor sees an "
        "'everything failed' baseline again and cannot reject anything")
    assert "_parent_baseline(run_dir, parent)" in src, (
        "the A-tier evaluate call no longer passes the parent's scores as its baseline")


def test_the_parent_baseline_resolves_from_the_lineage(tmp_path):
    """The fix reads the parent's stored scores. Driven through the real archive writer, not a
    hand built dict, because the shape it has to match is archive.add_version's, not mine."""
    from tools.sie import archive
    from tools.sie.statemachine import _parent_baseline

    run_dir = str(tmp_path / "run")
    dims = [{"name": "tests/test_a.py::test_one", "tier": "A", "score": 1.0, "weight": 1.0},
            {"name": "tests/test_a.py::test_two", "tier": "A", "score": 0.0, "weight": 1.0}]
    archive.add_version(run_dir, "v1", dims, "base")

    assert _parent_baseline(run_dir, "base") is None, "a genuine cold start has no parent"
    assert _parent_baseline(run_dir, "v9") is None, "an unknown parent must not invent a baseline"
    got = _parent_baseline(run_dir, "v1")
    assert got and [d["score"] for d in got["dimensions"]] == [1.0, 0.0]


def test_a_real_baseline_lets_the_hard_gate_see_a_regression(tmp_path):
    """End to end in miniature: parent scores -> paired -> decide REJECTS.

    The cold-start baseline could not express a regression at all, so this is the whole point of
    the change stated as one assertion.
    """
    from tools.sie import archive
    from tools.sie.statemachine import _parent_baseline

    run_dir = str(tmp_path / "run")
    dims = [{"name": "t::%d" % i, "tier": "A", "score": 1.0, "weight": 1.0} for i in range(20)]
    archive.add_version(run_dir, "v1", dims, "base")
    base = _parent_baseline(run_dir, "v1")

    after = [1.0] * 17 + [0.0] * 3          # three tests went red
    paired = [(float(base["dimensions"][i]["score"]), after[i]) for i in range(20)]
    d = decide(paired, "A", _st(), P)
    assert d["decision"] == "REJECT" and "no-regression" in d["reason"], (
        "with a truthful baseline the hard gate must refuse a proposal that turns tests red; "
        "got %r" % (d,))

def test_round_one_falls_back_to_the_base_ref_worktree(tmp_path):
    """Round 1 has no parent version, but it does have the base ref, and that is a real baseline.

    Measured, not theorized: the first run with a real baseline accepted exactly one change, in
    round 1 while parent was still "base", and that change broke bandit.py's cold-arm exploration.
    The target's own suite caught it after the fact (1 failed, 1159 passed). Rounds 2 through 10,
    with v1 as parent, rejected all eight proposals. The gate worked everywhere it had something to
    compare against; round 1 was the single window where it still could not refuse anything.
    """
    from tools.sie.statemachine import _base_ref_worktree

    run_dir = tmp_path / "t" / ".sie" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    wt = tmp_path / "t" / ".sie" / "worktrees"
    wt.mkdir(parents=True)
    assert _base_ref_worktree(str(run_dir)) is None, "no probe worktree yet, so no baseline"

    (wt / "r1").mkdir()                                   # the run's own sandbox, not a probe
    assert _base_ref_worktree(str(run_dir)) is None, "only profile_probe_* may serve as a baseline"

    probe = wt / "profile_probe_deadbeef1234"
    probe.mkdir()
    assert _base_ref_worktree(str(run_dir)) == str(probe)


def test_a_missing_probe_worktree_degrades_instead_of_raising(tmp_path):
    """Readers may degrade. A baseline we cannot build is round 1's old behavior, not a dead run."""
    from tools.sie.statemachine import _parent_baseline

    run_dir = tmp_path / "t" / ".sie" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    assert _parent_baseline(str(run_dir), "base") is None
