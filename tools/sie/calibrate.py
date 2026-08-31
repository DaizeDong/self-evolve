#!/usr/bin/env python3
"""Known-answer positive control for the self-improvement loop.

WHY THIS EXISTS. The loop's only record was 36 rounds and 1 accepted change, and eight adversarial
reviews all reached the same conclusion about that number: it cannot distinguish a broken harness
from a target with nothing left to fix. Every one of them proposed a NEGATIVE control (poison the
instrument, prove it does not fire on nothing) and not one proposed the dual. The operator's standing
rule is that verification must be able to FAIL; its other half is that verification must be able to
SUCCEED, and nothing here had ever tested that half.

So: seed a throwaway copy of a target with defects whose repair we already know, run the UNMODIFIED
loop against it, and count. A run where we already know the right answer is the cheapest experiment
available and it was the one nobody ran.

THE TWO INVARIANTS EVERY SEEDED DEFECT MUST SATISFY, and they are what make the experiment valid
rather than merely expensive:

  1. THE TARGET'S OWN SUITE MUST STAY GREEN with the defect injected. If the suite catches it, the
     baseline is red, PROFILE cannot reach tier A, and the loop is measured on a signal it would
     never have in production. It is also unrealistic: every real defect found in this codebase was
     invisible to the suite until someone looked. A seeded defect the suite already catches is not a
     defect, it is a broken test.

  2. A HIDDEN ORACLE MUST DISCRIMINATE. Each defect ships a test that FAILS on the seeded state and
     PASSES on the clean state. That oracle lives on the harness side and is NEVER copied into the
     sandbox, because a proposer that can read the grading criterion is being graded on its ability
     to read (arXiv:2505.22954 documents objective hacking rising when the checker is visible).

WHAT THIS DOES NOT MEASURE, stated up front so the number is not over-read. It measures repair on
defects a human chose, in files the proposer is allowed to see. It says nothing about defect classes
we did not think to seed, and nothing about the seven of our own real defects that live in files the
gate refuses to patch at all. A high score here is necessary evidence that the loop works, and not
sufficient evidence that it is useful.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The commit every calibration runs against. Pinning is what makes runs comparable to each other and
# independent of whatever the shared target repo is doing right now; see materialize().
PINNED_REF = os.environ.get("SIE_CALIBRATION_REF", "0215204")
DEFECTS_DIR = HERE / "calibration_defects"


class CalibrationError(RuntimeError):
    """A setup failure. Never silently degrades into a score: a calibration that could not run and a
    calibration that scored zero are different facts and must not share an exit path."""


def load_defects(only=None) -> list:
    """Every defect spec in calibration_defects/, sorted by id for a deterministic run order."""
    if not DEFECTS_DIR.is_dir():
        raise CalibrationError("no defect directory at %s" % DEFECTS_DIR)
    out = []
    for p in sorted(DEFECTS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CalibrationError("defect spec %s is unreadable: %s" % (p.name, e))
        for key in ("id", "file_rel", "find", "replace", "oracle", "defect_class", "why_realistic"):
            if key not in d:
                raise CalibrationError("defect spec %s is missing %r" % (p.name, key))
        if only and d["id"] not in only:
            continue
        out.append(d)
    if not out:
        raise CalibrationError("no defect specs matched")
    return out


def _make_repo(root: str) -> None:
    """Give the copied tree a .git marker so it still looks like a repository.

    We deliberately do NOT copy .git, because the copies are throwaways and a real object store
    would be gigabytes. But `datadir._own_repo_root()` finds the repo by walking parents for a .git
    entry, and returns None when there is none, which makes `assert_outside_own_repo` a NO-OP. Three
    of the target's own negative controls then go red on a CLEAN copy, and validate() refuses to
    start before it has looked at a single defect.

    The first of those three tests asserts `_own_repo_root() is not None, "not running from a
    worktree; the guard would be inert"`. The suite was telling the harness exactly what was wrong,
    which is the behavior every guard in this fleet is supposed to have and the reason this was a
    ten-minute diagnosis rather than an afternoon.

    A bare marker FILE is not enough, and finding that out cost a second round: another negative
    control shells out to `git check-ignore` to prove the public repo ignores secret patterns, and a
    fake .git makes that command answer "not ignored" for everything. So the copy gets a real, empty
    `git init`. It has no objects and no remote, which is all the resolver and check-ignore need.
    """
    if (Path(root) / ".git").exists():
        return
    # hooksPath is emptied for THIS repo only. The machine-level hook chain would otherwise run
    # pii_guard against a throwaway that has no remote at all, and an unknown remote is fail-closed
    # by design, so every commit here would be refused. This is not a --no-verify: nothing in this
    # tree can ever be pushed, it lives in TEMP and is deleted when the run ends. The guard exists to
    # stop real data reaching a public remote, and there is no remote to reach.
    steps = [["git", "init", "-q"],
             ["git", "-c", "core.hooksPath=", "add", "-A"],
             ["git", "-c", "core.hooksPath=",
              "-c", "user.name=calibration", "-c", "user.email=calibration@example.com",
              "commit", "-q", "-m", "calibration baseline"]]
    for cmd in steps:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            raise CalibrationError("could not prepare the calibration copy at %s (%s): %s"
                                   % (root, " ".join(cmd[-2:]), (r.stderr or r.stdout or "").strip()))


def seed_copy(target: str, defects: list, dest: str) -> dict:
    """Copy the target and inject every defect. Returns which injections actually applied.

    An injection whose `find` string is absent is a HARD failure, not a skip: a calibration that
    silently seeded 14 of 20 defects would report a repair rate against the wrong denominator, which
    is the same class of defect this whole exercise exists to catch.
    """
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    materialize(target, PINNED_REF, dest)
    applied = {}
    for d in defects:
        p = Path(dest) / d["file_rel"]
        if not p.is_file():
            raise CalibrationError("defect %s targets a missing file %s" % (d["id"], d["file_rel"]))
        src = p.read_text(encoding="utf-8")
        n = src.count(d["find"])
        if n != 1:
            raise CalibrationError(
                "defect %s: its `find` string occurs %d times in %s, needs exactly 1 so the "
                "injection is unambiguous" % (d["id"], n, d["file_rel"]))
        p.write_text(src.replace(d["find"], d["replace"], 1), encoding="utf-8", newline="\n")
        applied[d["id"]] = d["file_rel"]
    # The commit happens AFTER injection, and the ordering is the whole ballgame. Committing first
    # and writing the defects into an unstaged working tree looks identical from the outside: the
    # files on disk carry the defects, the suite sees them, every oracle fires. But the loop builds
    # its sandbox from `--base-ref HEAD`, and HEAD would be the pristine tree. It ran six live
    # rounds against a codebase with zero seeded defects and would have scored 0/20 however well it
    # worked. Nothing errored and nothing looked wrong; the run was simply worthless.
    _make_repo(dest)

    # And then PROVE it, because the ordering above is exactly the kind of thing that looks right
    # forever. Ask git what is actually in the commit, not what is on disk: `git show HEAD:<path>`
    # must contain the injected text for every defect. On-disk checks cannot tell the two orderings
    # apart, which is why the broken one survived a smoke test and six live rounds.
    for d in defects:
        rel = d["file_rel"].replace("\\", "/")
        r = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=dest,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise CalibrationError("defect %s: %s is not in HEAD of the seeded copy: %s"
                                   % (d["id"], rel, (r.stderr or "").strip()))
        if d["replace"] not in (r.stdout or ""):
            raise CalibrationError(
                "defect %s is on disk but NOT in the committed tree, so the loop would build its "
                "sandbox from a pristine baseline and the run would measure nothing" % d["id"])
    return applied


def run_suite(root: str, timeout_s: float = 1800) -> tuple:
    """(exit_code, tail) for the target's own suite. Exit -1 means the run never finished, which is
    NOT a failing suite; conflating those is the bug this harness already had to fix once."""
    skill = os.path.join(root, "skills", "daily-hotspots")
    cwd = skill if os.path.isdir(os.path.join(skill, "tests")) else root
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("DAILY_HOTSPOTS_CONFIG", None)     # the suite must be hermetic; prove it here too
    try:
        pr = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "tests/"],
                            cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, timeout=timeout_s)
        return pr.returncode, (pr.stdout or "")[-600:]
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT after %gs" % timeout_s


def run_oracle(root: str, oracle_src: str, timeout_s: float = 300) -> tuple:
    """Run one hidden oracle against a tree. The oracle is written to a temp file OUTSIDE the tree,
    so a proposer inspecting its own sandbox can never see the grading criterion."""
    with tempfile.TemporaryDirectory(prefix="sie-oracle-") as td:
        f = Path(td) / "test_oracle.py"
        f.write_text(oracle_src, encoding="utf-8", newline="\n")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("DAILY_HOTSPOTS_CONFIG", None)
        scripts = os.path.join(root, "skills", "daily-hotspots", "scripts")
        tools = os.path.join(root, "tools")
        env["PYTHONPATH"] = os.pathsep.join([scripts, tools, env.get("PYTHONPATH", "")])
        try:
            pr = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", str(f)],
                                cwd=td, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env, timeout=timeout_s)
            return pr.returncode, (pr.stdout or "")[-400:]
        except subprocess.TimeoutExpired:
            return -1, "TIMEOUT"


def validate(target: str, defects: list, workdir: str) -> dict:
    """Prove both invariants for every defect BEFORE any loop time is spent.

    This is itself a positive-and-negative control pair: the oracle must FAIL on the seeded tree
    (it can fire) and PASS on the clean tree (it does not fire on nothing). A defect failing either
    clause is excluded with its reason, never silently kept.
    """
    clean = os.path.join(workdir, "clean")
    if os.path.exists(clean):
        shutil.rmtree(clean, ignore_errors=True)
    materialize(target, PINNED_REF, clean)
    _make_repo(clean)

    base_rc, base_tail = run_suite(clean)
    report = {"clean_suite_rc": base_rc, "clean_suite_tail": base_tail, "defects": []}
    if base_rc != 0:
        raise CalibrationError(
            "the CLEAN target's suite is not green (rc=%s); calibration cannot start from a broken "
            "baseline. Tail: %s" % (base_rc, base_tail))

    for d in defects:
        row = {"id": d["id"], "defect_class": d.get("defect_class"), "usable": False, "why": ""}
        seeded = os.path.join(workdir, "seed_" + d["id"])
        try:
            seed_copy(target, [d], seeded)
        except CalibrationError as e:
            row["why"] = "injection failed: %s" % e
            report["defects"].append(row)
            continue

        o_seeded_rc, o_seeded_tail = run_oracle(seeded, d["oracle"])
        o_clean_rc, _ = run_oracle(clean, d["oracle"])
        s_rc, s_tail = run_suite(seeded)

        row["oracle_on_seeded_rc"] = o_seeded_rc
        row["oracle_on_clean_rc"] = o_clean_rc
        row["suite_on_seeded_rc"] = s_rc
        if o_seeded_rc == 0:
            row["why"] = "oracle PASSES on the seeded tree, so it does not detect the defect"
        elif o_seeded_rc == -1:
            row["why"] = "oracle timed out on the seeded tree"
        elif o_clean_rc != 0:
            row["why"] = "oracle FAILS on the clean tree, so it fires on nothing: %s" % o_seeded_tail[:200]
        elif s_rc == -1:
            row["why"] = "the target suite timed out with this defect seeded"
        elif s_rc != 0:
            row["why"] = ("the target's own suite CATCHES this defect (rc=%s), so the baseline "
                          "would be red and the loop could not reach tier A: %s" % (s_rc, s_tail[:200]))
        else:
            row["usable"] = True
        report["defects"].append(row)
        shutil.rmtree(seeded, ignore_errors=True)
    return report


def run_loop(root: str, run_id: str, rounds: int, live: bool, timeout_s: float) -> dict:
    """Drive the UNMODIFIED loop against the seeded tree. No calibration-aware flags exist, and that
    is the point: any switch that told the loop it was being measured would let it behave one way
    here and another way in production, which is exactly the confound this experiment removes."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("DAILY_HOTSPOTS_CONFIG", None)
    base = [sys.executable, "-m", "tools.sie.cli"]
    out = {"run_id": run_id, "rounds_requested": rounds}

    r = subprocess.run(base + ["init", "--target", root], cwd=str(HERE.parents[1]),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out["init_rc"] = r.returncode
    out["init_tail"] = ((r.stdout or "") + (r.stderr or ""))[-1500:]
    if r.returncode != 0:
        raise CalibrationError("the loop could not profile the seeded target: %s" % out["init_tail"])

    cmd = base + ["run", "--target", root, "--run-id", run_id,
                  "--base-ref", "HEAD", "--max-rounds", str(rounds), "--mode", "auto"]
    if live:
        cmd += ["--live"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(HERE.parents[1]), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, timeout=timeout_s)
        out["run_rc"] = r.returncode
        out["run_tail"] = ((r.stdout or "") + (r.stderr or ""))[-4000:]
    except subprocess.TimeoutExpired:
        out["run_rc"] = -1
        out["run_tail"] = "TIMEOUT after %gs" % timeout_s
    out["run_seconds"] = round(time.time() - t0, 1)
    return out


def read_events(root: str, run_id: str) -> dict:
    """Count what the loop actually did, from its own append-only log rather than from its summary.

    A loop that ran zero rounds and a loop that ran twenty and accepted nothing produce the same
    repair score, and they mean opposite things. Only the event log separates them.
    """
    ev = Path(root) / ".sie" / "runs" / run_id / "events.jsonl"
    out = {"events_path": str(ev), "present": ev.is_file(), "kinds": {}, "rounds_seen": 0,
           "accepted": 0, "static_rejected": 0, "rejected": 0}
    if not out["present"]:
        return out
    out["profile_tier"] = None
    for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        # The field is `type`. It was read as `kind` first, every counter came back 0, and the run
        # printed "rounds=0" for a loop that had demonstrably run a round. A counter that reads the
        # wrong key does not report an error, it reports zero, which is indistinguishable from the
        # thing it was built to detect. Hence the assertion below.
        k = str(rec.get("type") or "?")
        out["kinds"][k] = out["kinds"].get(k, 0) + 1
        if k == "ROUND_BEGIN":
            out["rounds_seen"] += 1
        elif k == "PROFILE":
            out["profile_tier"] = rec.get("tier")
        elif k == "ACCEPT":
            out["accepted"] += 1
        elif k == "STATIC_REJECT":
            out["static_rejected"] += 1
        elif k == "REJECT":
            out["rejected"] += 1
    if out["kinds"] and not out["rounds_seen"]:
        # An event log that exists, has records, and yields no rounds means either the loop truly
        # never began one or this parser is reading the wrong key again. Say so instead of printing
        # a zero that reads like a finding.
        out["parser_warning"] = ("no ROUND_BEGIN among %d events; kinds seen: %s"
                                 % (sum(out["kinds"].values()), sorted(out["kinds"])))
    return out


def check_sandbox_baseline(sandbox: str, defects: list) -> int:
    """Confirm the loop's sandbox was built from the SEEDED commit, by reading its base tree."""
    n = 0
    for d in defects:
        rel = d["file_rel"].replace("\\", "/")
        r = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=sandbox,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and d["replace"] in (r.stdout or ""):
            n += 1
    if n != len(defects):
        raise CalibrationError(
            "the loop's sandbox base commit carries only %d of %d seeded defects, so the loop was "
            "not working on the tree this experiment thinks it was" % (n, len(defects)))
    return n


def scoring_root(root: str, run_id: str) -> str:
    """The tree to grade. NOT the seeded root: the loop never writes there.

    Accepted patches land in the loop's own sandbox worktree at .sie/worktrees/<run_id>, and the
    seeded root keeps the injected code untouched for the whole run. Grading the root would have
    returned 0/20 for a loop that repaired every defect, and that zero would have read as the
    experiment's answer rather than as a harness fault. It resolves the sandbox or it raises; there
    is no fallback to the root, because the fallback is precisely the silent wrong answer.
    """
    w = Path(root) / ".sie" / "worktrees" / run_id
    if not w.is_dir():
        raise CalibrationError(
            "the loop's sandbox worktree is missing at %s, so there is nothing to grade. Grading "
            "the seeded root instead would report 0 repairs for any loop whatsoever." % w)

    # The sandbox is only the loop's OUTPUT if refused proposals do not linger in it. That was not
    # true: run_loop had no rollback, so a rejected edit stayed on the tree. One run accepted zero
    # proposals across 11 rounds and this function still scored its sandbox at 6 of 21 repaired,
    # crediting the loop for six changes its own acceptor had refused.
    #
    # So the grade is refused unless the lineage agrees the sandbox is a state the loop ACCEPTED. A
    # run with no accepted version has produced nothing, and "nothing" is a real result that must be
    # reportable as 0, never as whatever happens to be lying in the tree.
    lineage = Path(root) / ".sie" / "runs" / run_id / "archive" / "lineage.json"
    n_accepted = 0
    if lineage.is_file():
        try:
            n_accepted = len(json.loads(lineage.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise CalibrationError("the lineage at %s is unreadable, so there is no way to tell "
                                   "whether the sandbox holds accepted work: %s" % (lineage, e))
    if n_accepted == 0:
        raise CalibrationError(
            "the loop accepted nothing (no lineage at %s), so there is no accepted state to grade. "
            "The sandbox may still hold refused edits; scoring it would credit the loop for changes "
            "its own acceptor rejected." % lineage)
    return str(w)


def score(root: str, defects: list) -> dict:
    """Which seeded defects are repaired in `root`, by the hidden oracles."""
    out = {"repaired": [], "still_broken": [], "oracle_errors": []}
    for d in defects:
        rc, tail = run_oracle(root, d["oracle"])
        if rc == 0:
            out["repaired"].append(d["id"])
        elif rc == -1:
            out["oracle_errors"].append({"id": d["id"], "why": "timeout"})
        else:
            out["still_broken"].append(d["id"])
    return out


def materialize(target: str, ref: str, dest: str) -> None:
    """Put the target AT `ref` into `dest`, taking nothing from the live working tree.

    WHY NOT copytree. The first nine runs copied the target's working tree, which made every one of
    them depend on whatever state that shared repo happened to be in. It bit twice. Once an agent
    that had been told in writing never to touch that repo edited it anyway. Once, and this was not
    an accident at all, ANOTHER SESSION was doing legitimate work in it: three new commits about data
    boundaries and push hooks, landing between 13:36 and 15:50 while a calibration was starting. Both
    times the baseline suite went red (83 failed) and the run refused to start, correctly.

    The second one is the instructive one. Nobody did anything wrong except me: I pointed a
    long-running experiment at a live shared repository and relied on it holding still. This session
    had already written down that rule for its subagents ("do not protect a live repo with a
    prohibition, give the agent a copy") and then did not apply it to itself.

    `git archive <ref>` extracts exactly one commit. The working tree, the index, and anything
    another session is in the middle of are all invisible to it. 0215204 is the ref the first eight
    runs used and its suite was measured green in every one of them, so pinning to it also makes the
    old and new numbers comparable.
    """
    os.makedirs(dest, exist_ok=True)
    r = subprocess.run(["git", "-C", target, "rev-parse", "--verify", "%s^{commit}" % ref],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise CalibrationError("cannot resolve ref %r in %s: %s"
                               % (ref, target, (r.stderr or "").strip()[:200]))
    sha = (r.stdout or "").strip()
    tar = subprocess.run(["git", "-C", target, "archive", "--format=tar", sha],
                         capture_output=True)
    if tar.returncode != 0:
        raise CalibrationError("git archive failed for %s: %s"
                               % (sha[:12], (tar.stderr or b"").decode("utf-8", "replace")[:200]))
    import tarfile, io as _io
    with tarfile.open(fileobj=_io.BytesIO(tar.stdout)) as tf:
        tf.extractall(dest)


def _same_file(a: str, b: str, rel: str) -> bool:
    """True when one file is byte-identical between two snapshots."""
    try:
        return Path(os.path.join(a, rel)).read_bytes() == Path(os.path.join(b, rel)).read_bytes()
    except OSError:
        return False                 # cannot prove identical, so re-measure


def _same_sources(a: str, b: str, defects: list) -> bool:
    """True when every file any defect targets is byte-identical between two snapshots.

    Only the defect-bearing files matter here: an oracle can only move if the code it exercises
    changed. Comparing whole trees would also drag in caches and generated files and answer "changed"
    for versions that are behaviorally identical.
    """
    for d in defects:
        rel = d["file_rel"]
        pa, pb = os.path.join(a, rel), os.path.join(b, rel)
        try:
            if Path(pa).read_bytes() != Path(pb).read_bytes():
                return False
        except OSError:
            return False              # cannot prove identical, so do the expensive, correct thing
    return True


def attribute_decisions(root: str, run_id: str, defects: list) -> dict:
    """Label every ACCEPTED version from outside, using the hidden oracles.

    WHY THIS EXISTS, and it is the one thing three independent judges agreed to build first.

    `score()` runs the oracles ONCE, on the final tree. So a loop that accepted fifty one wrong
    changes and one right one reports exactly the same number as a loop that accepted the one right
    change and rejected everything else. That is not a measurement, it is a summary that discards the
    distinction the whole exercise is about.

    Every accepted version already has a full source snapshot on disk (archive.snapshot_version) and
    the lineage records the order. So each accepted DECISION can be labelled individually by running
    every oracle against that version's snapshot and comparing to the previous version's:

      REPAIR      this defect's own oracle went red -> green at this version. The decision was right.
      REGRESSION  some oracle went green -> red. The decision undid an earlier repair.
      NO_SEEDED_EFFECT   no seeded oracle moved. READ THIS LABEL NARROWLY. It does NOT mean the
                  change was worthless; it means none of the 21 SEEDED defects was affected. Two of
                  the changes carrying this label were inspected by hand: one threaded `side` and
                  `crowdedness` into score.py's CLI entry point, repairing a real unthreaded-argument
                  bug nobody had seeded, and one added `split_weight_proposal` to handle the two
                  weight vectors the demand lane needs. Both are genuine improvements. The instrument
                  measures "did it fix one of MY defects", never "was it good".
      (a version can carry several labels at once, so they are reported as lists, not as one verdict)

    THE POINT IS THE INSTRUMENT, NOT THE NUMBER. Four gates in this codebase were correct in their
    unit tests and inert in production, every time because the test fed them the input they were
    built to recognize. This pass takes its input from outside the system under test: 21 defects with
    known repairs, chosen by someone who knew the answer and did not tell the loop. A gate that
    scores well here cannot have done it by recognizing its own fixture.

    It adjudicates nothing and can accept nothing, so it violates no iron law. It only reports.
    """
    arch = os.path.join(root, ".sie", "runs", run_id, "archive")
    lin = []
    lp = os.path.join(arch, "lineage.json")
    if os.path.isfile(lp):
        try:
            lin = json.loads(Path(lp).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return {"error": "lineage unreadable: %s" % e, "versions": []}

    out = {"versions": [], "totals": {"REPAIR": 0, "REGRESSION": 0, "NO_SEEDED_EFFECT": 0},
           "n_accepted": len(lin)}
    prev = None                       # {defect_id: True if oracle green}
    prev_snap = None
    for entry in lin:
        vid = entry.get("vid")
        snap = os.path.join(arch, "versions", vid, "snapshot")
        row = {"vid": vid, "parent": entry.get("parent_vid"), "labels": [],
               "repaired": [], "regressed": [], "snapshot": snap}
        if not os.path.isdir(snap):
            # A version with no snapshot cannot be attributed. Saying so is the whole discipline:
            # "not measured" and "measured clean" must never share an output.
            row["labels"].append("UNMEASURABLE")
            row["why"] = "no snapshot at %s" % snap
            out["versions"].append(row)
            continue
        # COST FIRST, and this is not an optimization, it is the difference between an instrument
        # that runs and one that does not. 31 versions times 21 oracles is 651 pytest invocations;
        # the first attempt at this function ran past ten minutes and was killed. A version whose
        # source is byte-identical to its parent's cannot have moved any oracle, so it is labelled
        # INERT directly and its 21 runs are skipped. That is exact, not an approximation: identical
        # source, identical behavior.
        if prev_snap is not None and _same_sources(prev_snap, snap, defects):
            row["labels"].append("NO_SEEDED_EFFECT")
            row["why"] = "source identical to parent version"
            out["totals"]["NO_SEEDED_EFFECT"] += 1
            out["versions"].append(row)
            prev_snap = snap
            continue
        # Per DEFECT, not per version. An oracle can only move if the file its defect lives in
        # changed, so a defect whose file is byte-identical to the parent's inherits the parent's
        # verdict for free. Measured on a real run: consecutive versions typically differ in ONE
        # file, so this turns 21 pytest runs per version into one or two. The whole-version fast
        # path above almost never fires, because the loop does change some file every round; it is
        # this per-defect one that makes the instrument affordable at all.
        cur = {}
        for d in defects:
            if prev is not None and prev_snap is not None and _same_file(prev_snap, snap, d["file_rel"]):
                cur[d["id"]] = prev[d["id"]]
                continue
            rc, _ = run_oracle(snap, d["oracle"])
            cur[d["id"]] = (rc == 0)
        if prev is not None:
            row["repaired"] = sorted(k for k in cur if cur[k] and not prev.get(k))
            row["regressed"] = sorted(k for k in cur if not cur[k] and prev.get(k))
        else:
            row["repaired"] = sorted(k for k in cur if cur[k])
        if row["repaired"]:
            row["labels"].append("REPAIR")
        if row["regressed"]:
            row["labels"].append("REGRESSION")
        if not row["labels"]:
            row["labels"].append("NO_SEEDED_EFFECT")
        for lab in row["labels"]:
            if lab in out["totals"]:
                out["totals"][lab] += 1
        out["versions"].append(row)
        prev = cur
        prev_snap = snap
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="known-answer positive control for the loop")
    ap.add_argument("--target", required=True)
    ap.add_argument("--workdir", default="")
    ap.add_argument("--only", default="", help="comma-separated defect ids")
    ap.add_argument("--validate-only", action="store_true",
                    help="prove the two invariants and stop, spending no loop time")
    ap.add_argument("--out", default="")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--live", action="store_true", help="drive real agents, not the builtin proposer")
    ap.add_argument("--run-id", default="calib")
    ap.add_argument("--loop-timeout", type=float, default=36000.0)
    a = ap.parse_args(argv)

    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    defects = load_defects(only)
    workdir = a.workdir or tempfile.mkdtemp(prefix="sie-calibrate-")
    os.makedirs(workdir, exist_ok=True)

    t0 = time.time()
    rep = validate(a.target, defects, workdir)
    rep["seconds"] = round(time.time() - t0, 1)
    rep["workdir"] = workdir
    usable = [r["id"] for r in rep["defects"] if r["usable"]]
    rep["usable"] = usable
    rep["usable_count"] = len(usable)
    rep["total"] = len(defects)

    print("calibration validate: %d/%d defect specs are usable (%.0fs)"
          % (len(usable), len(defects), rep["seconds"]))
    for r in rep["defects"]:
        if not r["usable"]:
            print("  UNUSABLE %-28s %s" % (r["id"], r["why"][:150]))
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print("report: %s" % a.out)
    if a.validate_only:
        return 0 if usable else 2
    if not usable:
        return 2

    # THE EXPERIMENT. One tree carrying every usable defect at once, because that is the shape a real
    # codebase has: many latent faults, no marker saying which file is interesting. Seeding them one
    # per run would hand the loop a hint it never gets in production.
    seeded = os.path.join(workdir, "run")
    keep = [d for d in defects if d["id"] in set(usable)]
    seed_copy(a.target, keep, seeded)

    # Re-prove both invariants on the COMBINED tree. They were proven one defect at a time; twenty
    # together could interact, and an experiment whose baseline silently went red would report a
    # repair rate that means nothing.
    comb_rc, comb_tail = run_suite(seeded)
    rep["combined_suite_rc"] = comb_rc
    rep["combined_suite_tail"] = comb_tail
    if comb_rc != 0:
        raise CalibrationError("with all %d defects seeded together the target's own suite goes red "
                               "(rc=%s), so the combined baseline is invalid: %s"
                               % (len(keep), comb_rc, comb_tail))
    pre = score(seeded, keep)
    rep["pre_run_score"] = pre
    if pre["repaired"]:
        raise CalibrationError("these oracles already pass on the freshly seeded tree, so they are "
                               "not measuring their defect: %s" % ", ".join(pre["repaired"]))

    rep["loop"] = run_loop(seeded, a.run_id, a.rounds, a.live, a.loop_timeout)
    rep["events"] = read_events(seeded, a.run_id)

    # Write what we have BEFORE anything downstream is allowed to raise. "The loop accepted nothing,
    # so there is no accepted state to grade" is a correct refusal, but as written it also threw away
    # the record of the eight rounds that had just run: which phases rejected, why, and the loop's own
    # stderr. Refusing to produce a NUMBER and refusing to produce a RECORD are different things, and
    # only the first was intended.
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    # Attribute every accepted decision BEFORE grading the final tree, and independently of whether
    # grading is even possible. A run that accepted nothing still has a story worth recording.
    try:
        rep["attribution"] = attribute_decisions(seeded, a.run_id, keep)
    except CalibrationError:
        raise
    except Exception as e:
        rep["attribution"] = {"error": "%s: %s" % (type(e).__name__, e)}
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    graded = scoring_root(seeded, a.run_id)
    rep["graded_tree"] = graded

    # The sandbox must have STARTED defective, and this asks git rather than the oracles. The
    # tempting check, "if every oracle passes the sandbox was clean", fires on the single best
    # outcome the experiment can produce, so it would call a loop that repaired all twenty a harness
    # fault. Reading the sandbox's own base commit is exact and cannot be confused with success.
    rep["sandbox_base_carried_defects"] = check_sandbox_baseline(graded, keep)
    post = score(graded, keep)
    rep["post_run_score"] = post
    rep["repaired_count"] = len(post["repaired"])
    rep["repair_rate"] = round(len(post["repaired"]) / float(len(keep)), 3)

    # Did the loop break anything while it was in there? A repair rate reported without this is half
    # a result: a loop that fixes four defects and breaks the suite is not working.
    after_rc, after_tail = run_suite(graded)
    rep["suite_after_loop_rc"] = after_rc
    rep["suite_after_loop_tail"] = after_tail

    # Pre-registered, written before the run: below 4 of 20 means the loop is broken and every later
    # design step is premature. Recorded in the report so the threshold cannot be moved afterward.
    rep["prereg_threshold"] = 4
    rep["verdict"] = ("WORKS" if len(post["repaired"]) >= 4 else "BROKEN")

    att = rep.get("attribution") or {}
    tot = att.get("totals") or {}
    print("")
    if tot:
        print("accepted decisions: %d REPAIR, %d no-seeded-effect, %d REGRESSION (of %d "
              "accepted). 'no seeded effect' means none of the 21 seeded oracles moved; it is NOT "
              "a judgement that the change was worthless."
              % (tot.get("REPAIR", 0), tot.get("NO_SEEDED_EFFECT", 0), tot.get("REGRESSION", 0),
                 att.get("n_accepted", 0)))
    print("calibration run: repaired %d/%d (%.0f%%), loop ran %ds, suite after loop rc=%s"
          % (len(post["repaired"]), len(keep), 100 * rep["repair_rate"],
             rep["loop"]["run_seconds"], after_rc))
    print("  events: rounds=%s accepted=%s static_rejected=%s rejected=%s"
          % (rep["events"]["rounds_seen"], rep["events"]["accepted"],
             rep["events"]["static_rejected"], rep["events"]["rejected"]))
    for i in post["repaired"]:
        print("  REPAIRED  %s" % i)
    for e in post["oracle_errors"]:
        print("  ORACLE-ERR %s (%s)" % (e["id"], e["why"]))
    print("  verdict: %s (pre-registered threshold %d)" % (rep["verdict"], rep["prereg_threshold"]))
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CalibrationError as e:
        print("calibrate: %s" % e, file=sys.stderr)
        sys.exit(2)
