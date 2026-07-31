#!/usr/bin/env python3
"""Tests for tools/datadir.py -- the resolver that decides WHERE real-run output goes.

WHY THESE EXIST
---------------
This file is the pipe. If it points at the wrong place, no scanner downstream can help: a verdict
ledger with an entry price in it has no email, no phone and no ZIP to smell. The 2026-07 leak was
not a scanning failure, it was a resolver that had a fallback into the repo.

Two properties are pinned here, and they are the two that have actually broken:

  1. The resolver FOLLOWS the same pointer the skill follows. It knew only the dotfile path for
     months while several companion repos were pinned elsewhere with $<SKILL>_CONFIG, so it
     answered None -- "uninitialized" -- for skills that were writing a real ledger every day. An
     out-of-band control then asked it where the data was, was told nothing, and reported a clean
     sheet. A checker that is handed nothing prints the same green as a checker that found nothing
     wrong.

  2. It REFUSES a data dir inside its own repo. That is the in-repo-fallback shape, the one that
     put a real contact address in a public repo under the label "legacy fallback". The check is
     deliberately narrow so it needs no visibility map, no gh and no network: this file ships in
     public repos and must work on a stranger's fresh clone. Whether the CONTAINING repo is public
     is a question with no local answer, so it is asked out of band, by the fleet checker that has
     the map.

Stdlib + pytest only. No network, no gh, no real repos.
"""
from __future__ import annotations

import importlib.util
import os
import shutil

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DATADIR = os.path.join(HERE, "datadir.py")


def load(path, name="datadir_under_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dd = load(DATADIR)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ("DEMO_DATA_DIR", "DEMO_CONFIG", "DEMO_CONFIG_DIR"):
        monkeypatch.delenv(v, raising=False)
    # HOME is read for the dotfile fallbacks; point it somewhere empty so a real machine's
    # ~/.demo-config cannot make a test pass or fail by accident.
    yield


def _isolate_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# --- discovery order -----------------------------------------------------------------------------
def test_uninitialized_returns_none(monkeypatch, tmp_path):
    """A freshly cloned public skill knows nothing about anybody. That is the SHIPPING state."""
    _isolate_home(monkeypatch, tmp_path)
    assert dd.resolve_data_dir("demo") is None


def test_explicit_data_dir_wins(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    store = tmp_path / "explicit"
    store.mkdir()
    monkeypatch.setenv("DEMO_DATA_DIR", str(store))
    assert str(dd.resolve_data_dir("demo")) == str(store)


def test_config_env_resolves_to_companion_data_subdir(monkeypatch, tmp_path):
    """The fleet's primary shape: the companion repo keeps run output under data/."""
    _isolate_home(monkeypatch, tmp_path)
    cfg = tmp_path / "demo-config"
    (cfg / "data").mkdir(parents=True)
    monkeypatch.setenv("DEMO_CONFIG", str(cfg))
    assert str(dd.resolve_data_dir("demo")) == str(cfg / "data")


def test_config_env_falls_back_to_companion_root(monkeypatch, tmp_path):
    """The fleet's other shape: output filed directly under the companion repo (archive/, ...).

    Returning the companion ROOT is the honest answer to "where does this skill's real-run output
    live", and it is what makes the out-of-band boundary check able to see the skill at all. The
    predecessor returned None here, which reads as "nothing to check".
    """
    _isolate_home(monkeypatch, tmp_path)
    cfg = tmp_path / "demo-config"
    (cfg / "archive").mkdir(parents=True)
    monkeypatch.setenv("DEMO_CONFIG", str(cfg))
    assert str(dd.resolve_data_dir("demo")) == str(cfg)


def test_config_dir_alias_is_honored(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    cfg = tmp_path / "demo-config"
    (cfg / "data").mkdir(parents=True)
    monkeypatch.setenv("DEMO_CONFIG_DIR", str(cfg))
    assert str(dd.resolve_data_dir("demo")) == str(cfg / "data")


def test_dotfile_companion_still_works(monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    (home / ".demo-config" / "data").mkdir(parents=True)
    assert str(dd.resolve_data_dir("demo")) == str(home / ".demo-config" / "data")


def test_standalone_dotfile_is_the_last_resort(monkeypatch, tmp_path):
    home = _isolate_home(monkeypatch, tmp_path)
    (home / ".demo-data").mkdir(parents=True)
    assert str(dd.resolve_data_dir("demo")) == str(home / ".demo-data")


def test_data_path_raises_with_instructions_not_a_repo_fallback(monkeypatch, tmp_path):
    """The whole point: no silent in-repo fallback, ever. Raise and say what to do."""
    _isolate_home(monkeypatch, tmp_path)
    with pytest.raises(dd.DataDirNotInitialized) as e:
        dd.data_path("demo", "metrics/live-runs.jsonl")
    msg = str(e.value)
    assert "DEMO_CONFIG" in msg and "DEMO_DATA_DIR" in msg
    assert "NEVER goes back into THIS repo" in msg


# --- the narrow refusal --------------------------------------------------------------------------
def _skill_repo(tmp_path, name="fakeskill"):
    """A copy of datadir.py deployed at <repo>/tools/datadir.py inside a fake worktree."""
    repo = tmp_path / name
    (repo / "tools").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "data").mkdir()
    shutil.copy2(DATADIR, repo / "tools" / "datadir.py")
    return repo, load(str(repo / "tools" / "datadir.py"), "dd_" + name)


def test_data_dir_inside_own_repo_is_refused(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    repo, mod = _skill_repo(tmp_path)
    monkeypatch.setenv("FAKESKILL_DATA_DIR", str(repo / "data"))
    with pytest.raises(mod.DataDirInsideOwnRepo):
        mod.resolve_data_dir("fakeskill")


def test_repo_root_itself_is_refused(monkeypatch, tmp_path):
    _isolate_home(monkeypatch, tmp_path)
    repo, mod = _skill_repo(tmp_path)
    monkeypatch.setenv("FAKESKILL_DATA_DIR", str(repo))
    with pytest.raises(mod.DataDirInsideOwnRepo):
        mod.resolve_data_dir("fakeskill")


def test_sibling_companion_repo_is_not_mistaken_for_inside(monkeypatch, tmp_path):
    """`<repo>-config` must NOT count as inside `<repo>`.

    Every companion repo in this fleet is named exactly that way, so a prefix comparison without the
    separator would reject the one shape the doctrine prescribes. This is the regression test for
    the separator, not a style preference.
    """
    _isolate_home(monkeypatch, tmp_path)
    repo, mod = _skill_repo(tmp_path)
    comp = tmp_path / "fakeskill-config"
    (comp / "data").mkdir(parents=True)
    monkeypatch.setenv("FAKESKILL_CONFIG", str(comp))
    assert str(mod.resolve_data_dir("fakeskill")) == str(comp / "data")


def test_refusal_also_applies_when_creating(monkeypatch, tmp_path):
    """create=True is the WRITE path. A writer that shrugs has only bad options."""
    _isolate_home(monkeypatch, tmp_path)
    repo, mod = _skill_repo(tmp_path)
    monkeypatch.setenv("FAKESKILL_DATA_DIR", str(repo / "not-yet"))
    with pytest.raises(mod.DataDirInsideOwnRepo):
        mod.resolve_data_dir("fakeskill", create=True)
    assert not (repo / "not-yet").exists(), "refused, and must not have created it anyway"


def test_no_worktree_means_no_refusal(monkeypatch, tmp_path):
    """Deployed outside a worktree there is nothing to be inside of; do not invent a failure."""
    _isolate_home(monkeypatch, tmp_path)
    loose = tmp_path / "loose" / "tools"
    loose.mkdir(parents=True)
    shutil.copy2(DATADIR, loose / "datadir.py")
    mod = load(str(loose / "datadir.py"), "dd_loose")
    store = tmp_path / "loose" / "data"
    store.mkdir()
    monkeypatch.setenv("LOOSE_DATA_DIR", str(store))
    assert str(mod.resolve_data_dir("loose")) == str(store)
