"""Execute the packaged child with a generated importable fake, never a provider."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.make_fixtures import llm_samples
from tools.sie import agents, reflect, runtime_data
from tools.sie.backends import llm


_REAL_RUN = subprocess.run


@pytest.fixture
def synthetic_child(monkeypatch, tmp_path):
    samples = llm_samples()
    module_dir = tmp_path / "synthetic import with spaces"
    module_dir.mkdir()
    (module_dir / "llmcall.py").write_text(samples["child_module"], encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(module_dir))
    before = Path.cwd()
    directories = []

    def invoke(command, *args, **kwargs):
        if command[0] == sys.executable and Path(command[-1]).name == "llm_agent_child.py":
            assert Path.cwd() == before
            assert Path(command[-1]).is_absolute()
            directories.append(Path(kwargs["cwd"]))
            assert kwargs["shell"] is False
        else:
            assert Path(command[0]).stem == "git", command
        return _REAL_RUN(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", invoke)
    yield samples, directories
    assert Path.cwd() == before
    assert directories and all(not directory.exists() for directory in directories)


def test_real_child_preserves_terminal_metadata(synthetic_child):
    sample, directories = synthetic_child
    out = agents.invoke(sample["prompt"], model="ignored", effort="ignored", timeout_s=1)
    assert out["ok"], out
    assert out["provider"] == "cc" and out["family"] == "claude"
    assert out["attempts"] == sample["attempts"]
    assert directories[0].is_relative_to(runtime_data.private_root())
    assert "model" not in out and "status" not in out


@pytest.mark.parametrize("scenario", ["exception", "pending"])
def test_real_child_failure_cleans_directory(synthetic_child, monkeypatch, scenario):
    sample, _ = synthetic_child
    monkeypatch.setenv("SIE_SYNTHETIC_RESPONSE", scenario)
    out = agents.invoke(sample["prompt"])
    assert not out["ok"] and out["error"]
    if scenario == "pending":
        assert out["status"] == "running"
        assert out["attempts"] == sample["attempts"]


def test_parallel_reflectors_get_distinct_directories(synthetic_child, tmp_path):
    sample, directories = synthetic_child
    original = json.dumps(sample["history"])
    out = reflect.run_reflections_parallel(str(tmp_path), sample["history"], 3)
    assert len(out) == 3 and all(item["ok"] for item in out), out
    assert len(set(directories)) == 3
    assert {item["findings"][0] for item in out} == {str(path) for path in directories}
    assert json.dumps(sample["history"]) == original


@pytest.mark.parametrize("kind", ["proposal", "artifact"])
def test_proposers_use_real_private_child(synthetic_child, tmp_path, monkeypatch, kind):
    sample, _ = synthetic_child
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setenv("SIE_SYNTHETIC_RESPONSE", kind)
    if kind == "proposal":
        (target / sample["code_path"]).write_text(sample["code"], encoding="utf-8")
        result = llm.generate(str(target), [])
    else:
        (target / sample["artifact_path"]).write_text(json.dumps(sample["document"]), encoding="utf-8")
        result = llm.generate_artifact(str(target), [], sample["artifact_path"])
    assert len(result) == 1, result
    assert result[0]["backend"]["provider"] == "cc"
    assert result[0]["backend"]["attempts"] == sample["attempts"]
    assert len(list(target.iterdir())) == 1
