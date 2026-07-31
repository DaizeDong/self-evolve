#!/usr/bin/env python3
"""dash_guard: flag / fix en-dash and em-dash used as prose in a public repo.

House rule (user global): published prose carries NO en/em dash. The ASCII hyphen `-` is left
ALONE (it is code syntax: identifiers, flags, file names, versions, URLs, ranges in code), so this
guard only touches the en-dash U+2013, em-dash U+2014 and horizontal bar U+2015. None of those
three ever appear in code SYNTAX, so every occurrence outside a code span is prose and is a target.

Modes (exactly one action):
  --check  (default) print every offending file:line; exit 1 if any (pre-commit / CI gate)
  --fix              rewrite the offending files in place. NOT a gate: see the note at the end of
                     main(). It exits 0 after a successful repair and 1 only for files it could not
                     read, so wiring --fix into CI would install a check that cannot fail.

Exit codes: 0 clean, 1 findings (or, under --fix, unexaminable files), 2 the scan could not run at
all (git unusable / not a work tree). 2 must never be read as 0; see _git.

Target set:
  --staged           the git staged text blobs (pre-commit hook)
  --tree   (default) every git-tracked text file
  paths...           explicit files (overrides the set)

Markdown safety: fenced ``` code blocks and inline `code` spans are skipped, so a dash shown as a
literal example survives. In every other text file each en/em dash is treated as prose.

Replacement (deterministic):
  markdown table cell that is ONLY a dash  -> "none"  (the cell means "no value", not an aside)
  markdown table cell STARTING with a dash -> ASCII "-" (a sub-item marker, not an aside)
  spaced   ` — ` / ` – `                 -> ", "   (appositive / aside; never grammatically wrong)
  ASCII range  A–B  (word char both sides) -> "A to B"  (e.g. T1–T9, 2020–2026)
  any leftover run  —— / – / ―           -> "," glued to the preceding word (never " ,")

Why the table rules exist: a table cell holding a single long dash is the conventional way to write
"no default". Substituting punctuation there produced cells reading "," or ", something", which is
not prose at all, and NO gate can see it afterwards because the output contains no dash. The cell
rules run before the prose rules so a dash that is a value never reaches the appositive rule.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tokenize

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_DASHES = "–—―"          # – — ―
_DASH_RE = re.compile(f"[{_DASHES}]")
# How each extension is processed:
#   "md"    Markdown/rst: full prose de-dash, code fences + inline `code` exempt.
#   "prose" plain text: full prose de-dash, line by line.
#   "py"    Python: de-dash COMMENT tokens ONLY. Every string literal (docstring AND a data literal
#           like re.compile(r"[–—]")) is left untouched, so a functional dash-as-data is never
#           corrupted. Output/display strings are handled by the skill's runtime _inline normalizer,
#           not here.
#   "tmpl"  A generator template, processed as Markdown. This extension exists because a template is
#           the one file whose dashes are invisible twice over: the .tmpl suffix hid it from this map,
#           and the generator that expands it holds the rest of its prose in Python STRING literals,
#           which the "py" rule leaves alone by design. skill-smith therefore reported a clean tree
#           while its CONFIG.md.tmpl carried 22 dashes and every repo it scaffolded was born failing
#           the very gate it vendored. Markdown handling is the right rule even for a non-Markdown
#           template (a systemd unit, a gitignore): those carry no fences and no inline code spans, so
#           md degrades to plain prose on them, while a .md.tmpl keeps its fenced blocks protected.
# Any extension not listed is left completely alone (a mixed prose/data code file we cannot auto-edit
# safely). The rule is enforced on published docs + the .py comment prose; runtime output compliance
# is the renderer's job.
_KIND = {".md": "md", ".markdown": "md", ".rst": "md", ".txt": "prose", ".py": "py",
         ".tmpl": "md"}

_SPACED = re.compile(rf"\s+[{_DASHES}]+\s+")
_RANGE = re.compile(rf"([A-Za-z0-9])[{_DASHES}]+([A-Za-z0-9])")
# The leftover run is matched TOGETHER with the blanks hugging it, so the replacement decides the
# spacing instead of inheriting a stray space and emitting " ,".
_RUN = re.compile(rf"[ \t]*[{_DASHES}]+[ \t]*")

NO_VALUE = "none"                  # what an empty-meaning table cell says (fleet convention)


def _run_sub(m) -> str:
    """Replacement for a dash run that neither the spaced rule nor the range rule claimed.

    Three shapes, all of which used to collapse to a bare "," carrying whatever blank happened to
    sit in front of it:
      "... one thing —"  (hard-wrapped prose, sentence continues next line) -> "... one thing,"
      "foo —bar" / "foo— bar"                                              -> "foo, bar"
      "— foo"  at the very start of the segment (decoration, not an aside)  -> "foo"

    A dash with NO blank on either side ("$2.0B–$4.6B") keeps the old bare comma on purpose: those
    are ranges the range rule cannot claim (it needs a word character on both sides and a currency
    symbol is not one), rendering them is a separate judgement call, and widening the spacing here
    would churn hundreds of lines across the fleet without making any of them correct.
    """
    text, run = m.string, m.group()
    lead, trail = run[:1].isspace(), run[-1:].isspace()
    if not lead and not trail:
        return ","                               # tight dash: unchanged, no gratuitous respacing
    rest = text[m.end():]
    if rest in ("", "\r"):                       # the dash ended the line: glue the comma on
        return ","
    if m.start() == 0 and trail:
        return ""                                # a leading dash is decoration; drop it
    return ", "


def fix_prose(s: str) -> str:
    """Replace en/em dashes in one prose segment. Order matters: spaced separators first (they
    become ', '), then ASCII ranges ('A to B'), then any leftover dash run becomes a comma that is
    glued to the preceding word."""
    s = _SPACED.sub(", ", s)
    s = _RANGE.sub(r"\1 to \2", s)
    s = _RUN.sub(_run_sub, s)
    return s


# --- markdown table cells -------------------------------------------------------------------
# A pipe-table row. Markdown allows up to three leading spaces before the pipe.
_TABLE_ROW = re.compile(r"^ {0,3}\|")
# A cell whose ENTIRE content is a dash run: it means "no value", so it becomes a word.
_CELL_DASH_ONLY = re.compile(rf"(?<=\|)\s*[{_DASHES}]+\s*(?=\||\r?$)")
# A cell that OPENS with a dash run followed by text: a sub-item marker, so it becomes an ASCII
# hyphen (which this guard never touches) and keeps the indent it was drawing.
_CELL_DASH_LEAD = re.compile(rf"(?<=\|)(\s*)[{_DASHES}]+(?=[ \t]\S)")


def fix_table_cells(line: str) -> str:
    """Rewrite dash-as-value cells in one markdown table row, before any prose rule sees them."""
    if not _TABLE_ROW.match(line) or line.count("|") < 2:
        return line

    def _cell(m):
        rest = m.string[m.end():]                       # no trailing pad on the last cell of a row
        return f" {NO_VALUE} " if rest.startswith("|") else f" {NO_VALUE}"

    line = _CELL_DASH_ONLY.sub(_cell, line)
    return _CELL_DASH_LEAD.sub(r"\1-", line)


def _split_md_code(line: str, in_fence: bool):
    """Yield (segment, is_code) for a markdown line, protecting inline `code`. `in_fence` marks a
    line inside a ``` fenced block (entirely code). Returns (segments, new_in_fence)."""
    stripped = line.lstrip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return [(line, True)], (not in_fence)
    if in_fence:
        return [(line, True)], True
    # protect inline code spans (`...`)
    segs, is_code = [], False
    for i, part in enumerate(re.split(r"(`[^`]*`)", line)):
        segs.append((part, part.startswith("`") and part.endswith("`") and len(part) >= 2))
    return segs, False


_ALLOW = "dash-guard: allow"       # a line carrying this marker is left untouched (rare legit dash)


def _process_py(text: str, notes=None):
    """De-dash Python COMMENT tokens ONLY. Every string literal (docstring AND a data literal such as
    re.compile(r"[–—]") or a test fixture) is left untouched, so a functional dash-as-data is never
    corrupted. A line carrying the allow marker is skipped. Unparseable source is left as-is (we never
    blind-edit code we cannot tokenize). Returns (new_text, hits).

    Leaving unparseable source alone is the RIGHT behaviour and is unchanged. What was wrong is that
    it returned the same (text, []) as a genuinely clean file, so a .py file full of dashes that the
    tokenizer choked on counted as examined-and-clean. It now records the reason in `notes`, which
    main() prints and counts, so a clean report can never quietly include a file nobody read."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError) as e:
        if notes is not None:
            notes.append("untokenizable (%s)" % type(e).__name__)
        return text, []
    edits = {}                       # lineno -> (col_of_hash, fixed_comment)
    for tok in toks:
        if tok.type == tokenize.COMMENT and _ALLOW not in tok.line:
            fixed = fix_prose(tok.string)
            if fixed != tok.string:
                edits[tok.start[0]] = (tok.start[1], fixed)
    if not edits:
        return text, []
    lines, hits = text.split("\n"), []
    for lineno, (col, fixed) in edits.items():
        orig = lines[lineno - 1]
        lines[lineno - 1] = orig[:col] + fixed      # a comment always runs to end of line
        hits.append((lineno, orig))
    return "\n".join(lines), hits


def process_text(text: str, kind: str, notes=None):
    """Return (new_text, hits) where hits = list of (lineno, original_line).
    kind: "py" (comments only), "md" (prose, code spans exempt), "prose" (plain text, full).
    notes: optional list; anything appended is a reason this file was not fully examined."""
    if kind == "py":
        return _process_py(text, notes)
    is_md = (kind == "md")
    out_lines, hits, in_fence = [], [], False
    for lineno, line in enumerate(text.split("\n"), 1):
        if _ALLOW in line:
            out_lines.append(line)
            continue
        if is_md:
            # Table cells first: a dash that IS the value must never reach the appositive rule.
            work = line if in_fence else fix_table_cells(line)
            segs, in_fence = _split_md_code(work, in_fence)
            new_parts = []
            for part, is_code in segs:
                new_parts.append(part if is_code else fix_prose(part))
            new_line = "".join(new_parts)
            if new_line != line:
                hits.append((lineno, line))
            out_lines.append(new_line)
        else:
            fixed = fix_prose(line)
            if fixed != line:
                hits.append((lineno, line))
            out_lines.append(fixed)
    return "\n".join(out_lines), hits


class GitError(RuntimeError):
    """A git invocation this run depends on did not succeed. Raised, never swallowed."""


def _git(repo, *a, allow_fail=False):
    """Run a git command and return its stdout.

    THIS USED TO FAIL OPEN: `return r.stdout if r.returncode == 0 else ""`. _tracked() then returned
    an empty list, the scan loop never executed, `total` stayed 0, and main() printed
    "dash_guard: clean" and exited 0 without opening a single file. Every way git can fail -- not a
    repo, an extracted git-archive with no .git, git missing from PATH, an index.lock, a permission
    error -- arrived at that same green result, including in the CI workflow whose entire job is
    running this command.

    So a nonzero exit RAISES, carrying git's own stderr. allow_fail=True returns None instead, and
    is only for calls where failure is an ordinary state rather than a broken environment. None is
    deliberately distinct from "": that still means git succeeded with genuinely empty output (an
    empty staged diff is the normal case and must stay a normal case).
    """
    try:
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except (OSError, ValueError) as e:
        if allow_fail:
            return None
        raise GitError("cannot execute `git %s` in %s: %s\n  (is git installed and on PATH?)"
                       % (" ".join(a), repo, e)) from None
    if r.returncode != 0:
        if allow_fail:
            return None
        raise GitError("`git %s` exited %d in %s\n  %s"
                       % (" ".join(a), r.returncode, repo,
                          (r.stderr or "").strip().replace("\n", "\n  ") or "(no stderr)"))
    return r.stdout


def _eligible(paths):
    return [f for f in paths if os.path.splitext(f)[1].lower() in _KIND]


def _tracked(repo):
    """(all tracked paths, the ones with a de-dashable extension). Both are returned so main can
    tell 'this repo tracks nothing' from 'this repo tracks no markdown/text/python'."""
    all_paths = [f for f in _git(repo, "ls-files").splitlines() if f.strip()]
    return all_paths, _eligible(all_paths)


def _staged(repo):
    out = _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACM")
    all_paths = [f for f in out.splitlines() if f.strip()]
    return all_paths, _eligible(all_paths)


def main() -> int:
    ap = argparse.ArgumentParser(description="en/em dash guard for public repo prose")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--fix", action="store_true", help="rewrite offending files in place")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true")
    g.add_argument("--tree", action="store_true")
    ap.add_argument("paths", nargs="*", help="explicit files (overrides --staged/--tree)")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    enumerated = None                 # how many paths git named, before the extension filter
    source = "paths"
    if args.paths:
        files = args.paths
    elif args.staged:
        source = "staged"
        all_paths, files = _staged(repo)
        enumerated = len(all_paths)
    else:
        source = "tree"
        all_paths, files = _tracked(repo)
        enumerated = len(all_paths)

    # A git repo that enumerates nothing is possible (a fresh init, an empty staged set) but it is
    # NOT the same event as a clean scan, and until now the two printed the same line. Say which.
    if source == "tree" and enumerated == 0:
        print("dash_guard: WARNING %s is a git repo but tracks 0 files -- nothing was examined."
              % repo, file=sys.stderr)
    elif enumerated and not files:
        print("dash_guard: NOTE %d %s path(s), none with a de-dashable extension (%s)."
              % (enumerated, source, " ".join(sorted(_KIND))), file=sys.stderr)

    total = 0
    changed_files = 0
    examined = 0
    # Two different things, kept apart because only one of them is a problem:
    #   excluded  -- we CHOSE not to read this file (the guard's own source, an absent path). A
    #                declared exclusion is a decision, and a decision does not fail a run.
    #   unexamined -- we MEANT to read it and could not (undecodable bytes, source the tokenizer
    #                rejects). The file may be full of dashes and nobody looked. Both are printed;
    #                only this one affects an exit code.
    excluded = []                     # (path, reason)
    unexamined = []                   # (path, reason)
    _self = {"dash_guard.py", "test_dash_guard.py"}   # the guard's own source carries the dash set
    for rel in files:
        path = rel if os.path.isabs(rel) else os.path.join(repo, rel)
        if not os.path.isfile(path):
            excluded.append((rel, "not a file on disk (sparse checkout, or removed)"))
            continue
        if os.path.basename(path) in _self:
            excluded.append((rel, "the guard's own source (contains the dash set by design)"))
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError) as e:
            # Unchanged behaviour: an undecodable or unreadable file is skipped. It is now RECORDED,
            # because "skipped" reported as "clean" is the same class of lie as the git fail-open.
            unexamined.append((rel, "unreadable (%s)" % type(e).__name__))
            continue
        kind = _KIND.get(os.path.splitext(path)[1].lower())
        if kind is None:
            excluded.append((rel, "no de-dash rule for this extension"))
            continue
        examined += 1
        if not _DASH_RE.search(text):
            continue
        notes = []
        new_text, hits = process_text(text, kind, notes)
        for n in notes:                       # e.g. a .py the tokenizer could not parse
            unexamined.append((rel, n))
            examined -= 1
        if not hits:
            continue
        total += len(hits)
        if args.fix:
            if new_text != text:
                open(path, "w", encoding="utf-8", newline="\n").write(new_text)
                changed_files += 1
                print(f"fixed {len(hits):3} {os.path.relpath(path, repo)}")
        else:
            for lineno, line in hits:
                print(f"{os.path.relpath(path, repo)}:{lineno}: {line.strip()[:100]}")

    # Print both lists BEFORE the verdict, in both modes. A file carrying a dash that the tokenizer
    # rejected is exactly the file this guard exists for, and it used to vanish without a word.
    def _report(label, rows):
        if not rows:
            return
        print("dash_guard: %d file(s) %s:" % (len(rows), label), file=sys.stderr)
        for rel, why in rows[:20]:
            print("  %-52s %s" % (rel, why), file=sys.stderr)
        if len(rows) > 20:
            print("  ... and %d more" % (len(rows) - 20), file=sys.stderr)

    _report("deliberately excluded", excluded)
    _report("could NOT be examined", unexamined)

    if args.fix:
        print(f"dash_guard: fixed {total} line(s) across {changed_files} file(s); "
              f"{examined} file(s) examined")
        # --fix is a REPAIR, not a gate, and its exit code is deliberately not a verdict on the
        # tree: it just rewrote the tree, so "0 remaining findings" would be true by construction
        # and would let `dash_guard --fix` be wired into CI as a gate that can never fail. The gate
        # is --check, and only --check. What --fix DOES report nonzero is the one thing it cannot
        # honestly claim to have repaired: files it could not read. Those still hold whatever they
        # held, and a repair run that silently left them behind is the same silent-success bug.
        if unexamined:
            print("dash_guard: --fix could not examine %d file(s) (listed above); re-run --check "
                  "to gate." % len(unexamined), file=sys.stderr)
            return 1
        return 0
    if total:
        print(f"dash_guard: {total} prose en/em dash(es) found (run with --fix)", file=sys.stderr)
        return 1
    # The verdict states its own coverage. "dash_guard: clean" on its own is the identical string
    # whether 400 files were read or none were, which is precisely how the fail-open stayed hidden.
    skipped = len(excluded) + len(unexamined)
    print(f"dash_guard: clean ({examined} file(s) examined"
          + (f", {skipped} skipped)" if skipped else ")"))
    return 0


def cli():
    """main() with the git-failure exit. 0 clean, 1 findings, 2 the scan never ran. Any nonzero is
    a block for the hook and for CI: an unexamined tree is not a clean tree."""
    try:
        return main()
    except GitError as e:
        print("dash_guard: SCAN FAILED -- git could not be used, so NOTHING was examined.\n"
              "  %s\n"
              "  This is not a clean result. Fix git, or point --repo at a real work tree."
              % str(e).replace("\n", "\n  "), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
