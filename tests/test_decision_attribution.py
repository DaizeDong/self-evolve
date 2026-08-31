"""Every accepted decision gets labelled from outside, by the hidden oracles.

WHY. `score()` runs the oracles once, on the final tree, so a loop that accepted fifty one wrong
changes and one right one reports exactly the same number as a loop that accepted the one right
change and rejected everything else. Run on real history, this pass turned "the loop repaired 8 of
21" into "31 accepted decisions: 8 REPAIR, 23 INERT, 0 REGRESSION", which says the loop landed five
real repairs in its first five rounds and then accepted twenty three changes that moved nothing.

Three independent judges asked for this before any new gate, for one reason: it is the only
component whose INPUT COMES FROM OUTSIDE THE SYSTEM UNDER TEST. Four gates in this codebase were
correct in their unit tests and inert in production, every time because the test fed them the input
they were built to recognize. Here the input is 21 defects with known repairs, chosen by someone who
knew the answer and did not tell the loop.

So these tests build real snapshots on disk and drive the real function. Nothing is stubbed except
the oracle bodies, which are tiny real pytest files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tools.sie import archive
from tools.sie.calibrate import attribute_decisions


def _defect(did, rel, want):
    """A defect whose oracle passes exactly when `rel` contains `want`."""
    return {
        "id": did, "file_rel": rel, "find": "x", "replace": "y",
        "defect_class": "test", "why_realistic": "test",
        "oracle": ("import io, os\n"
                   "def test_repaired():\n"
                   "    src = io.open(os.path.join(os.environ['ATTR_TREE'], %r), encoding='utf-8').read()\n"
                   "    assert %r in src\n" % (rel, want)),
    }


def _version(root, run_id, vid, parent, files):
    arch = Path(root) / ".sie" / "runs" / run_id / "archive"
    snap = arch / "versions" / vid / "snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = snap / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    archive.add_version(str(Path(root) / ".sie" / "runs" / run_id), vid,
                        [{"name": "t::1", "tier": "A", "score": 1.0, "weight": 1.0}], parent)


def _run(root, run_id, defects, monkeypatch):
    """Run attribution with the oracle reading whichever tree it is pointed at."""
    import tools.sie.calibrate as C

    real = C.run_oracle

    def patched(tree, oracle_src, timeout_s=300):
        monkeypatch.setenv("ATTR_TREE", tree)
        return real(tree, oracle_src, timeout_s)

    monkeypatch.setattr(C, "run_oracle", patched)
    return C.attribute_decisions(root, run_id, defects)


def test_a_real_repair_is_labelled_REPAIR_and_a_no_op_is_labelled_INERT(tmp_path, monkeypatch):
    """THE LOAD BEARING TEST. Two accepted versions, one that fixes and one that changes nothing
    an oracle can see. They must not get the same label; that conflation is the whole defect."""
    root = str(tmp_path / "t")
    d = [_defect("d1", "mod.py", "FIXED")]
    _version(root, "r", "v1", "base", {"mod.py": "VALUE = 'broken'\n"})
    _version(root, "r", "v2", "v1", {"mod.py": "VALUE = 'FIXED'\n"})
    _version(root, "r", "v3", "v2", {"mod.py": "VALUE = 'FIXED'  # comment only\n"})

    out = _run(root, "r", d, monkeypatch)
    labels = {v["vid"]: v["labels"] for v in out["versions"]}
    assert labels["v1"] == ["NO_SEEDED_EFFECT"], labels
    assert labels["v2"] == ["REPAIR"] and out["versions"][1]["repaired"] == ["d1"], labels
    assert labels["v3"] == ["NO_SEEDED_EFFECT"], labels
    assert out["totals"] == {"REPAIR": 1, "REGRESSION": 0, "NO_SEEDED_EFFECT": 2}


def test_undoing_an_earlier_repair_is_labelled_REGRESSION(tmp_path, monkeypatch):
    """NEGATIVE CONTROL in the other direction. An instrument that can only say "good" or "nothing"
    would report this as INERT, and a loop quietly undoing its own repairs would look idle."""
    root = str(tmp_path / "t")
    d = [_defect("d1", "mod.py", "FIXED")]
    _version(root, "r", "v1", "base", {"mod.py": "VALUE = 'FIXED'\n"})
    _version(root, "r", "v2", "v1", {"mod.py": "VALUE = 'broken again'\n"})

    out = _run(root, "r", d, monkeypatch)
    assert out["versions"][0]["labels"] == ["REPAIR"]
    assert out["versions"][1]["labels"] == ["REGRESSION"]
    assert out["versions"][1]["regressed"] == ["d1"]


def test_a_version_with_no_snapshot_is_UNMEASURABLE_not_INERT(tmp_path, monkeypatch):
    """"Not measured" and "measured and found clean" must never share an output. This whole session
    was a sequence of gates that reported green because they had not looked."""
    root = str(tmp_path / "t")
    d = [_defect("d1", "mod.py", "FIXED")]
    _version(root, "r", "v1", "base", {"mod.py": "VALUE = 'FIXED'\n"})
    arch = Path(root) / ".sie" / "runs" / "r" / "archive"
    archive.add_version(str(Path(root) / ".sie" / "runs" / "r"), "v2",
                        [{"name": "t::1", "tier": "A", "score": 1.0, "weight": 1.0}], "v1")
    assert not (arch / "versions" / "v2" / "snapshot").is_dir()

    out = _run(root, "r", d, monkeypatch)
    assert out["versions"][1]["labels"] == ["UNMEASURABLE"]
    assert "no snapshot" in out["versions"][1]["why"]


def test_the_per_defect_shortcut_does_not_change_any_label(tmp_path, monkeypatch):
    """The cost shortcut inherits a parent's verdict when the defect's file is byte-identical. It is
    exact by construction, and this pins that: a defect in an UNTOUCHED file must keep its verdict
    across a version that edited a different file."""
    root = str(tmp_path / "t")
    d = [_defect("d1", "a.py", "FIXED_A"), _defect("d2", "b.py", "FIXED_B")]
    _version(root, "r", "v1", "base", {"a.py": "A = 'FIXED_A'\n", "b.py": "B = 'broken'\n"})
    _version(root, "r", "v2", "v1", {"a.py": "A = 'FIXED_A'\n", "b.py": "B = 'FIXED_B'\n"})

    out = _run(root, "r", d, monkeypatch)
    assert out["versions"][0]["repaired"] == ["d1"]
    assert out["versions"][1]["repaired"] == ["d2"], (
        "d1 lives in an untouched file and must stay repaired; d2 must be newly credited")
    assert out["versions"][1]["labels"] == ["REPAIR"]


def test_an_empty_lineage_reports_nothing_rather_than_inventing_versions(tmp_path, monkeypatch):
    root = str(tmp_path / "t")
    (Path(root) / ".sie" / "runs" / "r" / "archive").mkdir(parents=True)
    out = _run(root, "r", [_defect("d1", "mod.py", "FIXED")], monkeypatch)
    assert out["n_accepted"] == 0 and out["versions"] == []
    assert out["totals"] == {"REPAIR": 0, "REGRESSION": 0, "NO_SEEDED_EFFECT": 0}
