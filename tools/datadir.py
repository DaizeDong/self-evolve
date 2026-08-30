#!/usr/bin/env python3
"""datadir -- where a skill's REAL-RUN OUTPUT goes. Never the repo.

These skills already had a private-companion-config boundary, and it worked. But it only ever
covered INPUTS: the credentials, the mailboxes, the account slugs. Nothing covered OUTPUTS -- what
the skill LEARNED from a real run. So a forward-tracking tool appended the operator's actual research
verdicts (one row per decision, hundreds of them) to a git-tracked `metrics/*.jsonl`, and another
skill's ledger recorded what was bought and where it shipped -- straight into public repos, on every
run, by design.

No content scanner catches that. There is no email in it, no phone, no ZIP. It is just the
operator's life, correctly formatted. The fix is not a better sieve, it is a pipe that does not
point at the public repo in the first place.

  resolve_data_dir("small-cap-deepdive")  ->  the private directory, or None

Discovery order (first existing wins):
  1. $<SKILL>_DATA_DIR                       explicit override / hot-swap
  2. $<SKILL>_CONFIG / $<SKILL>_CONFIG_DIR   the PRIVATE COMPANION REPO, wherever it is pinned:
                                             <config>/data/ when that exists, else <config> itself
  3. ~/.<skill>-config/data/                 the same companion repo at its default dotfile path
  4. ~/.<skill>-data/                        standalone fallback
  5. None                                    -> the tool is UNINITIALIZED, which is exactly what a
                                                freshly cloned public skill SHOULD be

WHY STEP 2 EXISTS (added 2026-07-31)
------------------------------------
Every skill in this fleet already resolves its private companion repo from `$<SKILL>_CONFIG`, and
several of those repos have been pinned somewhere other than the dotfile path (`$MARKET_INTEL_CONFIG`
and `$DAILY_HOTSPOTS_CONFIG` both point into ~/CodesClaude). This resolver did not know that, so it
looked only at the dotfile path, found nothing, and answered None -- "uninitialized" -- for skills
that were writing a real ledger every day. An out-of-band control then asked THIS function where the
data was, got None, and reported the skill as nothing-to-check. A checker that is told nothing
reports a clean sheet, which is the failure mode the whole data boundary exists to avoid. The
resolver now follows the same pointer the skill itself follows.

PRIVATE COMPANION REPO IS THE DESTINATION, NOT AN ACCIDENT
----------------------------------------------------------
Real-run output LIVES IN the private companion repo, versioned and backed up like everything else
there. The rule was never "data must not be in git" -- it is "data must never be in a PUBLIC repo,
and a public repo never has an in-repo fallback". Those are different predicates and conflating them
condemns the correct shape: a private repo is exactly where a person's real data legitimately lives.

WHY THIS FILE DOES NOT CHECK VISIBILITY ITSELF
----------------------------------------------
The tempting next step is to have this function refuse a data dir that sits in a PUBLIC repo. It
cannot do that honestly. This file is vendored into every public skill repo, is stdlib-only by
contract, and has to work on a fresh clone on a stranger's machine: no ~/.pii-guard/visibility.json,
no `gh`, possibly no network. Fail-closed there bricks every fresh clone on a question that has no
local answer; fail-open makes the assertion decorative precisely where it matters. So the visibility
predicate stays OUT OF BAND, in the fleet checker that does have the map.

What this file CAN assert with no map, no network and no git binary is strictly weaker and always
true: a skill's data dir is never inside the skill's OWN repo. Public or private, the tool repo and
the companion repo are two different repos, and a data dir that resolved into this one is either an
in-repo fallback or a misconfigured pointer -- the exact shape that put a real SEC contact email in
a public repo under the label "legacy fallback". That one is checked here, and it raises.

`data_path()` raises a DataDirNotInitialized with instructions rather than silently falling back to a
path inside the repo. A silent in-repo fallback is how this happened: `reference/config.json` was the
documented "legacy fallback", and the operator's real SEC contact email ended up committed in it.
A fallback into the repo is not a convenience, it is the leak.

Vendored into each skill as `tools/datadir.py`. Stdlib only.
"""
import os
from pathlib import Path


class DataDirNotInitialized(RuntimeError):
    pass


class DataDirInsideOwnRepo(RuntimeError):
    """The resolved data dir is inside the skill repo that ships this file. Always a defect."""


def _env_var(skill):
    return skill.upper().replace("-", "_") + "_DATA_DIR"


def _config_env_vars(skill):
    stem = skill.upper().replace("-", "_")
    return (stem + "_CONFIG", stem + "_CONFIG_DIR")


def _own_repo_root():
    """The git worktree containing THIS file, or None.

    Walks parents looking for `.git`. Deliberately does not shell out: this runs inside live skills
    on machines where git may be absent, and a probe that can fail open is not a check.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _reject_if_inside_own_repo(p, skill):
    root = _own_repo_root()
    if root is None:
        return                       # not deployed from a worktree; nothing to be inside of
    try:
        target, repo = os.path.realpath(str(p)), os.path.realpath(root)
    except OSError:
        return
    # normcase for the COMPARISON only; the message keeps the real casing so it is greppable.
    t, r = os.path.normcase(target), os.path.normcase(repo)
    # The separator is load-bearing: `<root>-config` must NOT count as inside `<root>`, and the
    # companion repo is named exactly that way in every skill in this fleet.
    if t == r or t.startswith(r + os.sep):
        raise DataDirInsideOwnRepo(
            "%s resolved its data dir to %s, which is INSIDE its own repo %s.\n"
            "Real-run output belongs in the PRIVATE COMPANION repo, never in the tool repo.\n"
            "Repoint it:\n"
            "    set %s to the companion repo (its data/ subdir is used when present)\n"
            "    or set %s to an explicit private directory"
            % (skill, target, repo, _config_env_vars(skill)[0], _env_var(skill)))


def _convention_roots(skill):
    """The fleet convention: a skill's companion repo is its SIBLING, named `<skill>-config`.

    Every companion repo in this fleet already follows this. Nothing looked for it, and that
    was the whole defect. Discovery depended entirely on a per-skill environment variable, so
    the answer to "where is this skill's data" depended on whether someone had remembered to
    export a variable on this particular machine.

    Measured 2026-08-20 across eight skills that have real data:
      resolved to the companion repo   3   (their env var happened to be set)
      resolved to a $HOME dotfile      3   (one of them WHILE its companion repo sat beside it)
      answered "uninitialized"         3   (one of those had 153 tracked files in its companion)
    The last group is the bad one: `datadir.py` returned None, callers correctly reported the
    skill as having no data, and an out-of-band coverage check counted them as SKIP. Three real
    private repos were invisible to the boundary tooling, and the report was green.

    Derived from this file's own worktree rather than a hardcoded path, deliberately. The
    absolute location differs per machine, and a home-anchored literal in a public repo is
    exactly what pii_guard blocks. When this file is NOT inside a worktree (the canonical copy
    under the scripts directory), there is no sibling to infer and this contributes nothing;
    resolution then falls back to the env vars and dotfiles as before.
    """
    root = _own_repo_root()
    if root is None:
        return []
    return [Path(root).parent / ("%s-config" % skill)]


def _candidates(skill):
    """Discovery order, as Paths. See the module docstring."""
    out = []
    d = os.environ.get(_env_var(skill))
    if d:
        out.append(Path(os.path.expanduser(d)))
    for ev in _config_env_vars(skill):
        c = os.environ.get(ev)
        if not c:
            continue
        root = Path(os.path.expanduser(c))
        # A companion repo that keeps its output under data/ gets data/; one that files it directly
        # at the repo root (daily-hotspots' archive/ is the fleet's other shape) gets the root.
        # Either way the ANSWER to "where does real-run output live" is inside that private repo,
        # which is what every consumer of this function is actually asking.
        out.append(root / "data")
        out.append(root)
    # The convention comes BEFORE the dotfiles: when a skill has a real companion repo beside it,
    # that repo is the answer, and a leftover dotfile must not shadow it. It comes AFTER the env
    # vars so an explicit override still wins.
    for root in _convention_roots(skill):
        out.append(root / "data")
        out.append(root)
    dot = Path(os.path.expanduser("~/.%s-config" % skill))
    out.append(dot / "data")
    # The dotfile ROOT, not just its data/ subdir. Companion repos are already probed both ways
    # a few lines up; the dotfile shape was only probed one way, so a skill that files output
    # directly at the root answered "uninitialized" while its files sat right there. email-monitor
    # is that shape (153 tracked files, its own private remote, and its CONFIG.md documents this
    # exact path as the third discovery step) and it read as having no data at all until 2026-08-20.
    out.append(dot)
    out.append(Path(os.path.expanduser("~/.%s-data" % skill)))
    return out


def resolve_companion_root(skill):
    """The private companion REPO root for `skill`, or None. Never a path inside the skill's repo.

    resolve_data_dir answers "where does real-run output go", which is usually `<companion>/data`.
    This answers the adjacent question, "where is the companion itself", which is what a caller
    looking for config.json, a registry or a runbook needs.

    IT EXISTS SO THERE IS ONE DISCOVERY ORDER, NOT TWO. small-cap-deepdive had a second resolver in
    tools/_common.py that probed only environment variables and home dotfiles, and did not know the
    sibling convention at all. The consequence, measured 2026-08-30: resolve_data_dir found the
    companion at CodesClaude/small-cap-deepdive-config/data while resolve_config_json returned None,
    so the skill fell back to the shipped example default of `./reports/smallcap` and wrote 4029
    real-run files into its own public repository. Two answers to one question, and the wrong one
    was the one that decided where files landed.

    So a caller that needs the companion asks here rather than re-deriving the order. The order is
    the same as resolve_data_dir's, minus the data/ suffix probes, and the same rejection applies: a
    companion that resolves inside the skill's own repo raises rather than being returned.
    """
    for p in _candidates(skill):
        if not p.is_dir():
            continue
        # _candidates yields <root>/data before <root>. A caller asking for the companion ROOT gets
        # the parent in that case, so both companion shapes in this fleet answer the same way.
        root = p.parent if p.name == "data" and p.parent.is_dir() else p
        _reject_if_inside_own_repo(root, skill)
        return root
    return None


def resolve_data_dir(skill, create=False):
    """Return the private data dir for `skill`, or None if the tool is uninitialized.

    Raises DataDirInsideOwnRepo if the resolved directory sits inside this skill's own repo.
    """
    candidates = _candidates(skill)
    for p in candidates:
        if p.is_dir():
            _reject_if_inside_own_repo(p, skill)
            return p
    if create:
        # Create the most specific place the operator actually pointed at: an explicit data-dir
        # override first, then the companion repo's data/, then the dotfile default.
        p = candidates[0]
        _reject_if_inside_own_repo(p, skill)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def data_path(skill, relpath, create=False):
    """Resolve <private data dir>/<relpath>. Never returns a path inside the repo."""
    base = resolve_data_dir(skill, create=create)
    if base is None:
        raise DataDirNotInitialized(
            "%s has no private data directory, so it has nowhere to put real-run output.\n"
            "This is the correct state for a freshly cloned public skill: it ships as an\n"
            "uninitialized tool. Point it at your PRIVATE COMPANION repo:\n"
            "    set %s to the companion repo (data/ under it is used when present)\n"
            "    or mkdir -p ~/.%s-config/data\n"
            "    or set %s to an explicit private directory\n"
            "Real-run output NEVER goes back into THIS repo -- this repo carries only the schema\n"
            "(<file>.example) and a synthetic fixture set."
            % (skill, _config_env_vars(skill)[0], skill, _env_var(skill)))
    p = base / relpath
    if create:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cli(argv=None):
    """`python tools/datadir.py --path <skill> [relpath]` -> print the resolved path, or fail.

    Runbooks and shell steps need the path too, and the alternative is that someone hardcodes
    `metrics/foo.jsonl` into a doc because it was the only thing they could type -- which is how
    the docs ended up instructing agents to write real-run output into the public repo in the
    first place. Exit 3 (not 1) when uninitialized, so a script can tell "no data yet" apart from
    a real error.
    """
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Resolve a skill's private data path.")
    ap.add_argument("--path", action="store_true", help="print the resolved path")
    ap.add_argument("--create", action="store_true", help="create the directory if absent")
    ap.add_argument("skill")
    ap.add_argument("relpath", nargs="?", default="")
    a = ap.parse_args(argv)

    try:
        p = data_path(a.skill, a.relpath, create=a.create) if a.relpath \
            else (resolve_data_dir(a.skill, create=a.create) or _raise(a.skill))
    except DataDirNotInitialized as e:
        print(str(e), file=sys.stderr)
        return 3
    except DataDirInsideOwnRepo as e:
        # Exit 4, distinct from 3. "No data yet" is a state a caller may proceed through; "the data
        # dir points into the tool repo" is a defect a caller must stop on.
        print(str(e), file=sys.stderr)
        return 4
    print(p)
    return 0


def _raise(skill):
    raise DataDirNotInitialized(
        "%s has no private data directory.\n    set %s to the private companion repo\n"
        "    or mkdir -p ~/.%s-config/data\n    (or set %s)"
        % (skill, _config_env_vars(skill)[0], skill, _env_var(skill)))


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
