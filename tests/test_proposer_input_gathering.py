"""The proposer's INPUT is a signal, and an empty input must not look like an empty opinion.

WHAT WENT WRONG (2026-08-20)
----------------------------
A run was pointed at a target whose only non-test source file was 106 KB. `_gather_sources`
skipped any file over a 20 KB cap, silently, so it returned zero files; `llm.generate` returned
`[]` on its first line without ever launching the proposer; `propose` fell back to the builtin
fixer, which needs a `fix_content` the reflection did not have; `props` came back empty and the
loop recorded STATIC_REJECT. Four rounds, exit code 0, `accepted_versions: []`.

That output is byte-identical to the one a run produces when the target is genuinely already
good. The engine reported convergence on a target it had never looked at.

Two properties are pinned here. The cap must admit a file of realistic size for a single-module
target, and a gather that comes back empty must say what it skipped and why.
"""
from __future__ import annotations

import os

from tools.sie.backends import llm


def _write(root: str, name: str, size: int) -> None:
    with open(os.path.join(root, name), "w", encoding="utf-8") as f:
        f.write("# padding\n" * (size // 10))


def test_a_realistic_single_module_target_is_gathered(tmp_path):
    """A 100 KB module is about 25K tokens. Refusing to show it to the proposer is not a budget
    decision any more, it is a blindfold."""
    root = str(tmp_path)
    _write(root, "big_module.py", 100_000)
    files = llm._gather_sources(root)
    assert "big_module.py" in files


def test_a_file_over_the_cap_is_RECORDED_not_silently_dropped(tmp_path):
    """The twin. The cap still exists, and this is the part that was missing: the caller has to be
    able to tell 'nothing to propose' apart from 'nothing was shown to the proposer'."""
    root = str(tmp_path)
    _write(root, "enormous.py", llm._MAX_FILE_BYTES + 50_000)
    skipped: list = []
    files = llm._gather_sources(root, skipped)
    assert files == {}
    assert skipped and skipped[0][0] == "enormous.py"
    assert "larger than" in skipped[0][1]


def test_test_files_are_still_excluded(tmp_path):
    """Unchanged behaviour, asserted so a future widening of the cap does not quietly widen this
    too: the proposer edits sources, and handing it the tests invites editing the grader."""
    root = str(tmp_path)
    _write(root, "mod.py", 100)
    _write(root, "test_mod.py", 100)
    files = llm._gather_sources(root)
    assert "mod.py" in files and "test_mod.py" not in files


def test_generate_returns_empty_and_says_so_when_it_gathered_nothing(tmp_path, capsys):
    """`generate` returning [] is correct here. Doing it in silence was the defect."""
    root = str(tmp_path)
    _write(root, "enormous.py", llm._MAX_FILE_BYTES + 50_000)
    assert llm.generate(root, [{"text": "anything"}]) == []
    err = capsys.readouterr().err
    assert "gathered 0 source files" in err
    assert "enormous.py" in err


def test_every_failure_path_says_what_happened(tmp_path, capsys, monkeypatch):
    """`[]` is also what the proposer returns when the model genuinely had nothing to suggest.
    One value, two meanings, and only the innocent one reached the run report.

    Observed on a 106 KB target: the agent judged a hundred kilobytes of new_content too much to
    emit inline, wrote it to a file in the working directory, and printed prose. The contract
    reads stdout only, so the loop recorded STATIC_REJECT while a complete proposal sat on disk.
    """
    root = str(tmp_path)
    _write(root, "mod.py", 100)

    class FakeProc:
        returncode = 0
        stdout = "I have written the new file to proposal_tmp.json for you."
        stderr = ""

    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: FakeProc())
    assert llm.generate(root, [{"text": "x"}]) == []
    err = capsys.readouterr().err
    assert "not JSON" in err and "proposer produced nothing" in err
