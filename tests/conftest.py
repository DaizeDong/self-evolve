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
def business_artifact_admission(request, monkeypatch):
    """Isolate business logic from repeated Git transport proofs.

    Dedicated writer and runtime suites execute the complete shared authorizer.
    Other units still use its real contract matcher and destination validation;
    their synthetic PRIVATE environment is established by the session fixture.
    """
    name = request.path.name
    if (name.startswith('test_runtime') or name in {
            'test_storage_writer_contract.py', 'test_sandbox.py',
            'test_worktree_path_compatibility.py', 'test_business_tree_boundaries.py'}):
        return
    import importlib.util
    from tools.sie import runtime_data
    helper = runtime_data.ROOT/'guards/tools/storage_contract.py'
    spec = importlib.util.spec_from_file_location('_test_storage_contract', helper)
    contract_api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract_api)
    contract_api.load_boundary = lambda: SimpleNamespace(
        prove_private_companion=lambda root, visibility: SimpleNamespace(
            root=root, repositories=('synthetic-private',), signature='synthetic-proof'),
        read_private_companion_git=lambda proof, *args: subprocess.CompletedProcess(
            args, 1 if args[0] == 'check-ignore' else 0, stdout='', stderr=''),
        GitError=RuntimeError)

    def authorize(value, *, directory=False):
        path = Path(value).absolute()
        existing = path.parent
        while not existing.exists():
            existing = existing.parent
        repository = runtime_data._nearest_repository(existing)
        try:
            relative = path.relative_to(repository).as_posix()
            return contract_api.authorize_artifact_write(
                runtime_data.ROOT, repository, relative, directory=directory).path
        except ValueError as exc:
            raise runtime_data.DataBoundaryError(str(exc)) from exc

    monkeypatch.setattr(runtime_data, '_authorize_artifact', authorize)


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
