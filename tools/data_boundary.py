#!/usr/bin/env python3
"""data_boundary -- a public skill repo is an UNINITIALIZED TOOL. Enforced by construction.

WHY THIS EXISTS, AND WHY pii_guard WAS NOT ENOUGH
-------------------------------------------------
pii_guard is a sieve at the exit: it reads what you are about to publish and looks for things that
smell private. It works, and it has caught real leaks. But it is the wrong primary control, because
it accepts the premise that real data is flowing toward the exit at all.

The 2026-07 audit found the operator's real research verdicts, real
purchases, a real shipping ZIP and a real social handle sitting in PUBLIC repos -- not because anyone
pasted them into a doc, but because the skills WROTE them there during real runs. `metrics/*.jsonl`
was append-only telemetry of the operator's actual life, git-tracked, on GitHub.

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

`data_sealed` is a fourth, narrower declaration: a path that USED to hold real data, has been
purged, and must stay dead. Checked like DATA in (1), exempt from (3) -- a dead path is not owed a
schema; shipping one would advertise a path the tool no longer uses.

  python data_boundary.py [--repo .]     exit 0 clean / 1 violation
Stdlib only.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

MANIFEST = ".dataclass.json"


def _run(args, cwd):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout if p.returncode == 0 else ""


def _repo_root(start):
    return _run(["git", "rev-parse", "--show-toplevel"], start).strip() or start


def load_manifest(root):
    p = os.path.join(root, MANIFEST)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def tracked(root):
    return set(_run(["git", "ls-files"], root).splitlines())


def check_data_not_tracked(root, m, files, out):
    """A DATA path in the index means the skill wrote the operator's real life into a public repo.

    `data_sealed` is the same rule for a path that is DEAD: it held real data once, the data has
    been moved out and purged from history, and it must never come back. .gitignore already covers
    it, but .gitignore is advisory -- `git add -f` walks straight through, and an agent that wants
    a file tracked will find that flag. This makes the seal enforceable. It differs from `data`
    only in that a dead path is not owed a schema: publishing one would advertise a path the tool
    no longer uses.
    """
    for pat in m.get("data", []) + m.get("data_sealed", []):
        for rel in sorted(files):
            if rel == pat or rel.startswith(pat.rstrip("/") + "/"):
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


def main():
    ap = argparse.ArgumentParser(description="Enforce the TOOL / FIXTURE / DATA boundary.")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    root = _repo_root(os.path.abspath(a.repo))

    m = load_manifest(root)
    if m is None:
        print("data_boundary: no %s in this repo (nothing declared, nothing enforced)" % MANIFEST)
        return 0

    out, files = [], tracked(root)
    check_data_not_tracked(root, m, files, out)
    check_data_has_schema(root, m, out)
    check_fixtures_are_generated(root, m, out)

    if not out:
        print("data_boundary: clean (%d DATA + %d sealed paths absent, %d FIXTUREs "
              "generator-reproducible)"
              % (len(m.get("data", [])), len(m.get("data_sealed", [])),
                 len(m.get("fixture", []))))
        return 0

    print("data_boundary: %d violation(s) -- this repo is not an uninitialized tool\n" % len(out),
          file=sys.stderr)
    for kind, path, why in out:
        print("  %-16s %-52s %s" % (kind, path, why), file=sys.stderr)
    print("\nA public skill repo ships the TOOL and a SYNTHETIC fixture set. Everything a real run\n"
          "produced -- telemetry, real goldens, calibration, verdicts, config -- belongs in the\n"
          "private companion repo, and the loader resolves it from there.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
