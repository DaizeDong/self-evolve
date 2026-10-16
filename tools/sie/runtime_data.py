"""Resolve run state and disposable agent workspaces in the companion Git repository.

Writes are admitted by path checks only. The data root is decided by companion resolution
(SELF_EVOLVE_DATA_DIR, SELF_EVOLVE_CONFIG, then the fleet_guards resolver) with no in-repository
fallback, and a destination must be absolute and portable, outside this public tool tree and Git
metadata, free of aliases, inside the companion worktree that governs it and, for records, inside its
data/ layout. Commit-time fleet-guards hooks keep the companion's history out of public remotes.
"""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

ROOT = Path(__file__).resolve().parents[2]


class DataBoundaryError(RuntimeError):
    """Runtime output has no acceptable companion destination."""


def _safe_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise DataBoundaryError('Runtime data requires an absolute companion path')
    for part in path.parts[1:]:
        stem = part.split('.', 1)[0].upper()
        if (part.lower() in {'..', '.git'} or ':' in part or part.endswith((' ', '.'))
                or stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?:COM|LPT)[1-9]', stem)):
            raise DataBoundaryError('Runtime data path has an unsafe component')
    resolved = path.resolve()
    if any(part.lower() == '.git' for part in resolved.parts[1:]):
        raise DataBoundaryError('Runtime data cannot reside in Git metadata')
    return resolved


def _nearest_repository(path):
    """The nearest .git marker (directory or linked-worktree file); a nested or bare repository is a boundary."""
    try:
        for candidate in (path, *path.parents):
            marker = candidate/'.git'
            if os.path.lexists(marker):
                if not marker.is_file() and not marker.is_dir():
                    raise DataBoundaryError('Invalid runtime Git worktree marker')
                return candidate
            if (candidate/'HEAD').is_file() and (candidate/'objects').is_dir():
                raise DataBoundaryError('Runtime data cannot reside in a bare Git repository')
    except OSError as exc:
        raise DataBoundaryError('Cannot inspect runtime Git worktree markers: '
                                +str(exc)[:480]) from exc
    raise DataBoundaryError('Runtime directory is not inside a Git worktree')


def _directory_metadata(value):
    """Bind existing directory identities while rejecting aliases and file ancestors."""
    path = Path(value).expanduser()
    identities = []
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            identities.append((str(component), None))
            continue
        except OSError as exc:
            raise DataBoundaryError("Cannot inspect runtime directory identity") from exc
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 1024):
            raise DataBoundaryError("Runtime directory path cannot contain an alias or file")
        identities.append((str(component), (info.st_dev, info.st_ino, info.st_mode)))
    return tuple(identities)


def _check_marker(repository):
    """Refuse an aliased .git marker, a multi-link or unparsable gitdir file, or missing administration."""
    marker = repository / ".git"
    try:
        info = marker.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise DataBoundaryError("Runtime Git marker cannot be an alias")
        if stat.S_ISDIR(info.st_mode):
            _directory_metadata(marker)
            return
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DataBoundaryError("Runtime Git marker must be a regular single-link file")
        match = re.fullmatch(r"gitdir: ([^\r\n]+)\r?\n?", marker.read_bytes().decode("utf-8"))
        if match is None:
            raise DataBoundaryError("Invalid runtime Git worktree marker")
        administration = Path(match.group(1))
        if not administration.is_absolute():
            administration = repository / administration
        _directory_metadata(administration)
        if not administration.is_dir():
            raise DataBoundaryError("Runtime Git administration is missing")
    except (OSError, UnicodeError) as exc:
        raise DataBoundaryError("Cannot inspect runtime Git marker") from exc


def _directory_location(value):
    requested = Path(value).expanduser()
    path = _safe_path(requested)
    _directory_metadata(requested)
    if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise DataBoundaryError("Runtime data requires a separate companion repository")
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise DataBoundaryError("Runtime directory resolves to a file")
    return path, _nearest_repository(existing)


def verify_directory(value, *, expected_repo=None):
    """Return (path, repository) for a runtime directory using path checks only.

    The governing repository is the nearest `.git` marker; it must be valid, separate from this tool
    tree and, when given, equal to `expected_repo`. No Git process runs and no remote is consulted.
    """
    path, repository = _directory_location(value)
    _check_marker(repository)
    if (not path.is_relative_to(repository) or repository.is_relative_to(ROOT)
            or ROOT.is_relative_to(repository)
            or expected_repo is not None and repository != Path(expected_repo)):
        raise DataBoundaryError('Runtime path crossed its private repository boundary')
    return path, repository


@lru_cache(maxsize=None)
def _guard_resolver():
    """The installed fleet_guards companion resolver, bound to this tool tree."""
    try:
        from fleet_guards.runtime import companion_resolver
    except ImportError as exc:
        raise DataBoundaryError('fleet_guards is not installed; install it: '
                                'pip install -e "$(git config --get fleet.guards)"') from exc
    return companion_resolver(source_root=ROOT)


def _private_root_context():
    """Discover the configured companion data root and its repository (path checks only).

    Resolution runs afresh on every call; only the resolver binding is cached.
    """
    explicit = os.environ.get('SELF_EVOLVE_DATA_DIR')
    if explicit:
        root, repo = verify_directory(explicit)
        if root != repo/'data':
            raise DataBoundaryError('SELF_EVOLVE_DATA_DIR must select the companion data/ layout')
        return root, repo
    configured = None
    value = os.environ.get('SELF_EVOLVE_CONFIG')
    if value:
        configured = _safe_path(value)
        if not configured.is_dir():
            raise DataBoundaryError('SELF_EVOLVE_CONFIG must name an existing companion repository')
    value = _guard_resolver().resolve_companion_root('self-evolve')
    if value is None:
        raise DataBoundaryError('Uninitialized: clone the PRIVATE self-evolve-config companion, or set '
                                'SELF_EVOLVE_CONFIG or SELF_EVOLVE_DATA_DIR to its Git repository')
    selected, repo = verify_directory(value)
    if selected != repo or configured is not None and configured != repo:
        raise DataBoundaryError('SELF_EVOLVE_CONFIG must select the companion repository root')
    return verify_directory(repo/'data', expected_repo=repo)



def private_root():
    """Discover through the fleet_guards resolver, then check the path before any mkdir."""
    return _private_root_context()[0]


def validate_run_id(run_id):
    """Validate one portable run path component before any caller writes."""
    if (not isinstance(run_id, str) or not run_id or run_id.strip() != run_id
            or any(ch in run_id for ch in '/\\:<>"|?*') or run_id in {'.', '..'}
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in run_id)):
        raise ValueError('run_id must be one nonempty path component')
    stem = run_id.split('.', 1)[0].upper()
    if (run_id.endswith((' ', '.')) or stem in {'CON', 'PRN', 'AUX', 'NUL'}
            or re.fullmatch(r'(?:COM|LPT)[1-9]', stem)):
        raise ValueError('run_id contains a reserved path component')
    return run_id


def _target_component(target, run_id, kind):
    validate_run_id(run_id)
    target_path = Path(target).expanduser().resolve(strict=True)
    if not target_path.is_dir():
        raise ValueError('target must be a directory')
    root, repo = _private_root_context()
    identity = hashlib.sha256(os.path.normcase(str(target_path)).encode('utf-8')).hexdigest()
    requested = root/'targets'/identity/kind/run_id
    if kind == 'runs':
        from tools.storage_retention import enforce_capacity
        enforce_capacity(root, requested.relative_to(root).as_posix())
    path, _ = verify_directory(requested, expected_repo=repo)
    if not path.is_relative_to(root):
        raise DataBoundaryError('Run directory escaped the private data root')
    return path


def run_directory(target, run_id):
    return _target_component(target, run_id, 'runs')


def worktree_directory(target, run_id):
    """Locate source-only TOOL worktrees without creating a persistent DATA copy."""
    validate_run_id(run_id)
    target_path = Path(target).expanduser().resolve(strict=True)
    if not target_path.is_dir():
        raise ValueError('target must be a directory')
    _, repo = _private_root_context()
    identity = hashlib.sha256(os.path.normcase(str(target_path)).encode('utf-8')).hexdigest()
    workspace = repo.parent/'.worktrees'/'self-evolve'/repo.name/identity/run_id
    _directory_metadata(workspace)
    workspace = _safe_path(workspace)
    if (workspace.is_relative_to(ROOT) or workspace.is_relative_to(target_path)
            or workspace.is_relative_to(repo) or target_path.is_relative_to(workspace)):
        raise DataBoundaryError('Source worktree must be separate from target, source and companion')
    return workspace


def _file_in_parent(value, parent):
    """Check one file against its already checked parent."""
    requested = Path(value).expanduser()
    path = _safe_path(requested)
    if path.parent != parent:
        raise DataBoundaryError('Runtime report must be a file in the PRIVATE companion')
    for component in (*reversed(requested.parents), requested):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise DataBoundaryError('Runtime report path cannot contain an alias')
        if component == requested:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise DataBoundaryError('Runtime report must be a regular single-link file')
        elif not stat.S_ISDIR(info.st_mode):
            raise DataBoundaryError('Runtime report ancestor must be a directory')
    return path


def _authorize_artifact(value, *, root):
    """Refuse a destination outside the companion data/ root before the first mutation."""
    requested = Path(value).expanduser().absolute()
    if not requested.is_relative_to(root):
        raise DataBoundaryError('Runtime artifact writes must stay in the companion data/ layout')
    return requested


def private_file_path(value):
    """Check one runtime file against a single companion resolution."""
    data_root, repo = _private_root_context()
    parent, _ = verify_directory(_safe_path(value).parent, expected_repo=repo)
    return _authorize_artifact(_file_in_parent(value, parent), root=data_root)


def runtime_directory(value):
    """Check that the governing repository is the configured companion."""
    root, repo = _private_root_context()
    path, _ = verify_directory(value, expected_repo=repo)
    return path


def _make_directory(value, data_root, repo):
    path, _ = verify_directory(value, expected_repo=repo)
    _authorize_artifact(path, root=data_root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_directory(value):
    return _make_directory(value, *_private_root_context())


def write_json(value, payload, *, append=False):
    """Write unchanged JSON payloads after checking the destination and its temporary once.

    The temporary is a sibling in the already admitted parent, so it needs only the file checks.
    """
    path = private_file_path(value)
    parent = path.parent
    temporary = _file_in_parent(str(path)+'.tmp', parent) if not append else path
    parent.mkdir(parents=True, exist_ok=True)
    if append:
        record = (json.dumps(payload, ensure_ascii=False)+'\n').encode('utf-8')
        with path.open('a+b') as stream:
            stream.seek(0, 2)
            if stream.tell():
                stream.seek(-1, 2)
                if stream.read(1) != b'\n':
                    stream.write(b'\n')
            stream.write(record)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


def temporary_directory(prefix):
    """Allocate grader scratch alongside other runtime DATA, never in system temp."""
    validate_run_id(prefix)
    from tools.storage_retention import enforce_capacity
    data_root, repo = _private_root_context()
    enforce_capacity(data_root, 'grader-work')
    root = _make_directory(data_root/'grader-work', data_root, repo)
    path = _new_scratch_directory(root, prefix, data_root=data_root)
    return str(verify_directory(path, expected_repo=repo)[0])


def _new_scratch_directory(root, prefix, *, data_root=None):
    """Check the concrete scratch name before exclusive directory creation."""
    validate_run_id(prefix)
    path = _authorize_artifact(Path(root)/(prefix+uuid.uuid4().hex), root=data_root or private_root())
    path.mkdir(mode=0o700)
    return path


@contextmanager
def agent_scratch():
    """Own one private disposable working directory without changing process cwd."""
    root, repo = _private_root_context()
    from tools.storage_retention import enforce_capacity
    enforce_capacity(root, 'agent-work')
    scratch, _ = verify_directory(root/'agent-work', expected_repo=repo)
    if not scratch.is_relative_to(root):
        raise DataBoundaryError('Agent workspace escaped the private data root')
    _authorize_artifact(scratch, root=root)
    scratch.mkdir(parents=True, exist_ok=True)
    verify_directory(scratch, expected_repo=repo)
    path = _new_scratch_directory(scratch, 'call-', data_root=root)
    try:
        path, _ = verify_directory(path, expected_repo=repo)
        yield path
    finally:
        _directory_metadata(path)
        if path.exists():
            shutil.rmtree(path)
