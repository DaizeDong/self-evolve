#!/usr/bin/env python3
"""data_boundary -- a public skill repo is an UNINITIALIZED TOOL. Enforced by construction.

WHY THIS EXISTS, AND WHY pii_guard WAS NOT ENOUGH
-------------------------------------------------
pii_guard is a sieve at the exit: it reads what you are about to publish and looks for things that
smell private. It works, and it has caught real leaks. But it is the wrong primary control, because
it accepts the premise that real data is flowing toward the exit at all.

The 2026-07 audit found real-run output sitting in PUBLIC repos -- a research skill's verdict ledger,
a shopping skill's purchase records, a social skill's posting account -- not because anyone pasted it
into a doc, but because the skills WROTE it there during real runs. `metrics/*.jsonl` was append-only
telemetry of the operator's actual life, git-tracked, on GitHub. (What it recorded was his; the point
here is the mechanism, so the specifics stay out of this file.)

These repos already had a private-companion-config boundary. It only ever covered INPUTS -- the
credentials, the mailboxes, the account slugs. Nothing covered OUTPUTS: what the skill LEARNED from a
real run. That is the door every remaining leak walked out of, and no amount of content scanning
fixes a door.

So: every path in a public repo belongs to exactly one class, declared in `.dataclass.json`.

  TOOL     code, SKILL.md, docs.                 Public. Hand-written. Contains no data at all.
  FIXTURE  tests, goldens, examples.             Public, but SYNTHETIC ONLY, and PRODUCED BY A
                                                 GENERATOR -- never a copy of a real record. The
                                                 generator is the proof: a hand-pasted real email
                                                 cannot be regenerated, so it fails here.
  DATA     anything a real run produced:         PRIVATE companion repo. Physically absent from the
           telemetry, real goldens, calibration, public repo. The loader resolves it from outside.
           caches, verdicts, config.             The public repo ships only a `*.example` schema.

THE POINT IS NOT THAT THE DATA IS HIDDEN. It is that an agent writing the public repo has NOTHING
REAL WITHIN REACH to reuse. You cannot copy a convenient example out of a file that is not there.
That closes the artifact leak completely -- which is more than a scanner can promise.

WHAT IT DOES NOT CLOSE
----------------------
Prose. An agent that is reading the operator's inbox can still type a real employer's name into a
CHANGELOG from memory. No boundary reaches that; deleting a file does not make anyone forget. That
is what pii_guard is FOR, and it is why it stays -- demoted from primary control to backstop.

CHECKS
  1. no DATA-class path is git-tracked                       (the door)
  2. every FIXTURE path is byte-identical to what tools/make_fixtures.py produces  (the copy-paste)
  3. every DATA path has a `<path>.example` schema in the repo (so the tool is usable uninitialized)
  4. no git-tracked file has the SHAPE of real-run output unless it is declared  (the empty manifest)

`data_sealed` is a fourth, narrower declaration: a path that USED to hold real data, has been
purged, and must stay dead. Checked like DATA in (1), exempt from (3) -- a dead path is not owed a
schema; shipping one would advertise a path the tool no longer uses.

WHY CHECK 4 EXISTS (2026-07-31)
-------------------------------
Checks 1..3 only ever look at what the manifest DECLARES. A manifest that declares nothing therefore
enforces nothing: an independent verifier cloned six public repos whose `data` list was empty,
committed `metrics/live-runs.jsonl` and `runs/transcript.json` into each, and this script exited 0
on all six. Each of those manifests carried a careful prose note concluding that the skill writes its
real-run output outside the repo. The notes were largely accurate. They were also inert: PROSE IS
NOT A CONTROL, and every one of those skills can still be pointed at a repo-relative path by a flag
or an env var (`--archive-dir`, `--state-path`, `--status-json`, `LLMCALL_LEDGER`, `SCHEDULE_DB_PATH`),
so "the default resolver points elsewhere" was never the same statement as "nothing can land here".

So the empty declaration now has to survive a mechanical question instead of an argument: does this
repo TRACK anything shaped like the output a real run produces? The shapes below are not a guess at
what data looks like -- that is pii_guard's losing game -- they are the literal places and names this
fleet's skills write to. A repo with nothing to declare passes because the repo is genuinely empty of
run output, and it starts failing the moment that stops being true.

An exemption is possible and it is per-path: list the file under `tool` in the manifest with a
reason. That is an allowlist entry visible in the diff, which is the opposite of a paragraph.

  python data_boundary.py [--repo .]     exit 0 clean / 1 violation
Stdlib only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

MANIFEST = ".dataclass.json"

# A file whose name says "this is a published SHAPE, not a record". Exempt from the shape check, in
# either naming convention, because check 3 REQUIRES a schema next to every declared DATA path and
# `metrics/live-runs.jsonl.example` must not therefore become a violation of check 4.
SHAPE_EXEMPT = re.compile(r"\.(example|sample|tmpl|template)(\.|$)", re.I)

# The shapes real runs actually leave behind in this fleet. Each entry is (why, pattern).
RUN_SHAPES = (
    ("a jsonl ledger under metrics/ -- the exact shape of the 2026-07 leak",
     re.compile(r"(^|/)metrics/.*\.(jsonl|ndjson)$", re.I)),
    ("anything under a runs/ directory -- per-run output",
     re.compile(r"(^|/)runs/", re.I)),
    ("a dated file under an output directory -- a dated file is a record of a day, not a tool",
     re.compile(r"(^|/)(reports?|archive|digests?|logs?|out|output|state|snapshots?)/"
                r".*(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}(?!\d)|\d{8})", re.I)),
    ("a jsonl ledger under an output directory",
     re.compile(r"(^|/)(archive|logs?|state|out|output|runs|reports?)/.*\.(jsonl|ndjson)$", re.I)),
    ("a filename this fleet uses for a live ledger",
     re.compile(r"(^|/)(ledger|live-runs|events|dry-run|verdicts|opportunities|history|transcript"
                r"|pulls-\d{4}-\d{2})\.(jsonl|ndjson)$", re.I)),
    ("a filename this fleet uses for real-run state",
     re.compile(r"(^|/)(escalation_state|fleet-check-status|bandit-state|throttle-state"
                r"|dedup-state)\.json$", re.I)),
    ("a database file -- nobody hand-writes one, so it came from a run",
     re.compile(r"\.(db|sqlite|sqlite3)$", re.I)),
)


class GitError(RuntimeError):
    """A git invocation this check depends on did not succeed.

    Raised, never swallowed. See _run for why an exception and not an empty string.
    """


def _run(args, cwd):
    """Run a git command and return its stdout.

    THIS USED TO FAIL OPEN, and on the PRIMARY control that is worse than on the backstop.
    The old body was `return p.stdout if p.returncode == 0 else ""`. `tracked()` read that
    empty string as an ANSWER (no tracked files), every per-file check then iterated zero
    times, and main() printed "data_boundary: clean (... 0 tracked files ...)" and exited 0
    having examined nothing. Anything that breaks git produced that: a shell .git directory
    (a shape that has actually occurred on this machine), a directory that is not a repo,
    git missing from PATH, an index.lock, a dubious-ownership refusal.

    pii_guard and dash_guard were hardened against exactly this and this file was the
    outlier, which meant the two scanners disagreed about the same broken environment:
    pii_guard --tree exited 2 saying NOTHING was examined while data_boundary next to it
    printed clean and exited 0. install.py:86 calls this file the PRIMARY control, so the
    control was the one lying.

    A nonzero exit now RAISES, carrying git's own stderr. A clean report requires that the
    scan actually happened.

    encoding="utf-8" is load bearing, not decoration: without it text=True decodes with the
    locale codepage (cp936 here) while git emits UTF-8, and errors="replace" silently turns
    a repo path containing non-ASCII into mojibake. The `git ls-files` that follows then
    runs in a directory that does not exist.
    """
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except (OSError, ValueError) as e:
        raise GitError("cannot execute `%s` in %s: %s\n"
                       "  git must be runnable for this check to mean anything."
                       % (" ".join(args), cwd, e)) from e
    if p.returncode != 0:
        raise GitError("`%s` exited %d in %s\n  %s"
                       % (" ".join(args), p.returncode, cwd,
                          (p.stderr or "").strip() or "(no stderr)"))
    return p.stdout


def _repo_root(start):
    """Resolve the work tree root, or raise.

    The old body ended in `or start`, so a directory that is not a work tree quietly became
    its own "repo root". Everything downstream then scanned a non-repo and reported clean.
    That is the same defect pii_guard was fixed for; refusing here is the whole point.
    """
    root = _run(["git", "rev-parse", "--show-toplevel"], start).strip()
    if not root:
        raise GitError("git named no toplevel for %s (is it a work tree?)" % start)
    return root


def load_manifest(root):
    p = os.path.join(root, MANIFEST)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def tracked(root):
    """Every git-tracked path, NUL-separated so non-ASCII names survive.

    Why -z: `git ls-files` without it renders any path containing a non-ASCII byte as a
    C-quoted escape string (quotes included, e.g. "ä¸­...md"). Those strings are
    not paths. They do not open, and every regex anchored on a real suffix misses them.
    Callers read this list as an ANSWER, so such a file got counted in the tracked total and
    then silently excluded from every per-file match. Measured 2026-08-19: a tracked
    metrics/<CJK>-live-runs.jsonl produced "clean (... 3 tracked files carry no real-run
    shape)" with rc=0, while byte-identical content under an ASCII name produced rc=1.
    -z makes git emit raw bytes with NUL separators, so the name round-trips.
    """
    return {p for p in _run(["git", "ls-files", "-z"], root).split("\0") if p}


def _covered(rel, pats):
    """Is `rel` the declared path itself, or under it when the declaration names a directory?"""
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in pats)


def check_data_not_tracked(root, m, files, out):
    """A DATA path in the index means the skill wrote the operator's real life into a public repo.

    `data_sealed` is the same rule for a path that is DEAD: it held real data once, the data has
    been moved out and purged from history, and it must never come back. .gitignore already covers
    it, but .gitignore is advisory -- `git add -f` walks straight through, and an agent that wants
    a file tracked will find that flag. This makes the seal enforceable. It differs from `data`
    only in that a dead path is not owed a schema: publishing one would advertise a path the tool
    no longer uses.
    """
    pats = m.get("data", []) + m.get("data_sealed", [])
    for rel in sorted(files):
        if _covered(rel, pats):
            out.append(("DATA-TRACKED", rel,
                        "real-run output must live in the private companion config, not here"))


def check_data_has_schema(root, m, out):
    """An uninitialized tool must still be USABLE: ship the shape, never the contents.

    Without this, "keep real data out of the repo" degrades into "the repo no longer explains what it
    expects", and the next person to wire it up guesses -- or, far more likely, an agent recreates a
    convenient real-looking file to work against. The schema is what makes the empty tool honest.

    Both conventions are accepted: `x.jsonl.example` and the older `config.example.json`. A DATA path
    ending in `/` is a whole output directory; there is no single shape to publish for it.
    """
    for pat in m.get("data", []):
        if pat.endswith("/"):
            continue
        stem, ext = os.path.splitext(pat)
        if any(os.path.isfile(os.path.join(root, c))
               for c in (pat + ".example", stem + ".example" + ext)):
            continue
        out.append(("NO-SCHEMA", pat + ".example",
                    "publish the schema so the tool is usable uninitialized"))


def check_fixtures_are_generated(root, m, out):
    """The whole reason fixtures are generated: a real record CANNOT be regenerated.

    Hand-pasting a real email into a golden file is the single move that produced most of the 2026-07
    leaks. Requiring byte-equality with a deterministic generator makes that move fail loudly at
    commit time, instead of relying on someone noticing, months later, that a sender address in a
    test fixture was somebody's actual inbox.
    """
    fixtures = m.get("fixture", [])
    if not fixtures:
        return
    gen = os.path.join(root, "tools", "make_fixtures.py")
    if not os.path.isfile(gen):
        out.append(("NO-GENERATOR", "tools/make_fixtures.py",
                    "fixtures are declared but nothing can regenerate them -- so nothing proves "
                    "they are synthetic"))
        return
    with tempfile.TemporaryDirectory() as td:
        p = subprocess.run([sys.executable, gen, "--out", td], cwd=root,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            out.append(("GENERATOR-FAILED", "tools/make_fixtures.py",
                        (p.stderr or "").strip().splitlines()[-1] if p.stderr else "non-zero exit"))
            return
        for rel in fixtures:
            live = os.path.join(root, rel)
            fresh = os.path.join(td, os.path.basename(rel))
            if not os.path.isfile(fresh):
                out.append(("NOT-GENERATED", rel, "generator does not produce this fixture"))
                continue
            if not os.path.isfile(live):
                out.append(("MISSING", rel, "declared fixture is absent; run make_fixtures.py"))
                continue
            a = open(live, "rb").read().replace(b"\r\n", b"\n")
            b = open(fresh, "rb").read().replace(b"\r\n", b"\n")
            if a != b:
                out.append(("HAND-EDITED", rel,
                            "does not match the generator -- a real record cannot be regenerated. "
                            "Change the SCHEMA, then run: python tools/make_fixtures.py"))


def check_no_undeclared_run_shapes(root, m, files, out):
    """The check that survives an EMPTY manifest -- see "WHY CHECK 4 EXISTS" at the top of this file.

    Checks 1..3 are declaration-driven, so a repo that declares nothing is checked for nothing. This
    one runs off the tracked file list instead: any file shaped like real-run output must be
    ACCOUNTED FOR by name in the manifest, under `data`/`data_sealed` (check 1 then reports it),
    `fixture` (check 2 then proves it is generator-reproducible), or `tool` (a per-path allowlist
    entry, which shows up in the diff and has to be argued for -- the .pii-allow pattern).

    Default-deny is the point. Nothing here needs the manifest to be right; it needs the repo to be
    empty of run output, which is a fact about the working tree that no note can talk its way out of.
    """
    declared = (m.get("data", []) + m.get("data_sealed", [])
                + m.get("fixture", []) + m.get("tool", []))
    for rel in sorted(files):
        if _covered(rel, declared) or SHAPE_EXEMPT.search(os.path.basename(rel)):
            continue
        for why, pat in RUN_SHAPES:
            if pat.search(rel):
                out.append(("RUN-SHAPE", rel, why))
                break


def main():
    ap = argparse.ArgumentParser(description="Enforce the TOOL / FIXTURE / DATA boundary.")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    try:
        root = _repo_root(os.path.abspath(a.repo))
        files = tracked(root)
    except GitError as e:
        # Exit 2, distinct from 0 (clean) and 1 (violations), mirroring pii_guard. "clean" and
        # "never ran" must not be the same output on the primary control.
        print("data_boundary: SCAN FAILED, git could not be used, so NOTHING was examined.\n  %s"
              % e, file=sys.stderr)
        return 2

    m = load_manifest(root)
    if m is None:
        print("data_boundary: no %s in this repo (nothing declared, nothing enforced)" % MANIFEST)
        return 0

    out = []
    check_data_not_tracked(root, m, files, out)
    check_data_has_schema(root, m, out)
    check_fixtures_are_generated(root, m, out)
    check_no_undeclared_run_shapes(root, m, files, out)

    if not out:
        print("data_boundary: clean (%d DATA + %d sealed paths absent, %d FIXTUREs "
              "generator-reproducible, %d tracked files carry no real-run shape)"
              % (len(m.get("data", [])), len(m.get("data_sealed", [])),
                 len(m.get("fixture", [])), len(files)))
        return 0

    print("data_boundary: %d violation(s) -- this repo is not an uninitialized tool\n" % len(out),
          file=sys.stderr)
    for kind, path, why in out:
        print("  %-16s %-52s %s" % (kind, path, why), file=sys.stderr)
    print("\nA public skill repo ships the TOOL and a SYNTHETIC fixture set. Everything a real run\n"
          "produced -- telemetry, real goldens, calibration, verdicts, config -- belongs in the\n"
          "private companion repo, and the loader resolves it from there.\n"
          "\nRUN-SHAPE means: this tracked file looks like output, and no class claims it. Move it out\n"
          "(the usual answer), or -- if it really is hand-written TOOL material that happens to wear\n"
          "the shape -- add the exact path to \"tool\" in %s with a reason." % MANIFEST,
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
