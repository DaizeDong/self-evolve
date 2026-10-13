"""Make offline tests incapable of accidentally starting a live model call."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from runtime_fixture_support import synthetic_runtime_companion, synthetic_runtime_environment, tmp_path


@pytest.fixture(autouse=True)
def capacity_excludes_synthetic_test_inputs(synthetic_runtime_companion, monkeypatch):
    """Do not count generated test source repositories as live grader scratch."""
    from tools import storage_retention
    data, _ = synthetic_runtime_companion
    original = storage_retention.files_under

    def files_under(root, relative):
        if Path(root) == data and relative == 'grader-work':
            area = data / relative
            return [path for child in area.iterdir() if not child.name.startswith('case-')
                    for path in original(root, child.relative_to(data).as_posix())] if area.exists() else []
        return original(root, relative)

    monkeypatch.setattr(storage_retention, 'files_under', files_under)


@pytest.fixture(autouse=True)
def offline_models(monkeypatch):
    def blocked_call(*args, **kwargs):
        raise RuntimeError("Live llmcall is disabled in the offline test suite")

    original_run = subprocess.run

    def guarded_run(command, *args, **kwargs):
        if (isinstance(command, (list, tuple)) and command
                and Path(str(command[0])).stem.lower().startswith("python") and any(
                Path(str(arg)).name == "llm_agent_child.py" for arg in command)):
            raise OSError("Agent transport must use an explicit synthetic child in tests")
        return original_run(command, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "llmcall", SimpleNamespace(call=blocked_call))
    monkeypatch.setattr(subprocess, "run", guarded_run)
