#!/usr/bin/env python3
"""load_budget: the mechanism behind PHILOSOPHY P7.

P7 says SKILL.md carries the RULE and its test while references carry the rationale, the signature
and the war-story, and that **the same sentence never appears in both**. That is a principle, and a
principle with no mechanism decays (P2: mechanisms, not intentions). This is the mechanism.

WHAT IT MEASURES
    SKILL.md is paid for on every invocation; reference docs are paid for only when read. So the
    number that matters is not repo size, it is:
      1. how many lines are always loaded, and
      2. how much of that is prose that ALSO lives in an on-demand reference.

    (2) is the real defect. Two copies drift, and the copy a future reader trusts is whichever one
    they happened to open. It is detected with word shingles: a run of N consecutive words appearing
    in both SKILL.md and a reference is duplicated prose, not a coincidence.

WHAT IT DELIBERATELY DOES NOT FLAG
    Having many reference files. A directory of small, densely specific docs is healthy when each is
    loaded only by the run that needs it. The audit that motivated P7 went looking for bloat in a
    33-file tool directory and found layering instead. **Count what a run loads, not what the repo
    contains.**

    Short shared phrases. A rule's own wording legitimately appears in the reference that elaborates
    it. The shingle length is set so that only sustained prose overlap trips the gate.

EXIT CODES
    0  within budget
    1  over budget (used by hooks / CI)
    3  NOTHING WAS MEASURED. This is a failure, not a state.

WHY THE ALWAYS-LOADED HALF NOW BLOCKS (it used to be incapable of failing)
    This tool measures two things and, until now, only ONE of them could ever return nonzero.
    `dup_pct` over `--max-dup` set `failed`. `always_loaded_lines` set nothing at all: over
    ALWAYS_LOADED_WARN it printed a note and the row still read "[   ok]". So the gate whose name and
    docstring both lead with "the always-loaded budget" had no always-loaded budget in it. A SKILL.md
    could grow without bound forever and this tool would keep printing ok, which is worse than not
    measuring it, because the ok is read as a verdict.
    ALWAYS_LOADED_MAX is the half that bites. The ladder is deliberate and both rungs are reported
    differently: WARN is "look at this", MAX is "this stopped being a budget".
    Where the numbers come from, measured 2026-08-27 across the 30 skills on this machine: the
    largest always-loaded SKILL.md is 412 lines, the second 406, and everything else is under 370.
    WARN sits at 450, just above the real distribution, so it fires on the first file that leaves the
    pack. MAX sits at 600, which no skill here is within 180 lines of, so it cannot fire by accident
    on today's fleet and can only be reached by a file that genuinely stopped being budgeted. Raise
    either only with a reason recorded in CHANGELOG, and never by editing the call site to ignore it.

WHY "ZERO SHINGLES" AND "ZERO REFERENCES" ARE REPORTED, NOT ROUNDED TO CLEAN
    dup_pct is a ratio, and a ratio has two ways to come out 0.00%: nothing was duplicated, or
    nothing was compared. Those are opposite facts and this tool used to print the same "ok" for
    both. A repo with no reference docs has an empty `refs` list, the comparison loop runs zero
    times, and the row read exactly like a repo whose prose had been checked and found clean.
    So: no references at all is reported as NOT CHECKED rather than as 0.00% (it is not a failure,
    a single-file skill legitimately has nothing to duplicate into), and a SKILL.md that yields ZERO
    shingles is a BLOCK, because a file too short to produce one 8-word run of prose is empty,
    truncated or unreadable, and nothing was measured about it in either half.

WHY "NOTHING TO MEASURE" IS A FAILURE (and used to be a quiet success)
    This tool shipped knowing exactly one repo shape, skills/<name>/SKILL.md. Two repos in this
    fleet keep their single SKILL.md at the repo ROOT instead, and those two happen to hold the
    third and fifth largest always-loaded files on the machine. In both of them the tool printed
    "no SKILL.md found, nothing to measure" and exited 2, which the docstring itself blessed as
    "a state, not a failure". So the gate built to measure the always-loaded budget reported a
    clean, deliberate-looking result on the files most over that budget.
    That is the fleet's signature defect: a gate that reassures. Both halves are fixed here. The
    root layout is now discovered (see skill_md_paths), and finding nothing to measure exits 3,
    because a tool vendored into a skill repo that locates no skill has failed to do its job, no
    matter how calmly it says so. Exit code 2 is retired rather than redefined: a caller that
    special-cased 2 as benign must break loudly rather than keep quietly agreeing.
"""

import argparse
import glob
import json
import os
import re
import sys

# Tunables. Deliberately generous: this gate exists to catch a paragraph pasted into two files,
# not to police wording. Raise DUP_PCT_MAX only with a reason recorded in CHANGELOG.
SHINGLE_N = 8          # consecutive words; shorter than this matches ordinary phrasing
DUP_PCT_MAX = 2.0      # % of SKILL.md shingles that may also appear in a reference
ALWAYS_LOADED_WARN = 450   # lines in SKILL.md; advisory, prints a note, does not block
ALWAYS_LOADED_MAX = 600    # lines in SKILL.md; BLOCKS. See the docstring for where 450/600 come from.

_FENCE = re.compile(r"```.*?```", re.S)
_TABLE = re.compile(r"^\s*\|.*\|\s*$", re.M)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_PUNCT = re.compile(r"[`*_#>]")


def shingles(text, n=SHINGLE_N):
    """Word shingles over PROSE only.

    Code fences, tables and link targets are stripped first: those are structured data that is
    supposed to be repeated (a command, a slug, a column header), and counting them would make the
    gate fire on correctness rather than on duplication.
    """
    text = _FENCE.sub(" ", text)
    text = _TABLE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _PUNCT.sub(" ", text)
    words = [w for w in re.split(r"\s+", text.lower()) if w and not re.fullmatch(r"[\W\d_]+", w)]
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def is_template(path):
    """Templates and fixtures legitimately restate the rule they produce.

    A `criteria_template.md` that the buyer fills in will contain the very question SKILL.md mandates
    asking; a report template contains the sentence the report must say. That is the artifact of the
    rule, not a second copy of the prose, and neither side should be cut. Excluding them keeps the
    gate pointed at the defect it exists to catch.

    (Added only after every repo already passed without it, so it could not be mistaken for tuning
    the threshold to fit the work.)
    """
    n = os.path.basename(path).lower()
    return "template" in n or "fixture" in n or "_example" in n or n.endswith(".example.md")


def skill_md_paths(root):
    """Every SKILL.md a repo ships, in BOTH layouts this fleet actually uses.

    skills/<name>/SKILL.md is the multi-skill layout. A repo shipping exactly one skill puts its
    SKILL.md at the repo ROOT instead. Knowing only the first shape is what made this tool silent on
    the second, so the two are discovered together and nothing chooses between them.

    Same resolution as check_conformance.skill_md_paths(). Kept deliberately identical: two gates
    disagreeing about which files are always loaded is how a file ends up governed by neither.
    """
    out = sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md")))
    r = os.path.join(root, "SKILL.md")
    if os.path.isfile(r):
        out.append(r)
    return out


def ships_a_skill(root):
    """Does this repo claim to be a skill repo at all?

    Only used to word the exit-3 message. It never converts the failure into a pass: a repo that
    ships no skill and still carries this tool is a vendoring mistake to correct, not a result to
    accept, and either way nothing was measured.
    """
    return (os.path.isfile(os.path.join(root, ".claude-plugin", "plugin.json"))
            or os.path.isdir(os.path.join(root, "skills")))


def audit(skill_md):
    base = os.path.dirname(skill_md)
    refs = sorted(
        p for p in glob.glob(os.path.join(base, "**", "*.md"), recursive=True)
        if os.path.basename(p) != "SKILL.md" and not is_template(p)
    )
    s_text = read(skill_md)
    s_sh = shingles(s_text)
    per_ref, dup = [], set()
    for r in refs:
        common = s_sh & shingles(read(r))
        if common:
            dup |= common
            per_ref.append((len(common), os.path.relpath(r, base), sorted(common, key=len, reverse=True)[:2]))
    per_ref.sort(reverse=True)
    # Reference-to-reference duplication. The SKILL.md comparison above cannot see a paragraph that
    # lives in two references and in neither always-loaded file, yet that drifts exactly the same way
    # (observed: one template line in three files at once, the third copy found only by hand).
    # Inverted index rather than pairwise, so 200+ references stay cheap.
    owners = {}
    for r in refs:
        for sg in shingles(read(r)):
            owners.setdefault(sg, set()).add(os.path.relpath(r, base))
    pairs = {}
    for sg, who in owners.items():
        if len(who) > 1:
            pairs.setdefault(tuple(sorted(who))[:2], 0)
            pairs[tuple(sorted(who))[:2]] += 1
    cross = sorted(((c, p) for p, c in pairs.items() if c >= 12), reverse=True)

    # Was the duplication half actually able to run? Two separate ways for it to be a no-op, and
    # neither may be rendered as 0.00% clean:
    #   no shingles  -> SKILL.md produced no measurable prose at all. Nothing was measured, period.
    #   no refs      -> there was no second file for prose to be duplicated INTO. Legitimate, but
    #                   "not checked", not "checked and clean".
    return {
        "skill_md": skill_md,
        "always_loaded_lines": s_text.count("\n") + 1,
        "shingles": len(s_sh),
        "dup_shingles": len(dup),
        "dup_pct": round(100.0 * len(dup) / max(1, len(s_sh)), 2),
        "measured": bool(s_sh),
        "dup_checked": bool(s_sh) and bool(refs),
        "ref_count": len(refs),
        "ref_lines": sum(read(r).count("\n") + 1 for r in refs),
        "offenders": per_ref[:5],
        "cross_ref": cross[:4],
    }


def main():
    ap = argparse.ArgumentParser(description="PHILOSOPHY P7 gate: always-loaded budget + cross-file prose duplication.")
    ap.add_argument("root", nargs="?", default=".", help="repo root, or a directory of repos with --scan-all")
    ap.add_argument("--scan-all", action="store_true", help="treat root as a parent dir and audit every skill repo under it")
    ap.add_argument("--max-dup", type=float, default=DUP_PCT_MAX)
    ap.add_argument("--max-lines", type=int, default=ALWAYS_LOADED_MAX,
                    help="hard cap on always-loaded SKILL.md lines; over this BLOCKS (exit 1). "
                         "This is the half that used to be incapable of failing.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.scan_all:
        targets = []
        kids = sorted(os.listdir(args.root)) if os.path.isdir(args.root) else []
        for entry in kids:
            child = os.path.join(args.root, entry)
            if os.path.isdir(child):
                targets += skill_md_paths(child)
    else:
        targets = skill_md_paths(args.root)
    if not targets:
        # Say what was looked for, where, and that the run FAILED. The old wording ("nothing to
        # measure") described the tool's state; what the operator needs is the consequence.
        root = os.path.abspath(args.root)
        print("load_budget: FAIL, measured NOTHING under %s" % root)
        print("  looked for: skills/*/SKILL.md and SKILL.md at the root%s"
              % (" of every immediate subdirectory" if args.scan_all else ""))
        if args.scan_all or ships_a_skill(args.root):
            print("  This repo is a skill repo, so finding no SKILL.md is a defect in the repo or in")
            print("  this resolution, not a clean result. Nothing was measured; nothing is cleared.")
        else:
            print("  This repo declares no skill (no .claude-plugin/plugin.json, no skills/, no root")
            print("  SKILL.md), so load_budget has nothing here to guard. Drop tools/load_budget.py")
            print("  from it rather than letting an inert gate report a result.")
        return 3

    results = [audit(t) for t in targets]
    if args.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))

    failed = False
    for r in results:
        # abspath first: for the root layout dirname("./SKILL.md") is ".", and a report whose every
        # row is named "." tells the reader nothing about which file was measured.
        name = os.path.basename(os.path.abspath(os.path.dirname(r["skill_md"])))
        over = r["dup_checked"] and r["dup_pct"] > args.max_dup
        over_lines = r["always_loaded_lines"] > args.max_lines
        unmeasured = not r["measured"]
        bad = over or over_lines or unmeasured
        failed |= bad
        flag = "BLOCK" if bad else "ok"
        # The duplication column has to distinguish "0.00% because nothing matched" from "0.00%
        # because there was nothing to match against". Same number, opposite meanings.
        if not r["measured"]:
            dup_col = "dup NOT MEASURED (0 shingles)"
        elif not r["dup_checked"]:
            dup_col = f"dup NOT CHECKED (0 refs, {r['shingles']} shingles)"
        else:
            dup_col = f"dup {r['dup_pct']:>5.2f}% ({r['dup_shingles']}/{r['shingles']})"
        if not args.json:
            print(f"[{flag:>5}] {name:<26} always-loaded {r['always_loaded_lines']:>4} lines | "
                  f"{dup_col} | "
                  f"{r['ref_count']} refs, {r['ref_lines']} on-demand lines")
            if unmeasured:
                print(f"          MEASURED NOTHING: {r['skill_md']} yielded no {SHINGLE_N}-word run of prose.")
                print(f"          A SKILL.md that short is empty, truncated or unreadable. Neither half of this")
                print(f"          gate examined it, so nothing about it has been cleared. Exit 1, not exit 0.")
            if over_lines:
                print(f"          BLOCK: always-loaded budget exceeded. {r['always_loaded_lines']} lines > "
                      f"cap {args.max_lines}, over by {r['always_loaded_lines'] - args.max_lines}.")
                print(f"          file: {r['skill_md']}")
                print(f"          Every invocation of this skill pays for all {r['always_loaded_lines']} lines. Move the "
                      f"parts only SOME runs need")
                print(f"          into a reference doc and leave a pointer (P7). Raising --max-lines is not the fix.")
            elif r["always_loaded_lines"] > ALWAYS_LOADED_WARN:
                print(f"          note: SKILL.md is large ({r['always_loaded_lines']} lines, warn at "
                      f"{ALWAYS_LOADED_WARN}, block at {args.max_lines}). Not a failure by itself, but check")
                print(f"          whether any of it is only needed by SOME runs (P7).")
            if not r["dup_checked"] and r["measured"]:
                print(f"          note: 0 reference docs, so the duplication half compared nothing. Legitimate for "
                      f"a single-file skill, but NOT a clean duplication result.")
            if over:
                for count, ref, samples in r["offenders"]:
                    print(f"          +{count:<4} shared with {ref}")
                    for s in samples:
                        print(f"                \"{s[:96]}\"")
                print("          fix: keep the RULE in SKILL.md, move the rationale/war-story to the reference, "
                      "and leave a pointer. Do not paste both.")
                print("          NOTE: this measures overlap, not DIRECTION. Decide per hit which side defers. "
                      "A rule restated inside a reference means the REFERENCE should point back.")
            for count, pair in r["cross_ref"]:
                print(f"          note: +{count} shared between {pair[0]} and {pair[1]} "
                      f"(reference-to-reference, advisory only)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
