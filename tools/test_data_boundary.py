#!/usr/bin/env python3
"""Negative controls for tools/data_boundary.py -- the gate that had none.

WHY THIS FILE EXISTS
--------------------
data_boundary.py shipped as a CI job (.github/workflows/pii-guard.yml) and as both git hooks
(.githooks/pre-commit, .githooks/pre-push), and it is called the PRIMARY control in every document
in this fleet. Nothing had ever made it go red. That is not a paperwork gap, it is the same defect
the file's own docstring names: measured on 2026-08-27, its RUN_SHAPES patterns matched 0 of the
116 files one real daily run of this skill writes, so it printed "clean" every day while asserting
nothing about the one thing it exists to catch. A gate whose green nobody has ever contradicted is
indistinguishable from a gate that cannot speak.

So every check below is written as a POISONED REPO: a scratch work tree constructed to violate one
rule, run through the real script, asserting a nonzero exit AND that the offending path is named in
the output. Naming matters as much as the exit code; "1 violation(s)" with no path is a verdict
nobody can act on, and it would also pass a test that only looked at the return code.

Paired with each of those is an OVER-REJECTION control: the same scratch repo without the poison
must exit 0. A gate that is always red is as useless as one that is always green, and it is the
easier of the two to write by accident.

WHAT IS SYNTHETIC HERE
----------------------
Every filename below is a SHAPE this skill's pipeline really produces, reconstructed by hand. The
per-handle and per-subreddit shards in a real run tree are named after actual accounts and actual
subreddits, so those names are replaced with the synthetic namespace (example-handle-N,
r/example-*). The shape is the thing under test; the names inside it are nobody's business, and a
test fixture is the last place a real one should be recovered from.

Stdlib + pytest only. No network, no gh, no real repos: every repo here is built in tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "data_boundary.py")
REPO_ROOT = os.path.dirname(HERE)

# Exit codes this gate promises. They are asserted by name so that collapsing two of them together
# breaks a test instead of quietly making "nothing was examined" look like "clean".
CLEAN = 0
VIOLATION = 1
NOT_EXAMINED = 2   # git unusable, or an empty file list: the scan did not happen
NOT_ARMED = 3      # no manifest, or --companion with no companion: nothing was declared to enforce

# The exact prefix of the success summary. Asserted as a whole string so that a refusal is free
# to use the word "clean" in a sentence explaining that this is NOT one.
PASS_LINE = "data_boundary: clean ("

AUDITED = "synthetic test manifest -- this repo writes nothing, which is why the list is empty"


def git(repo, *args):
    """Run git in `repo` with the machine's own config kept OUT of the way.

    GIT_CONFIG_GLOBAL / GIT_CONFIG_NOSYSTEM matter: this machine sets a global core.hooksPath that
    installs an identity assertion and a PII scan on every commit. A test that tripped those would
    fail for reasons that have nothing to do with the gate under test, and worse, could pass for
    them too.
    """
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.path.join(str(repo), ".absent-global-gitconfig")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    assert p.returncode == 0, "git %s failed in %s:\n%s" % (" ".join(args), repo, p.stderr)
    return p.stdout


def run_guard(repo, *args, env_extra=None, path=None):
    """Invoke the real script exactly as CI and the hooks do, and return (rc, combined output)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if path is not None:
        env["PATH"] = path
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([sys.executable, GUARD, "--repo", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make_repo(tmp_path, name="scratch", files=None, manifest=None, track=True, remote=None):
    """A git work tree containing `files` (path -> text), with `manifest` written as .dataclass.json.

    `track=True` stages everything with --force, because the poison is often a path a real repo
    would gitignore and .gitignore is advisory: `git add -f` is precisely the move this gate exists
    to survive.
    """
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    if manifest is not None:
        (repo / ".dataclass.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    for rel, text in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    if remote is not None:
        git(repo, "remote", "add", "origin", remote)
    if track:
        git(repo, "add", "-A", "--force")
    return repo


def base_manifest(**over):
    m = {"data": [], "data_sealed": [], "fixture": [], "tool": [], "_audited": AUDITED}
    m.update(over)
    return m


def assert_not_a_pass(out):
    """The success SUMMARY line must be absent. Matching the bare word "clean" is not the same
    property: a refusal is allowed to contain the phrase "this is not a clean bill of health",
    and a test that forbids the word would push the next author toward a quieter refusal."""
    assert PASS_LINE not in out, "this run reported a pass it did not earn:\n%s" % out


def assert_blocked(rc, out, path, kind=None):
    """A verdict must carry the offending path. An exit code alone is not actionable."""
    assert rc == VIOLATION, "expected exit %d, got %d\n%s" % (VIOLATION, rc, out)
    assert path in out, "the gate blocked but never named %r:\n%s" % (path, out)
    if kind:
        assert kind in out, "expected finding kind %r in:\n%s" % (kind, out)


# ---------------------------------------------------------------------------------------------
# The shapes a REAL daily run of this skill writes. Reconstructed by hand from one run tree
# (116 files) and the live archive (40 files); the account-shaped and subreddit-shaped names are
# replaced with the synthetic namespace. Each entry is (relative path, why it is run output).
#
# The whole point of check 4 is that it catches these AT AN IN-REPO RELATIVE PATH, not only inside
# a conveniently named .run-YYYY-MM-DD/ directory. A pipeline pointed at the repo by a flag or an
# env var (--archive-dir, DAILY_HOTSPOTS_CONFIG) drops these at the root, with no dated directory
# to give them away, and that is the case the shipped pattern list missed entirely.
# ---------------------------------------------------------------------------------------------
RUN_ARTIFACTS_AT_REPO_ROOT = [
    "candidates.json",
    "sources.json",
    "sources_result.json",
    "sources_out.json",
    "result.json",
    "run_out.json",
    "roster_raw_1.json",
    "roster_shard_3.json",
    "roster_plan.json",
    "demand_cards.json",
    "supply_cards.json",
    "all_jobs.json",
    "raw_jobs.json",
    "dry.json",
    "reddit_out.json",
    "hn_out.json",
    "arxiv_out.json",
    "ph_out.json",
    "x_broad_out.json",
    "gdelt_raw.json",
    "roster.json",
    "roster-review.md",
    "opportunities.jsonl",
    "opportunities.after-interactive-run.jsonl",
    "pulls-2026-08.jsonl",
    "identity-sweep-2026-08.json",
    "dedup-state.json",
    "digests/2026/2026-08-27.md",
    "archive/opportunities.jsonl",
    "archive/pulls-2026-08.jsonl",
    "archive/dedup-state.json",
    "archive/digests/2026/2026-08-27.md",
    "archive/identity-sweep-2026-08.json",
    "archive/roster-review.md",
]

# The scratch tree a single run leaves behind, names synthesized. Every one of these is under a
# dated run directory, which is a second, independent way for the same file to be caught.
RUN_TREE = [
    ".run-2026-08-27/candidates.json",
    ".run-2026-08-27/sources.json",
    ".run-2026-08-27/result.json",
    ".run-2026-08-27/demand_cards.json",
    ".run-2026-08-27/roster_raw_1.json",
    ".run-2026-08-27/run_err.txt",
    ".run-2026-08-27/reddit_log.txt",
    ".run-2026-08-27/fetch_reddit.py",
    ".run-2026-08-27/digest-2026-08-27.interactive-backup.md",
    ".run-2026-08-27/opportunities.after-interactive-run.jsonl",
    ".run-2026-08-27/parts5/example-handle-1.json",
    ".run-2026-08-27/reddit_raw/example-subreddit.json",
    ".run-2026-08-27/_d/hits.jsonl",
    ".run-2026-08-27/_d/raw_example_1.json",
    ".run-2026-08-27-rerun-1214/candidates.json",
]


@pytest.mark.parametrize("rel", RUN_ARTIFACTS_AT_REPO_ROOT)
def test_check4_catches_a_real_run_artifact_at_an_in_repo_path(tmp_path, rel):
    """CHECK 4, THE ONE THAT WAS INERT. Each of these is a file a real run of this skill writes.

    Poison: the artifact is git-tracked at a repo-relative path, undeclared.
    Expected: exit 1, and the path named.
    """
    repo = make_repo(tmp_path, files={rel: "{}\n", "SKILL.md": "# tool\n"},
                     manifest=base_manifest())
    rc, out = run_guard(repo)
    assert_blocked(rc, out, rel, "RUN-SHAPE")


@pytest.mark.parametrize("rel", RUN_TREE)
def test_check4_catches_the_whole_run_tree(tmp_path, rel):
    """The per-run scratch tree, file by file. 116 of these land per real run."""
    repo = make_repo(tmp_path, files={rel: "x\n"}, manifest=base_manifest())
    rc, out = run_guard(repo)
    assert_blocked(rc, out, rel, "RUN-SHAPE")


def test_check4_catches_an_entire_run_tree_at_once(tmp_path):
    """A whole run pasted in must produce a finding PER FILE, not one summary line.

    A gate that says "1 violation" for 116 files teaches the reader that moving one file fixes it.
    """
    repo = make_repo(tmp_path, files={rel: "x\n" for rel in RUN_TREE}, manifest=base_manifest())
    rc, out = run_guard(repo)
    assert rc == VIOLATION, out
    for rel in RUN_TREE:
        assert rel in out, "the run tree was blocked but %r was never named:\n%s" % (rel, out)
    assert "%d violation(s)" % len(RUN_TREE) in out, out


def test_check4_over_rejection_tool_material_passes(tmp_path):
    """The other half of the control: hand-written TOOL material must NOT be flagged.

    These are real names from this repo. A shape list broad enough to swallow SKILL.md or the
    roster DESIGN NOTE gets switched off within a week, and then nothing is checked at all.
    """
    clean = {
        "SKILL.md": "# daily-hotspots\n",
        "README.md": "# readme\n",
        "reference/collect.md": "collection reference\n",
        "reference/roster-evolution.md": "how the roster evolves\n",
        "scripts/lib.py": "TRACKS = []\n",
        "scripts/run.py": "def main():\n    return 0\n",
        "scripts/archive.py": "def archive_card():\n    return None\n",
        "tools/datadir.py": "def resolve_data_dir(name):\n    return None\n",
        "tests/test_dedup.py": "def test_x():\n    assert True\n",
        "watchlist.example.json": "{}\n",
        "archive/opportunities.jsonl.example": '{"schema": 1}\n',
        "metrics/live-runs.jsonl.example": '{"schema": 1}\n',
        ".github/workflows/tests.yml": "name: tests\n",
    }
    repo = make_repo(tmp_path, files=clean, manifest=base_manifest())
    rc, out = run_guard(repo)
    assert rc == CLEAN, "a repo of pure tool material must pass:\n%s" % out
    assert "clean" in out


def test_check4_declaring_the_path_in_tool_is_the_documented_escape(tmp_path):
    """The per-path allowlist works, and it is per PATH, not per directory.

    Declaring one ledger under `tool` must not amnesty the one beside it, or the allowlist becomes
    the paragraph it was built to replace.
    """
    files = {"tests/fixtures/yield/opportunities.jsonl": "{}\n",
             "tests/fixtures/yield/pulls-2026-06.jsonl": "{}\n"}
    m = base_manifest(tool=["tests/fixtures/yield/opportunities.jsonl"])
    repo = make_repo(tmp_path, files=files, manifest=m)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "tests/fixtures/yield/pulls-2026-06.jsonl", "RUN-SHAPE")
    assert "1 violation(s)" in out, "the allowlisted path must not also be reported:\n%s" % out


# ---------------------------------------------------------------------------------------------
# CHECK 1 -- a DATA-class path must not be in the index.
# ---------------------------------------------------------------------------------------------
def test_check1_declared_data_path_that_is_tracked_is_blocked(tmp_path):
    """Poison: the manifest itself says archive/opportunities.jsonl is real-run output, and it is
    staged anyway. This is the 2026-07 leak in one line."""
    m = base_manifest(data=["archive/opportunities.jsonl"])
    repo = make_repo(tmp_path, files={"archive/opportunities.jsonl": '{"id": "op-a"}\n',
                                      "archive/opportunities.jsonl.example": '{"id": "..."}\n'},
                     manifest=m)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "archive/opportunities.jsonl", "DATA-TRACKED")


def test_check1_covers_a_declared_DIRECTORY_not_just_the_exact_path(tmp_path):
    """`archive/` as a DATA declaration must cover everything under it. Otherwise the declaration
    is satisfied by renaming the file."""
    m = base_manifest(data=["archive/"])
    repo = make_repo(tmp_path, files={"archive/digests/2026/2026-08-27.md": "# digest\n"},
                     manifest=m)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "archive/digests/2026/2026-08-27.md", "DATA-TRACKED")


def test_check1_data_sealed_path_may_not_come_back(tmp_path):
    """A sealed path is one that HELD real data and was purged. .gitignore is advisory and
    `git add -f` walks straight through it, which is why make_repo forces the add."""
    m = base_manifest(data_sealed=["metrics/live-runs.jsonl"])
    repo = make_repo(tmp_path, files={"metrics/live-runs.jsonl": '{"run": 1}\n'}, manifest=m)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "metrics/live-runs.jsonl", "DATA-TRACKED")


def test_check1_over_rejection_untracked_data_path_passes(tmp_path):
    """The rule is about the INDEX. A DATA path present in the work tree but not staged is the
    normal, correct state on an operator's machine and must not be a violation."""
    m = base_manifest(data=["archive/opportunities.jsonl"])
    repo = make_repo(tmp_path, files={"archive/opportunities.jsonl.example": '{"id": "..."}\n'},
                     manifest=m)
    (repo / "archive" / "opportunities.jsonl").write_text('{"id": "op-a"}\n', encoding="utf-8")
    rc, out = run_guard(repo)
    assert rc == CLEAN, "an unstaged DATA file is not a leak:\n%s" % out


# ---------------------------------------------------------------------------------------------
# CHECK 3 -- every DATA path ships a schema, so the uninitialized tool is still usable.
# ---------------------------------------------------------------------------------------------
def test_check3_data_path_without_a_schema_is_blocked(tmp_path):
    m = base_manifest(data=["archive/opportunities.jsonl"])
    repo = make_repo(tmp_path, files={"README.md": "# readme\n"}, manifest=m)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "archive/opportunities.jsonl.example", "NO-SCHEMA")


@pytest.mark.parametrize("schema_name", ["watchlist.json.example", "watchlist.example.json"])
def test_check3_over_rejection_either_naming_convention_satisfies_it(tmp_path, schema_name):
    m = base_manifest(data=["watchlist.json"])
    repo = make_repo(tmp_path, files={schema_name: "{}\n"}, manifest=m)
    rc, out = run_guard(repo)
    assert rc == CLEAN, "%s should satisfy the schema requirement:\n%s" % (schema_name, out)


def test_check3_a_declared_output_DIRECTORY_is_not_owed_a_schema(tmp_path):
    """There is no single shape to publish for a whole directory, so a trailing slash is exempt.
    This is an exemption, so it is pinned: widening it to bare paths would silence check 3."""
    m = base_manifest(data=["archive/digests/"])
    repo = make_repo(tmp_path, files={"README.md": "# readme\n"}, manifest=m)
    rc, out = run_guard(repo)
    assert rc == CLEAN, out


# ---------------------------------------------------------------------------------------------
# CHECK 5 -- an empty `data` list has to be a finding, not a default.
# ---------------------------------------------------------------------------------------------
def test_check5_empty_data_list_with_no_audit_note_is_blocked(tmp_path):
    """The manifest a fresh repo gets by accident. It declares nothing, so checks 1 and 3 iterate
    zero times, and without this the repo reports clean on the strength of a default."""
    repo = make_repo(tmp_path, files={"README.md": "# readme\n"},
                     manifest={"data": [], "data_sealed": [], "fixture": []})
    rc, out = run_guard(repo)
    assert_blocked(rc, out, ".dataclass.json", "UNAUDITED")


@pytest.mark.parametrize("note", ["", "   ", "\n\t "])
def test_check5_whitespace_is_not_an_audit(tmp_path, note):
    """A key present with an empty value is the cheapest way to silence this check, so it must not
    work. This is the difference between a note and a field."""
    repo = make_repo(tmp_path, files={"README.md": "# readme\n"},
                     manifest={"data": [], "fixture": [], "_audited": note})
    rc, out = run_guard(repo)
    assert_blocked(rc, out, ".dataclass.json", "UNAUDITED")


def test_check5_over_rejection_a_real_note_or_the_older_key_passes(tmp_path):
    for key in ("_audited", "_armed"):
        repo = make_repo(tmp_path, name="audited-" + key, files={"README.md": "# readme\n"},
                         manifest={"data": [], "fixture": [], key: AUDITED})
        rc, out = run_guard(repo)
        assert rc == CLEAN, "%s should satisfy the audit requirement:\n%s" % (key, out)


def test_check5_a_nonempty_data_list_needs_no_note(tmp_path):
    """A declaration IS the finding. Requiring prose next to a real list would be prose for its
    own sake, which is the thing this repo keeps deciding is not a control."""
    m = {"data": ["archive/opportunities.jsonl"], "fixture": []}
    repo = make_repo(tmp_path, files={"archive/opportunities.jsonl.example": "{}\n"}, manifest=m)
    rc, out = run_guard(repo)
    assert rc == CLEAN, out


# ---------------------------------------------------------------------------------------------
# CHECK 2 -- a fixture must be byte-identical to what the generator emits.
# ---------------------------------------------------------------------------------------------
FAKE_GEN = (
    "import argparse, json, os\n"
    "BLOB = json.dumps({\"_synthetic\": \"generated\", \"host\": \"example.com\"}, indent=2) + \"\\n\"\n"
    "ap = argparse.ArgumentParser()\n"
    "ap.add_argument(\"--out\")\n"
    "a = ap.parse_args()\n"
    "open(os.path.join(a.out, \"sample.json\"), \"w\", newline=\"\").write(BLOB)\n"
)


def _generated_bytes():
    return json.dumps({"_synthetic": "generated", "host": "example.com"}, indent=2) + "\n"


def _fixture_repo(tmp_path, name, fixture_text, generator=FAKE_GEN, declare="fx/sample.json"):
    files = {"fx/sample.json": fixture_text}
    if generator is not None:
        files["tools/make_fixtures.py"] = generator
    return make_repo(tmp_path, name=name, files=files,
                     manifest=base_manifest(fixture=[declare]))


def test_check2_a_hand_pasted_fixture_is_blocked(tmp_path):
    """THE MOVE THAT CAUSED MOST OF THE 2026-07 LEAKS: someone pastes a convenient real record into
    a golden file. A real record cannot be regenerated, so byte-equality is what makes that fail at
    commit time instead of at audit time months later."""
    repo = _fixture_repo(tmp_path, "handedited",
                         _generated_bytes().replace("example.com", "a-real-looking-host.test"))
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "fx/sample.json", "HAND-EDITED")


def test_check2_a_declared_fixture_with_no_generator_at_all_is_blocked(tmp_path):
    """A GUARD FILE IT DEPENDS ON IS ABSENT. Deleting tools/make_fixtures.py must not turn check 2
    into a no-op, which is exactly what "if the generator is missing, skip" would do."""
    repo = _fixture_repo(tmp_path, "nogen", _generated_bytes(), generator=None)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "tools/make_fixtures.py", "NO-GENERATOR")


def test_check2_a_generator_that_crashes_is_blocked_not_skipped(tmp_path):
    """A generator that exits nonzero proves nothing about the fixtures. Treating that as "could
    not check, carry on" is the fail-open shape this whole file exists to rule out."""
    repo = _fixture_repo(tmp_path, "brokengen", _generated_bytes(),
                         generator="import sys\nsys.exit(3)\n")
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "tools/make_fixtures.py", "GENERATOR-FAILED")


def test_check2_a_fixture_the_generator_does_not_produce_is_blocked(tmp_path):
    """Declared, present, and unreproducible: nothing proves it is synthetic."""
    repo = _fixture_repo(tmp_path, "notgen", "{}\n", declare="fx/other.json")
    (repo / "fx" / "other.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A", "--force")
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "fx/other.json", "NOT-GENERATED")


def test_check2_a_declared_fixture_that_is_missing_is_blocked(tmp_path):
    repo = _fixture_repo(tmp_path, "missing", _generated_bytes())
    (repo / "fx" / "sample.json").unlink()
    git(repo, "add", "-A", "--force")
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "fx/sample.json", "MISSING")


def test_check2_over_rejection_a_generated_fixture_passes(tmp_path):
    repo = _fixture_repo(tmp_path, "good", _generated_bytes())
    rc, out = run_guard(repo)
    assert rc == CLEAN, "a fixture that matches its generator must pass:\n%s" % out
    assert "1 FIXTUREs generator-reproducible" in out, out


def test_check2_crlf_is_not_a_hand_edit(tmp_path):
    """Windows checkouts rewrite line endings. If that read as a hand-edited fixture, the gate
    would be red on every clone on this operator's own machine, and a permanently red gate gets
    disabled within the week."""
    repo = _fixture_repo(tmp_path, "crlf", _generated_bytes())
    # write_bytes, not write_text: write_text translates again on Windows and would produce
    # \r\r\n, a third file that is neither what a checkout writes nor what the generator emits.
    (repo / "fx" / "sample.json").write_bytes(
        _generated_bytes().replace("\n", "\r\n").encode("utf-8"))
    git(repo, "add", "-A", "--force")
    rc, out = run_guard(repo)
    assert rc == CLEAN, out


# ---------------------------------------------------------------------------------------------
# FAIL CLOSED, NOT OPEN.
#
# The ways this gate could decide it "cannot check". All of them must be nonzero and must say so.
# The gate deliberately never asks whether the remote is public, so the visibility cases below are
# about proving it does not start asking and then shrug when the answer is unavailable.
# ---------------------------------------------------------------------------------------------
def test_a_directory_that_is_not_a_work_tree_exits_not_examined(tmp_path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    (d / "candidates.json").write_text("{}\n", encoding="utf-8")
    rc, out = run_guard(d)
    assert rc == NOT_EXAMINED, "expected %d, got %d\n%s" % (NOT_EXAMINED, rc, out)
    assert "NOTHING was examined" in out, out
    assert "clean" not in out.lower(), "a failed scan must never say clean:\n%s" % out


def test_a_shell_dot_git_directory_exits_not_examined(tmp_path):
    """An empty .git directory has really happened on this machine and stopped a work journal for
    days. It is the canonical way a scan silently examines nothing."""
    d = tmp_path / "shell"
    (d / ".git").mkdir(parents=True)
    (d / "candidates.json").write_text("{}\n", encoding="utf-8")
    rc, out = run_guard(d)
    assert rc == NOT_EXAMINED, "expected %d, got %d\n%s" % (NOT_EXAMINED, rc, out)
    assert "NOTHING was examined" in out, out


def test_git_missing_from_PATH_exits_not_examined(tmp_path):
    """The interpreter-probe lesson, applied to git: a tool that cannot run must not read as a tool
    that found nothing."""
    repo = make_repo(tmp_path, files={"candidates.json": "{}\n"}, manifest=base_manifest())
    empty = tmp_path / "empty-path"
    empty.mkdir()
    rc, out = run_guard(repo, path=str(empty))
    assert rc == NOT_EXAMINED, "expected %d, got %d\n%s" % (NOT_EXAMINED, rc, out)
    assert "NOTHING was examined" in out, out


@pytest.mark.parametrize("remote", [
    None,                                               # no remote at all: no visibility to read
    "https://example.invalid/nobody/unknown-repo.git",  # a host no visibility map covers
    "git@example.invalid:nobody/unknown-repo.git",
    "../a-local-path-that-is-not-a-hosted-repo",
])
def test_unknown_remote_visibility_still_enforces(tmp_path, remote):
    """FAIL CLOSED ON VISIBILITY. This gate must never grow a "skip if the remote looks private"
    branch. pii_guard has one and it is right there, because a content scan of a private repo is
    noise. The boundary is a different question: it is about where a skill WRITES, and a repo whose
    visibility cannot be determined is exactly the repo that has to be treated as public.

    Asserted behaviorally rather than by reading the source: with no remote, with a remote on a host
    no map covers, and with a bare path remote, the same poisoned file is still blocked.
    """
    repo = make_repo(tmp_path, name="vis-%d" % (abs(hash(str(remote))) % 999983),
                     files={"archive/opportunities.jsonl": '{"id": "op-a"}\n'},
                     manifest=base_manifest(), remote=remote)
    rc, out = run_guard(repo)
    assert_blocked(rc, out, "archive/opportunities.jsonl", "RUN-SHAPE")


def test_no_manifest_does_not_launder_a_tracked_run_artifact(tmp_path):
    """DELETING THE MANIFEST MUST NOT DISARM THE GATE.

    Before this test, an absent .dataclass.json returned 0 immediately, before check 4 ever ran. So
    the one-line way past the primary control was to delete the file that arms it, after which the
    repo could track an entire archive with the gate still reporting success. CI papered over this
    with a `test -f .dataclass.json` step in pii-guard.yml, which says out loud that the fail-open
    was known; the hooks had no such step, and a workaround in one caller is not a property of the
    gate. Check 4 is manifest-INDEPENDENT by design, so it must still run.
    """
    repo = make_repo(tmp_path, manifest=None, files={
        "archive/opportunities.jsonl": '{"id": "op-a"}\n',
        "archive/digests/2026/2026-08-27.md": "# digest\n",
        "candidates.json": "{}\n",
    })
    rc, out = run_guard(repo)
    assert rc == VIOLATION, "expected %d, got %d\n%s" % (VIOLATION, rc, out)
    for rel in ("archive/opportunities.jsonl", "archive/digests/2026/2026-08-27.md",
                "candidates.json"):
        assert rel in out, "not named: %r\n%s" % (rel, out)


def test_no_manifest_is_reported_as_not_armed_not_as_clean(tmp_path):
    """Nothing declared and nothing wrong are different findings and must not share an exit code.

    A repo with no manifest has had checks 1, 2, 3 and 5 assert exactly nothing about it. Reporting
    that as 0 makes a disarmed gate look identical to a passing one in a CI log.
    """
    repo = make_repo(tmp_path, manifest=None, files={"README.md": "# readme\n"})
    rc, out = run_guard(repo)
    assert rc == NOT_ARMED, "expected %d, got %d\n%s" % (NOT_ARMED, rc, out)
    assert_not_a_pass(out)


def test_zero_tracked_files_is_not_a_clean_bill_of_health(tmp_path):
    """THE ORIGINAL DEFECT IN ITS PUREST FORM: a checker fed nothing printing the same green as a
    checker that found nothing wrong.

    `git ls-files` exits 0 and returns an empty list in a fresh repo, and returned one in the
    incident this script's own `_run` docstring describes. Every per-file check then iterates zero
    times and the summary says "clean". The count inside that success line was the only difference
    from a real pass, and a count inside a success message is not a signal anybody reads.
    """
    repo = make_repo(tmp_path, files={"README.md": "# readme\n"}, manifest=base_manifest(),
                     track=False)
    rc, out = run_guard(repo)
    assert rc == NOT_EXAMINED, "expected %d, got %d\n%s" % (NOT_EXAMINED, rc, out)
    assert "NOTHING was examined" in out, out
    assert_not_a_pass(out)


def test_clean_and_not_examined_do_not_share_an_exit_code(tmp_path):
    """The property, stated once, across the three states a caller has to tell apart."""
    armed = make_repo(tmp_path, name="armed", files={"README.md": "# readme\n"},
                      manifest=base_manifest())
    empty = make_repo(tmp_path, name="empty", files={"README.md": "# readme\n"},
                      manifest=base_manifest(), track=False)
    unarmed = make_repo(tmp_path, name="unarmed", files={"README.md": "# readme\n"}, manifest=None)
    codes = {"clean": run_guard(armed)[0],
             "nothing examined": run_guard(empty)[0],
             "not armed": run_guard(unarmed)[0]}
    assert len(set(codes.values())) == 3, "these three states must be distinguishable: %r" % codes
    assert codes["clean"] == CLEAN
