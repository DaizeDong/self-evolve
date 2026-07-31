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
    2  nothing to measure (no SKILL.md found) -- a state, not a failure
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
ALWAYS_LOADED_WARN = 450   # lines in SKILL.md; a warning, never a block

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

    return {
        "skill_md": skill_md,
        "always_loaded_lines": s_text.count("\n") + 1,
        "shingles": len(s_sh),
        "dup_shingles": len(dup),
        "dup_pct": round(100.0 * len(dup) / max(1, len(s_sh)), 2),
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
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.scan_all:
        targets = sorted(glob.glob(os.path.join(args.root, "*", "skills", "*", "SKILL.md")))
    else:
        targets = sorted(glob.glob(os.path.join(args.root, "skills", "*", "SKILL.md")))
    if not targets:
        print("load_budget: no SKILL.md found, nothing to measure")
        return 2

    results = [audit(t) for t in targets]
    if args.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))

    failed = False
    for r in results:
        name = os.path.basename(os.path.dirname(r["skill_md"]))
        over = r["dup_pct"] > args.max_dup
        failed |= over
        flag = "BLOCK" if over else "ok"
        if not args.json:
            print(f"[{flag:>5}] {name:<26} always-loaded {r['always_loaded_lines']:>4} lines | "
                  f"dup {r['dup_pct']:>5.2f}% ({r['dup_shingles']}/{r['shingles']}) | "
                  f"{r['ref_count']} refs, {r['ref_lines']} on-demand lines")
            if r["always_loaded_lines"] > ALWAYS_LOADED_WARN:
                print(f"          note: SKILL.md is large. Not a failure by itself, but check whether any of it "
                      f"is only needed by SOME runs (P7).")
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
