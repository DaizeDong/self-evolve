#!/usr/bin/env python3
"""PROFILE has to grade the code it was asked about, not whatever it graded first.

Found 2026-08-29 on a real target, after four separate runs all froze at tier C with
verifiability_score 0.0. That reads as "this target has no verifiable signal", and it was wrong:

    _exec_signal called make_worktree(target, base_ref, "profile_probe")

make_worktree is idempotent BY DESIGN. If the directory already holds a valid worktree it returns it
as-is, without checking that it sits at the ref it was just handed. So the first profile on a
machine created .sie/worktrees/profile_probe at whatever HEAD happened to be, and every profile
after that graded THAT code forever. Measured: the cached worktree was pinned three commits behind
at a revision whose suite fails 22 of 1083 tests, and kept reporting exit_code 1, while a fresh
worktree at the requested ref passed 1429. Four runs were adjudicated against code that had been
fixed days earlier.

The failure is the house shape one level up: a cache that is silently wrong is indistinguishable
from a measurement, and the number it produced disqualified the strongest evidence the target had.

Keying the worktree on the RESOLVED commit fixes it, and the tests below pin both halves: the name
must vary with the ref, and a moving ref must resolve before it is used as a key.
"""
from __future__ import annotations

import subprocess

import pytest

from tools.sie import profile as P


def _git(cwd, *args):
    out = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """A tiny real repo with two commits, so HEAD and HEAD~1 are genuinely different trees."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "user1@example.com")
    _git(r, "config", "user.name", "Test User")
    (r / "a.txt").write_text("one\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "first")
    (r / "a.txt").write_text("two\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "second")
    return r


# --------------------------------------------------------------------------- ref resolution
def test_resolve_ref_returns_a_full_sha_for_head(repo):
    sha = P._resolve_ref(str(repo), "HEAD")
    assert len(sha) >= 40
    assert sha == _git(repo, "rev-parse", "HEAD")


def test_resolve_ref_distinguishes_two_commits(repo):
    """The whole point: HEAD and HEAD~1 must not produce the same key."""
    assert P._resolve_ref(str(repo), "HEAD") != P._resolve_ref(str(repo), "HEAD~1")


def test_resolve_ref_raises_on_an_unknown_ref_rather_than_returning_something(repo):
    """A silent fallback here would recreate the bug: an unresolvable ref must not quietly become
    HEAD, or two different requests could share one cache slot again."""
    with pytest.raises(RuntimeError):
        P._resolve_ref(str(repo), "no-such-ref-anywhere")


def test_resolve_ref_raises_outside_a_repo(tmp_path):
    with pytest.raises(RuntimeError):
        P._resolve_ref(str(tmp_path), "HEAD")


# --------------------------------------------------------------------------- the cache key
def test_the_probe_worktree_name_varies_with_the_ref(repo, monkeypatch):
    """THE regression. Two different refs must ask for two different worktrees."""
    asked: list[tuple[str, str]] = []

    def fake_make_worktree(target, ref, name):
        asked.append((ref, name))
        return str(repo)

    monkeypatch.setattr("tools.sie.sandbox.make_worktree", fake_make_worktree)
    monkeypatch.setattr("tools.sie.probes.exec_probe.run_exec_probe",
                        lambda root: {"has_tests": False, "exit_code": None,
                                      "mutation_killed": False, "unavailable_reason": None})
    P._exec_signal(str(repo), "HEAD")
    P._exec_signal(str(repo), "HEAD~1")

    assert len(asked) == 2
    assert asked[0][1] != asked[1][1], \
        f"both refs asked for the same worktree name {asked[0][1]!r}; the stale-cache bug is back"
    assert asked[0][0] != asked[1][0], "the ref was not resolved before being passed down"


def test_the_same_ref_reuses_one_worktree(repo, monkeypatch):
    """Over-rejection control. The cache must still be a cache: probing the same commit twice must
    not create a second worktree, or every profile pays a full checkout."""
    asked: list[str] = []
    monkeypatch.setattr("tools.sie.sandbox.make_worktree",
                        lambda target, ref, name: asked.append(name) or str(repo))
    monkeypatch.setattr("tools.sie.probes.exec_probe.run_exec_probe",
                        lambda root: {"has_tests": False, "exit_code": None,
                                      "mutation_killed": False, "unavailable_reason": None})
    P._exec_signal(str(repo), "HEAD")
    P._exec_signal(str(repo), "HEAD")
    assert asked[0] == asked[1]


def test_a_moving_ref_and_its_sha_share_one_worktree(repo, monkeypatch):
    """HEAD and the sha it points at are the same tree, so they must not create two checkouts."""
    asked: list[str] = []
    monkeypatch.setattr("tools.sie.sandbox.make_worktree",
                        lambda target, ref, name: asked.append(name) or str(repo))
    monkeypatch.setattr("tools.sie.probes.exec_probe.run_exec_probe",
                        lambda root: {"has_tests": False, "exit_code": None,
                                      "mutation_killed": False, "unavailable_reason": None})
    P._exec_signal(str(repo), "HEAD")
    P._exec_signal(str(repo), _git(repo, "rev-parse", "HEAD"))
    assert asked[0] == asked[1]


# --------------------------------------------------------------------------- failures speak
def test_a_probe_that_cannot_run_says_why_instead_of_vanishing(repo, monkeypatch):
    """It used to be `except Exception: return None`, and the caller turns None into a tier
    downgrade. An infrastructure failure was therefore indistinguishable from a target that has no
    tests, which is the same clean-versus-unchecked confusion in a different costume."""
    def boom(*a, **k):
        raise OSError("disk on fire")
    monkeypatch.setattr("tools.sie.sandbox.make_worktree", boom)
    got = P._exec_signal(str(repo), "HEAD")
    assert got is not None, "the probe failure vanished"
    assert got["mutation_killed"] is False
    assert "disk on fire" in (got["unavailable_reason"] or "")
    assert "OSError" in (got["unavailable_reason"] or "")


def test_a_failed_probe_never_claims_tier_a(repo, monkeypatch):
    """Whatever shape the failure takes, it must not satisfy the A-tier condition
    (has_tests and exit_code == 0 and mutation_killed)."""
    monkeypatch.setattr("tools.sie.sandbox.make_worktree",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    got = P._exec_signal(str(repo), "HEAD")
    verifiable = bool(got.get("has_tests")) and got.get("exit_code") == 0 and got.get("mutation_killed")
    assert not verifiable
