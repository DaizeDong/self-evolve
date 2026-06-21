import os
import json
from tools.sie import archive


def test_add_and_lineage(tmp_path):
    run_dir = str(tmp_path / "run")
    archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
    archive.add_version(run_dir, "v2", {"pytest": 1.0}, "v1")
    lin = archive.lineage(os.path.join(run_dir, "archive"))
    ids = [e["vid"] for e in lin]
    assert ids == ["v1", "v2"]
    assert lin[1]["parent_vid"] == "v1"


def test_snapshot_and_rollback(tmp_path):
    run_dir = str(tmp_path / "run")
    arch = os.path.join(run_dir, "archive")
    sbx = tmp_path / "sbx"
    sbx.mkdir()
    (sbx / "code.py").write_text("VERSION = 1\n")
    archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
    archive.snapshot_version(arch, "v1", str(sbx))
    # modify sandbox content to v2
    (sbx / "code.py").write_text("VERSION = 2\n")
    archive.add_version(run_dir, "v2", {"pytest": 1.0}, "v1")
    archive.snapshot_version(arch, "v2", str(sbx))
    # rollback to v1: current pointer back to v1 snapshot
    archive.rollback(arch, "v1")
    cur = os.path.join(arch, "current", "code.py")
    assert open(cur).read() == "VERSION = 1\n"


def test_pareto_returns_active(tmp_path):
    run_dir = str(tmp_path / "run")
    archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
    front = archive.pareto_front(os.path.join(run_dir, "archive"))
    assert "v1" in front


def test_lineage_append_only(tmp_path):
    """lineage.json must grow monotonically — no entries ever removed."""
    run_dir = str(tmp_path / "run")
    arch = os.path.join(run_dir, "archive")
    archive.add_version(run_dir, "v1", {"s": 1.0}, None)
    archive.add_version(run_dir, "v2", {"s": 0.9}, "v1")
    archive.add_version(run_dir, "v3", {"s": 1.1}, "v2")
    lin = archive.lineage(arch)
    assert len(lin) == 3
    assert [e["vid"] for e in lin] == ["v1", "v2", "v3"]
    assert lin[0]["parent_vid"] is None
    assert lin[1]["parent_vid"] == "v1"
    assert lin[2]["parent_vid"] == "v2"


def test_rollback_truly_restores_content(tmp_path):
    """rollback must restore file content from the snapshot, not just update metadata."""
    run_dir = str(tmp_path / "run")
    arch = os.path.join(run_dir, "archive")
    sbx = tmp_path / "sbx"
    sbx.mkdir()

    (sbx / "main.py").write_text("A = 100\n")
    (sbx / "sub").mkdir()
    (sbx / "sub" / "helper.py").write_text("def help(): return 1\n")
    archive.add_version(run_dir, "v1", {"s": 1.0}, None)
    archive.snapshot_version(arch, "v1", str(sbx))

    (sbx / "main.py").write_text("A = 999\n")
    (sbx / "sub" / "helper.py").write_text("def help(): return 999\n")
    archive.add_version(run_dir, "v2", {"s": 0.5}, "v1")
    archive.snapshot_version(arch, "v2", str(sbx))

    archive.rollback(arch, "v1")
    cur = os.path.join(arch, "current")
    assert open(os.path.join(cur, "main.py")).read() == "A = 100\n"
    assert open(os.path.join(cur, "sub", "helper.py")).read() == "def help(): return 1\n"

    # rollback to v2 must replace current again
    archive.rollback(arch, "v2")
    assert open(os.path.join(cur, "main.py")).read() == "A = 999\n"


def test_retire_stale_writes_jsonl(tmp_path):
    run_dir = str(tmp_path / "run")
    arch = os.path.join(run_dir, "archive")
    for i in range(1, 5):
        archive.add_version(run_dir, f"v{i}", {"s": float(i)}, f"v{i-1}" if i > 1 else None)
    # active_cap=2 → 2 oldest become stale
    archive.retire_stale(arch, active_cap=2)
    retired_path = os.path.join(arch, "retired.jsonl")
    assert os.path.exists(retired_path)
    lines = [json.loads(l) for l in open(retired_path).readlines()]
    assert len(lines) == 2
    assert lines[0]["vid"] == "v1"
    assert lines[1]["vid"] == "v2"


def test_versions_dir_created(tmp_path):
    run_dir = str(tmp_path / "run")
    archive.add_version(run_dir, "vA", {"s": 1.0}, None)
    versions_dir = os.path.join(run_dir, "archive", "versions", "vA")
    assert os.path.isdir(versions_dir)
