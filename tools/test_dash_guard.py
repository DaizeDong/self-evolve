#!/usr/bin/env python3
# dash-guard:scanner-file -- this file carries the dash set by design; see _self_marker
"""Tests for dash_guard.

The reason this file exists: on 2026-07-17 the guard's --fix pass rewrote every markdown table cell
that held a single em dash (the conventional way to write "no default") into a bare comma, producing
99 cells across 7 repos that read ", something" or just ",". Nothing could detect the damage
afterwards, because the output contains no dash for the guard to flag, and the next --fix run would
have recreated it. So the property under test is stated the strong way: a dash-as-value cell must
round-trip to a WORD, and must never round-trip to punctuation.

Run: python test_dash_guard.py     (also collectable by pytest)
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dash_guard as dg  # noqa: E402
from dash_guard import NO_VALUE, fix_prose, fix_table_cells, process_text  # noqa: E402

EM = "—"
EN = "–"

_FAILS = []


def check(got, want, what):
    if got != want:
        _FAILS.append(f"{what}\n     got: {got!r}\n    want: {want!r}")


def md(text):
    """Run the real markdown pipeline (the path --fix takes) and return the rewritten text."""
    return process_text(text, "md")[0]


# --- the regression: a dash-only cell becomes a word, never punctuation ----------------------

def test_dash_only_cell_becomes_a_word():
    row = f"| `health_interval` | str | no | {EM} | `*:0/15` |"
    out = md(row)
    check(out, "| `health_interval` | str | no | none | `*:0/15` |", "dash-only cell -> none")
    # The property, stated so a future rewrite cannot satisfy it with different punctuation.
    for cell in out.split("|"):
        assert cell.strip() != ",", f"cell collapsed to a comma: {out!r}"
        assert not cell.strip().startswith(", "), f"cell opens with a comma: {out!r}"
    assert NO_VALUE.isalpha(), "the empty-cell token must be a word, not punctuation"


def test_dash_only_cell_is_idempotent():
    row = f"| a | {EM} | b |"
    once = md(row)
    check(md(once), once, "second --fix pass must not touch the repaired row")


def test_several_dash_cells_in_one_row():
    check(md(f"| SIFY | fcf_cap | null | {EM} | {EM} | {EM} | False |"),
          "| SIFY | fcf_cap | null | none | none | none | False |", "adjacent dash cells")


def test_trailing_dash_cell_without_closing_pipe():
    check(md(f"| Clean BUYs | **0** | {EM}"), "| Clean BUYs | **0** | none", "trailing cell")


def test_leading_dash_cell_is_a_sub_item_marker():
    check(md(f"| {EM} deep band (<$2.0B) | 109 | resolved |"),
          "| - deep band (<$2.0B) | 109 | resolved |", "leading dash -> ASCII hyphen")


def test_prose_inside_a_cell_still_gets_de_dashed():
    check(md(f"| x | a thing {EM} really | y |"), "| x | a thing, really | y |", "aside in a cell")


def test_delimiter_row_untouched():
    check(md("|---|---:|---|"), "|---|---:|---|", "ASCII hyphens are never touched")


def test_code_span_cell_untouched():
    row = f"| `{EM}` | text |"
    check(md(row), row, "a dash shown as code survives")


def test_dash_cell_inside_a_fence_untouched():
    src = f"```\n| a | {EM} |\n```"
    check(md(src), src, "fenced block is code")


def test_allow_marker_wins():
    row = f"| a | {EM} |  <!-- dash-guard: allow -->"
    check(md(row), row, "allow marker skips the line")


def test_not_a_table_row():
    check(md(f"a | b {EM} c"), "a | b, c", "a pipe in prose is not a table")


# --- the adjacent damage: a leftover dash must not leave a space before the comma ------------

def test_dash_at_end_of_line_glues_the_comma():
    check(fix_prose(f"the bot does exactly one thing {EM}"), "the bot does exactly one thing,",
          "hard-wrapped line ending in a dash")


def test_dash_touching_the_next_word():
    check(fix_prose(f"foo {EM}bar"), "foo, bar", "space only on the left")
    check(fix_prose(f"foo{EM} bar"), "foo, bar", "space only on the right")


def test_leading_dash_in_prose_is_dropped():
    check(fix_prose(f"{EM} continued here"), "continued here", "decorative leading dash")


def test_no_output_ever_contains_space_before_comma():
    for s in (f"a {EM}", f"a {EN}", f"a {EM}{EM}b", f"x {EM} y", f"{EM} z", f"t {EM}\r"):
        out = fix_prose(s)
        assert " ," not in out, f"{s!r} -> {out!r} still has a space before the comma"


def test_a_tight_dash_is_not_respaced():
    """A dash with no blank around it is a range the range rule cannot claim (currency symbols are
    not word characters). Rendering those is a separate call; this guard must not respace them,
    or every re-run churns hundreds of fleet lines for nothing."""
    check(fix_prose(f"$2.0B{EN}$4.6B"), "$2.0B,$4.6B", "currency range keeps its old rendering")
    check(fix_prose(f"8.8x{EN}50.5x"), "8.8x to 50.5x", "plain word chars still become a range")


def test_existing_behavior_preserved():
    check(fix_prose(f"an aside {EM} like this"), "an aside, like this", "spaced aside")
    check(fix_prose(f"2020{EN}2026"), "2020 to 2026", "numeric range")
    check(fix_prose(f"T1{EN}T9"), "T1 to T9", "identifier range")
    check(fix_prose("nothing to do"), "nothing to do", "clean text untouched")


def test_python_comments_only():
    src = f'x = "{EM}"  # an aside {EM} here\n'
    out = process_text(src, "py")[0]
    assert f'"{EM}"' in out, "a dash inside a string literal must survive"
    assert "an aside, here" in out, f"comment not de-dashed: {out!r}"


# --- the enumeration fail-open ---------------------------------------------------------------
# Until 2026-07-30 `_git` returned "" whenever git exited nonzero. `_tracked()` then returned an
# empty list, the scan loop never executed, `total` stayed 0, and main() printed "dash_guard: clean"
# and exited 0 having opened no file. A directory that is not a repo, a git-archive extraction, git
# missing from PATH, an index.lock and a permission error all landed on that same green result --
# including in the vendored CI workflow, whose entire job is running this command. These tests fail
# if that comes back.

class _TmpDir:
    """A temp directory that is guaranteed NOT to be inside a git repo. Plain stdlib so this file
    still runs as a script without pytest."""

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix="dashguard-test-")
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def _inside_a_repo(d):
    return subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                          capture_output=True).returncode == 0


def _guard(args, cwd, env_overrides=None):
    env = dict(os.environ)
    env.update(env_overrides or {})
    return subprocess.run([sys.executable, dg.__file__] + args, cwd=cwd,
                          capture_output=True, text=True, env=env)


def _git(cwd, *a):
    subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True)


def test_a_failed_git_call_raises_instead_of_returning_empty():
    try:
        dg._git(os.getcwd(), "definitely-not-a-subcommand")
    except dg.GitError as e:
        assert "definitely-not-a-subcommand" in str(e), f"git's own error is not carried: {e}"
    else:
        raise AssertionError("a failing git call returned normally: that is the fail-open")


def test_allow_fail_returns_none_and_a_real_empty_output_stays_empty_string():
    assert dg._git(os.getcwd(), "definitely-not-a-subcommand", allow_fail=True) is None
    with _TmpDir() as d:
        _git(d, "init", "-q")
        assert dg._git(d, "ls-files") == "", "a SUCCESSFUL git call with no output must be ''"


def test_a_non_repo_directory_is_not_reported_clean():
    """THE REGRESSION. Before the fix this exited 0 printing 'dash_guard: clean'."""
    with _TmpDir() as d:
        if _inside_a_repo(d):
            return                                    # cannot construct the failure here
        p = _guard(["--tree", "--repo", "."], d)
        assert p.returncode != 0, f"a non-repo reported success: {p.stdout!r}"
        assert "clean" not in p.stdout, p.stdout
        assert "SCAN FAILED" in p.stderr, p.stderr


def test_an_exported_tree_with_no_git_dir_is_not_reported_clean():
    """A git-archive extraction: real files, no .git. Grading it clean is a lie about coverage."""
    with _TmpDir() as d:
        if _inside_a_repo(d):
            return
        with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
            f.write(f"an aside {EM} here\n")
        p = _guard(["--tree", "--repo", "."], d)
        assert p.returncode != 0 and "clean" not in p.stdout, p.stdout


def test_git_missing_from_path_is_not_reported_clean_and_is_not_a_traceback():
    with _TmpDir() as d:
        empty = os.path.join(d, "nothing-on-path")
        os.mkdir(empty)
        p = _guard(["--tree", "--repo", "."], d, {"PATH": empty, "GIT_EXEC_PATH": empty})
        assert p.returncode != 0 and "clean" not in p.stdout, p.stdout
        assert "SCAN FAILED" in p.stderr and "Traceback" not in p.stderr, p.stderr


def test_a_repo_tracking_zero_files_says_so():
    """Legitimate (a fresh init), so still exit 0 -- but it must not read like a scan that ran."""
    with _TmpDir() as d:
        _git(d, "init", "-q")
        p = _guard(["--tree", "--repo", "."], d)
        assert p.returncode == 0, p.stderr
        assert "tracks 0 files" in p.stderr, p.stderr


def test_a_clean_report_states_how_many_files_were_examined():
    with _TmpDir() as d:
        _git(d, "init", "-q")
        with open(os.path.join(d, "a.md"), "w", encoding="utf-8") as f:
            f.write("nothing to do\n")
        _git(d, "add", "a.md")
        p = _guard(["--tree", "--repo", "."], d)
        assert p.returncode == 0 and "1 file(s) examined" in p.stdout, p.stdout


def test_a_python_file_the_tokenizer_rejects_is_reported_not_silently_clean():
    """_process_py leaves unparseable source alone -- correct, and unchanged. What was wrong is
    that it returned the same (text, []) as a clean file, so a .py full of dashes that failed to
    tokenize was counted as examined and clean."""
    notes = []
    src = f"def f(:\n    # an aside {EM} here\n"
    out, hits = process_text(src, "py", notes)
    check(out, src, "unparseable source is still left untouched")
    assert hits == [], "no hits can be reported from a file that was never tokenized"
    assert notes and "untokenizable" in notes[0], f"the skip was not recorded: {notes!r}"
    with _TmpDir() as d:
        _git(d, "init", "-q")
        with open(os.path.join(d, "broken.py"), "w", encoding="utf-8") as f:
            f.write(src)
        _git(d, "add", "broken.py")
        p = _guard(["--tree", "--repo", "."], d)
        assert "untokenizable" in p.stderr, p.stderr
        assert "could NOT be examined" in p.stderr, p.stderr
        assert "1 skipped" in p.stdout, "the verdict must state its own coverage: %r" % p.stdout


def test_fix_stays_zero_for_a_deliberate_exclusion():
    """A DECLARED exclusion (the guard's own source) is a decision, not a coverage gap, and must not
    turn every --fix run in every repo red. The split between 'excluded' and 'could not be examined'
    is what keeps the nonzero below meaningful."""
    with _TmpDir() as d:
        _git(d, "init", "-q")
        for name in ("dash_guard.py", "a.md"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("nothing to do\n")
        _git(d, "add", "-A")
        p = _guard(["--fix", "--tree", "--repo", "."], d)
        assert p.returncode == 0, f"a declared exclusion failed the repair run: {p.stderr!r}"
        assert "deliberately excluded" in p.stderr, p.stderr


def test_fix_reports_nonzero_when_it_could_not_examine_a_file():
    """--fix is a repair, not a gate: after rewriting the tree its own 'no findings' is true by
    construction. The one thing it CAN honestly fail on is a file it never read."""
    with _TmpDir() as d:
        _git(d, "init", "-q")
        with open(os.path.join(d, "broken.py"), "w", encoding="utf-8") as f:
            f.write(f"def f(:\n    # an aside {EM} here\n")
        _git(d, "add", "broken.py")
        p = _guard(["--fix", "--tree", "--repo", "."], d)
        assert p.returncode != 0, f"--fix hid an unexaminable file: {p.stdout!r}"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    errors = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            errors += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:                        # a test that ERRORS is a failed test
            errors += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    for f in _FAILS:
        errors += 1
        print(f"FAIL {f}")
    print(f"dash_guard tests: {len(tests)} run, {errors} failure(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
