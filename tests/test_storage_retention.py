"""Retirement must preserve core data and reject stale or escaping selections."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.make_fixtures import retention_samples
from tools import storage_retention as storage


def setup_case(tmp_path):
    case = retention_samples()
    for name in ("core", "scratch"):
        path = tmp_path / case[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(case["content"])
    return case


def selected(case, path):
    registry = copy.deepcopy(case["registry"])
    registry["retirements"] = [{"path": path, "reason": "Synthetic completed review",
                                "completed": True, "dependencies_released": True}]
    return registry


def test_core_cannot_be_retired_even_when_marked_complete(tmp_path):
    case = setup_case(tmp_path)
    with pytest.raises(ValueError, match="core"):
        storage.build_plan(tmp_path, selected(case, case["core"]), case["contract"])
    assert (tmp_path / case["core"]).read_bytes() == case["content"]


def test_protected_dependency_blocks_parent_retirement(tmp_path):
    case = setup_case(tmp_path)
    registry = selected(case, "diagnostics")
    registry["protected_paths"] = [case["scratch"]]
    with pytest.raises(ValueError, match="protected"):
        storage.build_plan(tmp_path, registry, case["contract"])
    assert (tmp_path / case["scratch"]).exists()


def test_changed_plan_fails_before_any_deletion(tmp_path):
    case = setup_case(tmp_path)
    registry = selected(case, case["scratch"])
    plan = storage.build_plan(tmp_path, registry, case["contract"])
    (tmp_path / case["scratch"]).write_bytes(case["changed"])
    with pytest.raises(ValueError, match="changed"):
        storage.apply_plan(tmp_path, registry, case["contract"], plan)
    assert (tmp_path / case["scratch"]).read_bytes() == case["changed"]


def test_only_reviewed_retired_bytes_are_removed(tmp_path):
    case = setup_case(tmp_path)
    registry = selected(case, case["scratch"])
    plan = storage.build_plan(tmp_path, registry, case["contract"])
    assert plan["files"][0]["sha256"] == hashlib.sha256(case["content"]).hexdigest()
    assert storage.apply_plan(tmp_path, registry, case["contract"], plan)["removed_files"] == 1
    assert (tmp_path / case["core"]).read_bytes() == case["content"]
    assert storage.build_plan(tmp_path, registry, case["contract"])["file_count"] == 0


def test_unfinished_work_cannot_be_retired(tmp_path):
    case = setup_case(tmp_path)
    registry = selected(case, case["scratch"])
    registry["retirements"][0]["dependencies_released"] = False
    with pytest.raises(ValueError, match="dependencies"):
        storage.build_plan(tmp_path, registry, case["contract"])


@pytest.mark.parametrize("marker", ["reparse", "hardlink"])
def test_link_metadata_blocks_retirement_before_reading(tmp_path, monkeypatch, marker):
    case = setup_case(tmp_path)
    path = tmp_path / case["scratch"]
    original = Path.lstat
    def metadata(self):
        info = original(self)
        if self == path:
            return SimpleNamespace(st_mode=info.st_mode,
                                   st_nlink=2 if marker == "hardlink" else 1,
                                   st_file_attributes=1024 if marker == "reparse" else 0)
        return info
    monkeypatch.setattr(Path, "lstat", metadata)
    with pytest.raises(ValueError, match="link"):
        storage.build_plan(tmp_path, selected(case, case["scratch"]), case["contract"])
    assert path.read_bytes() == case["content"]


def test_capacity_stops_generated_admission_without_evicting_core(tmp_path, monkeypatch):
    case = setup_case(tmp_path)
    area = "agent-work" if storage.ROOT.name == "self-evolve" else "diagnostics"
    p = tmp_path / area / "synthetic.json"
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(case["content"])
    with pytest.raises(ValueError, match="capacity"):
        storage.enforce_capacity(tmp_path, area + "/next.json", max_files=1)
    storage.enforce_capacity(tmp_path, case["core"], max_files=1)
    assert (tmp_path / case["core"]).read_bytes() == case["content"]


@pytest.mark.parametrize("path", ["../outside", ".git/config", ".GIT/config", "x/../core", "/absolute", "x:stream"])
def test_retirement_path_cannot_escape_data(path):
    with pytest.raises(ValueError):
        storage.relative_name(path)


def test_glob_star_cannot_hide_an_extra_path_component():
    assert storage.matches("dossiers/case/report.pdf", "dossiers/*/*.pdf")
    assert not storage.matches("dossiers/case/old/report.pdf", "dossiers/*/*.pdf")


def test_run_limit_counts_empty_runs_and_allows_existing_run(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_RUNS", 1)
    (tmp_path / "targets/synthetic-target/runs/first").mkdir(parents=True)
    storage.enforce_capacity(tmp_path, "targets/synthetic-target/runs/first")
    with pytest.raises(ValueError, match="Run capacity"):
        storage.enforce_capacity(tmp_path, "targets/synthetic-target/runs/second")


def test_repository_contract_projects_into_data_without_weakening_core(tmp_path):
    case = retention_samples()
    repository = tmp_path / "synthetic-companion"
    data = repository / "data"
    data.mkdir(parents=True)
    for name in ("core", "scratch"):
        path = data / case[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(case["content"])
    original = copy.deepcopy(case["contract"])
    for artifact in original["artifacts"]:
        artifact["path_pattern"] = "data/" + artifact["path_pattern"]
    original["artifacts"].append({"path_pattern": "README.md",
                                  "retention_rule": {"class": "core"}})
    snapshot = copy.deepcopy(original)
    projected = storage.contract_for_data_root(original, data, repository)
    assert original == snapshot
    assert projected["artifacts"] == case["contract"]["artifacts"]
    with pytest.raises(ValueError, match="core"):
        storage.build_plan(data, selected(case, case["core"]), projected)
    assert storage.build_plan(data, selected(case, case["scratch"]), projected)["file_count"] == 1


def test_data_projection_requires_declared_scope_and_repository_confinement(tmp_path):
    case = retention_samples()
    with pytest.raises(ValueError, match="declared"):
        storage.contract_for_data_root(case["contract"], tmp_path / "data", tmp_path)
    with pytest.raises(ValueError, match="companion"):
        storage.contract_for_data_root(case["contract"], tmp_path.parent, tmp_path)


def test_retention_main_projects_verified_data_root_before_planning(tmp_path, monkeypatch, capsys):
    import json
    from tools.sie import runtime_data

    case = retention_samples()
    source = tmp_path / "synthetic-source"
    source.mkdir()
    repository = tmp_path / "synthetic-companion"
    data = repository / "data"
    data.mkdir(parents=True)
    for name in ("core", "scratch"):
        path = data / case[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(case["content"])
    contract = copy.deepcopy(case["contract"])
    contract["tool"] = "self-evolve"
    for artifact in contract["artifacts"]:
        artifact["path_pattern"] = "data/" + artifact["path_pattern"]
    (source / "storage.contract.json").write_text(json.dumps(contract), encoding="utf-8")
    (data / "retention.json").write_text(json.dumps(selected(case, case["core"])), encoding="utf-8")
    monkeypatch.setattr(storage, "ROOT", source)
    monkeypatch.setattr(runtime_data, "_private_root_context", lambda: (data, repository))
    with pytest.raises(ValueError, match="core"):
        storage.main([])
    (data / "retention.json").write_text(json.dumps(selected(case, case["scratch"])), encoding="utf-8")
    storage.main([])
    assert json.loads(capsys.readouterr().out)["file_count"] == 1
    assert (data / case["core"]).read_bytes() == case["content"]
    assert (data / case["scratch"]).read_bytes() == case["content"]
