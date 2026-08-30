#!/usr/bin/env python3
"""Does COMPANION.md describe what tools/datadir.py actually does?

WHY THIS TEST EXISTS. This fleet already had a companion specification: 542 lines, versioned v1.3,
marked STABLE, in market-intel. Its discovery section names three locations, and not one of them is
the sibling convention that every companion on this machine is actually found by. It was written
from memory, nothing ever compared it to the resolver, and a companion built to it would not be
discovered at all. A contract nobody can plug into is worse than no contract, because it reads like
one.

So the contract's discovery table is checked against the code by CONSTRUCTION: each documented
location is created in a scratch HOME and the resolver must pick it, and the documented priority is
checked by pairwise shadowing. The two promises the document makes about failure, that nothing found
means None rather than a guess, and that a data directory inside the skill's own repo raises, are
asserted too.

  python tools/test_companion_contract.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DOC = REPO / "COMPANION.md"
DD = HERE / "datadir.py"
SKILL = "probe-skill"
STEM = SKILL.upper().replace("-", "_")

failures = []


def check(label, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + label + (("  <- " + detail) if (detail and not cond) else ""))
    if not cond:
        failures.append(label)


def _load(path):
    spec = importlib.util.spec_from_file_location("dd_under_test", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _clean_env(home):
    for k in list(os.environ):
        if k.startswith(STEM):
            del os.environ[k]
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home


def _case(make, envf=None, tmp=None):
    """Put a copy of datadir.py in <tmp>/repos/<skill>/tools/, run `make`, resolve.

    `tmp` is created by the CALLER and passed in, because an env-var case has to name a path under
    it and therefore has to know it first. An earlier version built tmp in here and handed the env
    builder a different temp directory, so the variable pointed at a path nothing had created and
    two documented locations reported as unresolvable when they resolve fine. A test that fails for
    a reason of its own making is worse than no test: it accuses working code.
    """
    if tmp is None:
        tmp = tempfile.mkdtemp()
    try:
        home = os.path.join(tmp, "home")
        repos = os.path.join(tmp, "repos")
        repo = os.path.join(repos, SKILL)
        os.makedirs(os.path.join(repo, "tools"), exist_ok=True)
        os.makedirs(home, exist_ok=True)
        dst = os.path.join(repo, "tools", "datadir.py")
        shutil.copy(str(DD), dst)
        # datadir derives the sibling from ITS OWN worktree, so this has to be one.
        subprocess.run(["git", "-C", repo, "init", "-q"], capture_output=True)
        _clean_env(home)
        for k, v in ((envf(tmp) if callable(envf) else (envf or {})) or {}).items():
            os.environ[k] = v
        make(tmp, home, repos)
        return _load(dst).resolve_data_dir(SKILL), tmp, home, repos
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def main():
    if not DOC.is_file():
        print("FAIL: %s is missing. The contract is what a restored machine reads." % DOC)
        return 1
    text = io.open(DOC, encoding="utf-8").read()

    print("A. the table names every location the resolver probes")
    for needed in ("$<SKILL>_DATA_DIR", "$<SKILL>_CONFIG", "_CONFIG_DIR",
                   "<skill>-config", "~/.<skill>-config", "~/.<skill>-data"):
        check("names %s" % needed, needed in text)

    print("\nB. each documented location resolves")
    cases = [
        ("env DATA_DIR",
         lambda t, h, r: os.makedirs(os.path.join(t, "explicit"), exist_ok=True),
         lambda t: {STEM + "_DATA_DIR": os.path.join(t, "explicit")},
         lambda t, r: os.path.join(t, "explicit")),
        ("env CONFIG plus data/",
         lambda t, h, r: os.makedirs(os.path.join(t, "cfg", "data"), exist_ok=True),
         lambda t: {STEM + "_CONFIG": os.path.join(t, "cfg")},
         lambda t, r: os.path.join(t, "cfg", "data")),
        ("sibling <skill>-config/data",
         lambda t, h, r: os.makedirs(os.path.join(r, SKILL + "-config", "data"), exist_ok=True),
         lambda t: {},
         lambda t, r: os.path.join(r, SKILL + "-config", "data")),
        ("sibling root, the shape with no data/",
         lambda t, h, r: os.makedirs(os.path.join(r, SKILL + "-config"), exist_ok=True),
         lambda t: {},
         lambda t, r: os.path.join(r, SKILL + "-config")),
        ("home dotfile config/data",
         lambda t, h, r: os.makedirs(os.path.join(h, "." + SKILL + "-config", "data"), exist_ok=True),
         lambda t: {},
         lambda t, r: os.path.join(t, "home", "." + SKILL + "-config", "data")),
        ("home dotfile data",
         lambda t, h, r: os.makedirs(os.path.join(h, "." + SKILL + "-data"), exist_ok=True),
         lambda t: {},
         lambda t, r: os.path.join(t, "home", "." + SKILL + "-data")),
    ]
    for label, make, envf, want in cases:
        tmp = tempfile.mkdtemp()
        try:
            got, tmp, home, repos = _case(make, envf, tmp)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            check(label, False, "raised %s" % type(e).__name__)
            continue
        try:
            exp = want(tmp, repos)
            check(label, got is not None and Path(str(got)).resolve() == Path(exp).resolve(),
                  "want %s got %s" % (exp, got))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\nC. the documented PRIORITY, by shadowing")
    got, tmp, home, repos = _case(lambda t, h, r: (
        os.makedirs(os.path.join(r, SKILL + "-config", "data"), exist_ok=True),
        os.makedirs(os.path.join(h, "." + SKILL + "-config", "data"), exist_ok=True)), {})
    try:
        check("the sibling beats the home dotfile",
              got is not None and ".%s-config" % SKILL not in str(got), "got %s" % got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nD. the two promises the contract makes about failure")
    got, tmp, home, repos = _case(lambda t, h, r: None, {})
    try:
        check("nothing present resolves to None, never to a guess", got is None, "got %s" % got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        repo = os.path.join(tmp, "repos", SKILL)
        os.makedirs(os.path.join(repo, "tools"), exist_ok=True)
        home = os.path.join(tmp, "home")
        os.makedirs(home, exist_ok=True)
        shutil.copy(str(DD), os.path.join(repo, "tools", "datadir.py"))
        subprocess.run(["git", "-C", repo, "init", "-q"], capture_output=True)
        inside = os.path.join(repo, "reports")
        os.makedirs(inside, exist_ok=True)
        _clean_env(home)
        os.environ[STEM + "_DATA_DIR"] = inside
        m = _load(os.path.join(repo, "tools", "datadir.py"))
        raised = False
        try:
            m.resolve_data_dir(SKILL)
        except Exception as e:
            raised = type(e).__name__ == "DataDirInsideOwnRepo"
        check("a data dir inside the skill's own repo raises", raised)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    if failures:
        print("test_companion_contract: %d FAILED" % len(failures))
        return 1
    print("test_companion_contract: the contract matches the resolver")
    return 0


if __name__ == "__main__":
    sys.exit(main())
