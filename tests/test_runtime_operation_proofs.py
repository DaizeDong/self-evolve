"""Generator-owned operation-scoped PRIVATE proof regressions; no live network."""
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from tools.make_fixtures import operation_proof_inputs
from tools.sie import immutable, runtime_data as runtime

RECIPE = operation_proof_inputs()


@pytest.fixture
def scene(tmp_path, monkeypatch):
    repository = tmp_path / "companion"
    (repository / ".git").mkdir(parents=True)
    data = repository / "data"
    data.mkdir()
    home = tmp_path / "home"
    visibility = home / ".pii-guard/visibility.json"
    visibility.parent.mkdir(parents=True)
    sample = RECIPE["runtime"]
    document = {"_refreshed": sample["fresh"], sample["slug"]: "PRIVATE",
                sample["nested_slug"]: "PUBLIC"}
    visibility.write_text(json.dumps(document), encoding="utf-8")
    for key in list(os.environ):
        if key.upper().startswith("GIT_") or key.lower() in {
            "http_proxy", "https_proxy", "all_proxy", "curl_ca_bundle",
            "ssl_cert_file", "ssl_cert_dir", "curl_ssl_backend",
        }:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(data))
    monkeypatch.delenv("SELF_EVOLVE_CONFIG", raising=False)
    monkeypatch.delenv("SELF_EVOLVE_CONFIG_DIR", raising=False)
    state = {"repository": repository, "administration": repository / ".git",
             "fetch": sample["origin"], "push": sample["origin"], "extra": ""}
    calls = []
    boundary_factory = runtime._shared_data_boundary
    boundary = boundary_factory()

    def git(command, cwd, *, env=None):
        calls.append(tuple(command))
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return str(state["repository"])
        if command == ["git", "rev-parse", "--absolute-git-dir"]:
            return str(state["administration"])
        if command == ["git", "config", "--null", "--list"]:
            return ("remote.origin.url\n" + state["fetch"] + "\0"
                    + "remote.origin.pushurl\n" + state["push"] + "\0" + state["extra"])
        if command == ["git", "remote"]:
            return "origin"
        if command[:3] == ["git", "remote", "get-url"]:
            return state["push"] if "--push" in command else state["fetch"]
        raise AssertionError(command)

    monkeypatch.setattr(boundary, "_run", git)
    monkeypatch.setattr(runtime, "_shared_data_boundary", lambda: boundary)
    return SimpleNamespace(repository=repository, data=data, state=state, calls=calls,
                           visibility=visibility, document=document, sample=sample,
                           boundary=boundary, home=home, boundary_factory=boundary_factory, git=git)


def mutate(scene, kind, monkeypatch):
    if kind in {"public", "unknown", "visibility"}:
        scene.document[scene.sample["slug"]] = "UNKNOWN" if kind == "unknown" else "PUBLIC"
        scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    elif kind in {"stale", "future"}:
        scene.document["_refreshed"] = scene.sample[kind]
        scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    elif kind in {"fetch", "push"}:
        scene.state[kind] = scene.sample["nested_origin"]
    elif kind == "transport":
        scene.state["extra"] = "remote.origin.receivepack\nsynthetic-command\0"
    elif kind == "environment":
        monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    elif kind == "marker":
        old = scene.repository / ".git"
        old.rename(scene.repository / "saved-marker")
        old.mkdir()
    elif kind == "configured_root":
        monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(scene.repository / "other-data"))
    elif kind == "nested_repository":
        (scene.data / "nested" / ".git").mkdir()
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("append", [False, True])
def test_each_write_has_one_fresh_proof_and_rechecks_both_configurations(scene, append):
    path = scene.data / RECIPE["file_name"]
    for index, payload in enumerate(RECIPE["payloads"], 1):
        runtime.write_json(path, payload, append=append)
        assert len(scene.calls) == index * RECIPE["proof_queries"]
        assert runtime._DIRECTORY_PROOF.get() is None
    text = path.read_text(encoding="utf-8")
    assert ([json.loads(line) for line in text.splitlines()] if append else json.loads(text)) == (
        RECIPE["payloads"] if append else RECIPE["payloads"][-1])
    assert not Path(str(path) + ".tmp").exists()


def test_standalone_proofs_remain_fresh_and_same_repo_sibling_output_remains_valid(scene):
    target = scene.repository / "sibling" / RECIPE["file_name"]
    for _ in range(2):
        assert runtime.verify_directory(target.parent) == (target.parent, scene.repository)
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]
    scene.calls.clear()
    assert runtime.private_file_path(target) == target
    assert len(scene.calls) == RECIPE["proof_queries"]
    assert not target.exists()


@pytest.mark.parametrize("operation", ["run_directory", "worktree_directory"])
def test_target_namespaces_share_only_the_current_proof_pair(scene, tmp_path, operation):
    target = tmp_path / "target"
    target.mkdir()
    result = getattr(runtime, operation)(target, RECIPE["runtime"]["run_id"])
    assert result.is_relative_to(scene.data)
    assert result.name == RECIPE["runtime"]["run_id"]
    assert len(scene.calls) == RECIPE["proof_queries"]
    assert not result.exists()


@pytest.mark.parametrize("kind", RECIPE["between_calls"])
def test_changed_authority_between_writes_rejects_without_overwrite(scene, monkeypatch, kind):
    path = scene.data / RECIPE["file_name"]
    runtime.write_json(path, RECIPE["payloads"][0])
    before = path.read_bytes()
    count = len(scene.calls)
    mutate(scene, kind, monkeypatch)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][1])
    assert len(scene.calls) > count
    assert path.read_bytes() == before and not Path(str(path) + ".tmp").exists()
    assert runtime._DIRECTORY_PROOF.get() is None


@pytest.mark.parametrize("kind", RECIPE["within_call"])
def test_changed_endpoint_during_proof_pair_cannot_reuse_authority(scene, monkeypatch, kind):
    parent = scene.data / "nested"
    parent.mkdir()
    path = parent / RECIPE["file_name"]
    path.write_text('{"value": 0}', encoding="utf-8")
    original = path.read_bytes()
    verify = runtime.verify_directory

    def change(value, *, expected_repo=None):
        result = verify(value, expected_repo=expected_repo)
        if expected_repo is None:
            mutate(scene, kind, monkeypatch)
        return result

    monkeypatch.setattr(runtime, "verify_directory", change)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][1])
    assert path.read_bytes() == original
    assert not Path(str(path) + ".tmp").exists()
    assert runtime._DIRECTORY_PROOF.get() is None


def test_failed_pair_resets_before_another_fresh_operation(scene, monkeypatch):
    path = scene.data / RECIPE["file_name"]
    verify = runtime.verify_directory
    rejected = False

    def fail_target(value, *, expected_repo=None):
        nonlocal rejected
        if expected_repo is not None and not rejected:
            rejected = True
            raise runtime.DataBoundaryError("Synthetic target refusal")
        return verify(value, expected_repo=expected_repo)

    monkeypatch.setattr(runtime, "verify_directory", fail_target)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][0])
    assert runtime._DIRECTORY_PROOF.get() is None
    first = len(scene.calls)
    runtime.write_json(path, RECIPE["payloads"][1])
    assert len(scene.calls) - first == RECIPE["proof_queries"]
    assert json.loads(path.read_text()) == RECIPE["payloads"][1]


def test_new_configured_repository_gets_new_authority(scene, tmp_path, monkeypatch):
    runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][0])
    other = tmp_path / "other-companion"
    (other / ".git").mkdir(parents=True)
    other_data = other / "data"
    other_data.mkdir()
    scene.state.update(repository=other, administration=other / ".git",
                       fetch=scene.sample["nested_origin"], push=scene.sample["nested_origin"])
    scene.document[scene.sample["nested_slug"]] = "PRIVATE"
    scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(other_data))
    runtime.write_json(other_data / RECIPE["file_name"], RECIPE["payloads"][1])
    assert len(scene.calls) == 2 * RECIPE["proof_queries"]
    assert json.loads((other_data / RECIPE["file_name"]).read_text()) == RECIPE["payloads"][1]


def test_nested_repository_and_expected_repository_mismatch_are_refused(scene):
    nested = scene.data / "nested"
    (nested / ".git").mkdir(parents=True)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.private_file_path(nested / RECIPE["file_name"])
    with pytest.raises(runtime.DataBoundaryError):
        runtime.verify_directory(scene.data, expected_repo=nested)
    assert not (nested / RECIPE["file_name"]).exists()


def test_linked_worktree_marker_binds_its_actual_administration(scene):
    marker = scene.repository / ".git"
    marker.rmdir()
    administration = scene.repository.parent / "synthetic-linked-admin"
    administration.mkdir()
    marker.write_text("gitdir: " + str(administration) + "\n", encoding="utf-8")
    scene.state["administration"] = administration
    path = scene.data / RECIPE["file_name"]
    assert runtime.private_file_path(path) == path
    assert len(scene.calls) == RECIPE["proof_queries"]


@pytest.mark.parametrize("kind", ["symlink", "reparse", "file"])
def test_parent_metadata_is_rejected_before_any_git_proof(scene, monkeypatch, kind):
    original_lstat = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == scene.data:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK if kind == "symlink" else stat.S_IFREG if kind == "file" else stat.S_IFDIR,
                st_file_attributes=1024 if kind == "reparse" else 0,
            )
        return original_lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.private_file_path(scene.data / RECIPE["file_name"])
    assert scene.calls == []


def test_missing_query_receipt_keeps_complete_second_proof(scene, monkeypatch):
    context = scene.boundary._companion_git_context
    visibility = scene.boundary._companion_visibility
    def unrecorded_context(*args):
        return context(*args)
    # A wrapper without the observable query seam cannot issue a reusable receipt.
    wrapper = SimpleNamespace(_companion_git_context=unrecorded_context,
                              _companion_visibility=visibility, GitError=scene.boundary.GitError)
    monkeypatch.setattr(runtime, "_shared_data_boundary", lambda: wrapper)
    assert runtime.runtime_directory(scene.data / "child") == scene.data / "child"
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]


def test_frozen_materialization_keeps_all_committed_bytes_hashes_and_isolation(scene, tmp_path, monkeypatch):
    recipe = operation_proof_inputs(immutable.IMMUTABLE_RELPATHS)
    source = tmp_path / "source"
    sie_root = source / "tools/sie"
    sie_root.mkdir(parents=True)
    for name, body in recipe["frozen"].items():
        (sie_root / name).write_bytes(body)
    native_calls = []

    def git(command, **kwargs):
        native_calls.append(command)
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return SimpleNamespace(stdout=str(source))
        if command[:2] == ["git", "show"]:
            name = command[-1].rsplit("/", 1)[-1]
            assert command[-1].startswith(recipe["base_ref"] + ":tools/sie/")
            return SimpleNamespace(stdout=recipe["frozen"][name])
        raise AssertionError(command)

    monkeypatch.setattr(immutable.subprocess, "run", git)
    frozen = scene.data / "frozen"
    digests = immutable.materialize_frozen(recipe["base_ref"], str(sie_root), str(frozen))
    assert set(digests) == set(immutable.IMMUTABLE_RELPATHS)
    assert len(native_calls) == 1 + len(immutable.IMMUTABLE_RELPATHS)
    assert len(scene.calls) == (1 + len(immutable.IMMUTABLE_RELPATHS)) * RECIPE["proof_queries"]
    for name, body in recipe["frozen"].items():
        assert (frozen / name).read_bytes() == body
        assert digests[name] == hashlib.sha256(body.replace(b"\r\n", b"\n")).hexdigest()
        assert not (frozen / name).stat().st_mode & stat.S_IWUSR
    immutable.verify_immutable(str(sie_root), digests)
    changed = immutable.IMMUTABLE_RELPATHS[0]
    (sie_root / changed).write_text(recipe["candidate_edit"], encoding="utf-8")
    with pytest.raises(immutable.ImmutableViolation):
        immutable.verify_immutable(str(sie_root), digests)
    assert (frozen / changed).read_bytes() == recipe["frozen"][changed]


def test_query_recorder_and_operation_reset_after_shared_proof_error(scene, monkeypatch):
    reader = scene.boundary._run
    context = scene.boundary._companion_git_context
    def fail(*args, **kwargs):
        raise scene.boundary.GitError("Synthetic proof interruption")
    monkeypatch.setattr(scene.boundary, "_companion_git_context", fail)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][0])
    assert scene.boundary._run is reader
    assert runtime._DIRECTORY_PROOF.get() is None
    monkeypatch.setattr(scene.boundary, "_companion_git_context", context)
    runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][1])
    assert len(scene.calls) == RECIPE["proof_queries"]


def test_ssh_policy_keeps_complete_proofs_instead_of_reusing_https_receipt(scene, monkeypatch):
    origin = "git@github.com:" + scene.sample["slug"] + ".git"
    scene.state.update(fetch=origin, push=origin)
    monkeypatch.setattr(scene.boundary, "_ssh_configuration_problem", lambda: None)
    assert runtime.runtime_directory(scene.data / "child") == scene.data / "child"
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]



def test_agent_scratch_first_use_survives_sibling_directory_creation(scene, monkeypatch, tmp_path):
    """Pause after the absent-path snapshot and let a sibling finish first."""
    from threading import Event, Thread, current_thread

    scratch = scene.data / "agent-work"
    snapshot_taken, sibling_finished = Event(), Event()
    observations, errors, paths = {}, {}, {}
    metadata = runtime._directory_metadata
    factory, git = scene.boundary_factory, scene.git

    def fresh_boundary():
        boundary = factory()
        boundary._run = git
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", fresh_boundary)

    def interleave(value):
        before = metadata(value)
        if (Path(value) == scratch and current_thread().name == "delayed-proof"
                and not snapshot_taken.is_set()):
            observations["before"] = before
            marker = runtime._marker_metadata(scene.repository)
            root_metadata = metadata(scene.data)
            environment = runtime._proof_environment()
            authority = dict(scene.state)
            snapshot_taken.set()
            if not sibling_finished.wait(15):
                raise AssertionError("Sibling did not finish the forced interleaving")
            observations["after"] = metadata(value)
            observations["marker_unchanged"] = marker == runtime._marker_metadata(scene.repository)
            observations["root_metadata_unchanged"] = root_metadata == metadata(scene.data)
            observations["environment_unchanged"] = environment == runtime._proof_environment()
            observations["configured_endpoints_unchanged"] = authority == scene.state
        return before

    monkeypatch.setattr(runtime, "_directory_metadata", interleave)

    def use_scratch(role):
        try:
            with runtime.agent_scratch() as path:
                paths[role] = path
                assert path.is_dir() and path.is_relative_to(scene.data)
        except BaseException as exc:
            errors[role] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if role == "sibling":
                sibling_finished.set()

    delayed = Thread(target=use_scratch, args=("delayed",), name="delayed-proof", daemon=True)
    sibling = Thread(target=use_scratch, args=("sibling",), name="sibling-proof", daemon=True)
    delayed.start()
    try:
        assert snapshot_taken.wait(15), "Absent-path metadata snapshot was not reached"
        sibling.start()
        sibling.join(20)
        delayed.join(20)
        assert not sibling.is_alive() and not delayed.is_alive(), "Workers did not finish"
    finally:
        sibling_finished.set()
        delayed.join(20)
        if sibling.ident is not None:
            sibling.join(20)

    before, after = observations["before"], observations["after"]
    assert before[:-1] == after[:-1]
    assert before[-1] == (str(scratch), None)
    assert after[-1][0] == str(scratch) and after[-1][1] is not None
    assert all(observations[key] for key in (
        "marker_unchanged", "root_metadata_unchanged",
        "environment_unchanged", "configured_endpoints_unchanged"))
    assert "sibling" in paths and "sibling" not in errors
    observations["errors"] = errors
    observations["fresh_boundary_instances"] = True
    observations["worker_paths_cleaned"] = all(not path.exists() for path in paths.values())
    receipt = tmp_path / "concurrency-proof-observation.json"
    receipt.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    assert not errors, json.dumps(observations, indent=2)
    assert len(set(paths.values())) == 2 and observations["worker_paths_cleaned"]



@pytest.mark.parametrize("protocol", ["https", "ssh"])
def test_plain_directory_creation_gets_one_complete_fresh_reproof(scene, monkeypatch, protocol):
    requested = scene.data / "created"
    factories = []
    factory, git = scene.boundary_factory, scene.git
    if protocol == "ssh":
        origin = "git@github.com:" + scene.sample["slug"] + ".git"
        scene.state.update(fetch=origin, push=origin)

    def load():
        boundary = factory()
        boundary._run = git
        if protocol == "ssh":
            boundary._ssh_configuration_problem = lambda: None
        factories.append(boundary)
        index = len(factories)
        visibility = boundary._companion_visibility

        def during_proof(*args, **kwargs):
            result = visibility(*args, **kwargs)
            if index == 1:
                requested.mkdir()
            return result

        boundary._companion_visibility = during_proof
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", load)
    assert runtime.verify_directory(requested, expected_repo=scene.repository) == (
        requested, scene.repository)
    assert len(factories) == 2 and factories[0] is not factories[1]
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]
    assert runtime._DIRECTORY_PROOF.get() is None


@pytest.mark.parametrize("kind, expected_proofs", [
    ("existing_identity", 1),
    ("removed_identity", 1),
    ("file", 1),
    ("alias", 1),
    ("reparse", 1),
    ("new_marker", 1),
    ("repository_marker", 1),
    ("environment", 1),
    ("no_receipt", 1),
    ("configuration", 2),
    ("fetch_private", 2),
    ("push_private", 2),
    ("visibility_public", 2),
    ("visibility_unknown", 2),
    ("visibility_stale", 2),
    ("git_failure", 2),
    ("second_creation", 2),
    ("changed_created_identity", 2),
    ("late_marker", 2),
])
def test_directory_creation_never_retries_changed_authority_or_identity(
        scene, monkeypatch, kind, expected_proofs):
    requested = scene.data / "created"
    if kind == "second_creation":
        requested = requested / "leaf"
    if kind in {"existing_identity", "removed_identity"}:
        requested.mkdir()
    scene.document[scene.sample["nested_slug"]] = "PRIVATE"
    scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    factory, git = scene.boundary_factory, scene.git
    factories = []
    original_lstat = Path.lstat

    def change(index):
        if index == 2:
            if kind == "second_creation":
                requested.mkdir()
            elif kind == "changed_created_identity":
                requested.rename(scene.data / "saved-created")
                requested.mkdir()
            elif kind == "late_marker":
                (requested / ".git").mkdir()
            return
        if kind in {"existing_identity", "removed_identity"}:
            requested.rename(scene.data / "saved-existing")
            if kind == "existing_identity":
                requested.mkdir()
            return
        if kind == "file":
            requested.write_text("Synthetic file ancestor", encoding="utf-8")
            return
        if kind == "second_creation":
            requested.parent.mkdir()
        else:
            requested.mkdir()
        if kind in {"alias", "reparse"}:
            def lstat(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                if path == requested:
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK if kind == "alias" else info.st_mode,
                        st_file_attributes=1024 if kind == "reparse" else 0,
                        st_dev=info.st_dev, st_ino=info.st_ino)
                return info
            monkeypatch.setattr(Path, "lstat", lstat)
        elif kind == "new_marker":
            (requested / ".git").mkdir()
        elif kind == "repository_marker":
            (scene.repository / ".git").rename(scene.repository / "saved-marker")
            (scene.repository / ".git").mkdir()
        elif kind == "environment":
            monkeypatch.setenv("SYNTHETIC_DIRECTORY_PROOF_CHANGE", "1")
        elif kind == "configuration":
            scene.state["extra"] = "synthetic.changed\n1\0"
        elif kind in {"fetch_private", "push_private"}:
            scene.state[kind.removesuffix("_private")] = scene.sample["nested_origin"]
        elif kind in {"visibility_public", "visibility_unknown", "visibility_stale"}:
            if kind == "visibility_stale":
                scene.document["_refreshed"] = scene.sample["stale"]
            else:
                scene.document[scene.sample["slug"]] = kind.removeprefix("visibility_").upper()
            scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")

    def load():
        boundary = factory()
        factories.append(boundary)
        index = len(factories)

        def run(command, cwd, *, env=None):
            if kind == "git_failure" and index == 2:
                raise boundary.GitError("Synthetic reproof failure")
            return git(command, cwd, env=env)

        boundary._run = run
        visibility = boundary._companion_visibility

        def during_proof(*args, **kwargs):
            result = visibility(*args, **kwargs)
            change(index)
            return result

        boundary._companion_visibility = during_proof
        if kind == "no_receipt":
            return SimpleNamespace(
                _companion_git_context=boundary._companion_git_context,
                _companion_visibility=boundary._companion_visibility,
                GitError=boundary.GitError)
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", load)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.verify_directory(requested, expected_repo=scene.repository)
    assert len(factories) == expected_proofs
    assert runtime._DIRECTORY_PROOF.get() is None


def test_directory_created_before_verification_keeps_one_fresh_proof(scene):
    requested = scene.data / "already-created"
    requested.mkdir()
    assert runtime.verify_directory(requested, expected_repo=scene.repository) == (
        requested, scene.repository)
    assert len(scene.calls) == RECIPE["standalone_queries"]
    assert runtime._DIRECTORY_PROOF.get() is None


def test_generated_test_source_is_reproducible():
    from tools.make_fixtures import operation_proof_test_source
    assert operation_proof_test_source() == Path(__file__).read_text(encoding="utf-8")
