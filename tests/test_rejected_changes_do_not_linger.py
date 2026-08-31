"""A refused proposal must not stay on the sandbox tree.

WHY. run_loop had no rollback at all. A REJECT wrote its event, incremented no_progress, and moved
on with the refused edits still in the sandbox; the next round then reflected, proposed and
evaluated on top of them. "Rejected" did not mean "this change does not stay", it meant "this change
gets no version number".

It stayed invisible for five calibration runs because the A-tier gate was accepting unconditionally
and never rejected anything. Repairing that gate is what exposed this: the next run accepted ZERO
proposals across 11 rounds and left 330 changed lines across five files in its sandbox. The
calibration harness, which grades the sandbox, scored those refused edits as 6 of 21 defects
repaired, a number produced entirely by changes the loop had rejected.

The spec is silent (docs/pipeline.md 态9 says only "拒绝本轮, no_progress++" and nothing about the
tree), so discarding is a judgement call: A-tier is two-state with CONTINUE forbidden, which makes
REJECT terminal, and select_parent already points the next round at the lineage tail.
"""
from __future__ import annotations

import inspect
import subprocess

from tools.sie.statemachine import _discard_rejected_changes, run_loop


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=", *args], cwd=cwd,
                          capture_output=True, text=True)


def test_a_rejected_edit_is_restored(tmp_path):
    """The load bearing behavior, driven through a real git worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    f = repo / "mod.py"
    f.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base")

    f.write_text("VALUE = 999  # a proposal the acceptor refused\n", encoding="utf-8")
    assert "999" in f.read_text(encoding="utf-8")

    _discard_rejected_changes(str(repo))
    assert f.read_text(encoding="utf-8") == "VALUE = 1\n", (
        "the refused edit survived; the next round would build on a change the evidence rejected")


def test_an_accepted_commit_is_not_touched(tmp_path):
    """NEGATIVE CONTROL. Discarding must only drop UNCOMMITTED work. If it could reach committed
    state it would undo accepted versions, which is far worse than the defect it fixes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    f = repo / "mod.py"
    f.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base")
    f.write_text("VALUE = 2  # accepted and committed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "v1")

    _discard_rejected_changes(str(repo))
    assert "VALUE = 2" in f.read_text(encoding="utf-8"), "an accepted, committed change was undone"


def test_a_missing_or_bogus_sandbox_degrades_quietly(tmp_path):
    """Readers may degrade. This is called on a rejection path; it must never take out the run.
    A test that drives run_loop with a stub root hit exactly this and raised NotADirectoryError."""
    _discard_rejected_changes(str(tmp_path / "does-not-exist"))
    _discard_rejected_changes("")
    _discard_rejected_changes(str(tmp_path))          # a real dir that is not a git repo


def test_every_reject_site_discards(tmp_path):
    """Four sites emit REJECT. Fixing three of them leaves the same symptom, so each is checked in
    its own window rather than by a total count that accept branches could pad."""
    src = inspect.getsource(run_loop)
    lines = src.split("\n")
    sites = [i for i, l in enumerate(lines) if '"type": "REJECT",' in l]
    assert len(sites) >= 4, "expected the four REJECT sites; found %d" % len(sites)
    for i in sites:
        window = "\n".join(lines[max(0, i - 8):i + 2])
        assert "_discard_rejected_changes(sandbox_root)" in window, (
            "the REJECT site at run_loop line %d does not discard its refused edits:\n%s" % (i, window))
