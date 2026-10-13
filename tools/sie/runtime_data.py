"""Resolve run state and disposable agent workspaces in the companion Git repository.

Runtime writes carry no PRIVATE visibility proof. The data root is decided by companion resolution
(SELF_EVOLVE_DATA_DIR, SELF_EVOLVE_CONFIG, then the pinned guards resolver) with no in-repository
fallback, and every destination is refused only by cheap path checks: absolute and portable, outside
this public tool tree and Git metadata, free of aliases, inside the companion worktree that governs it
and, for records, inside its data/ layout. Commit-time Guards hooks and CI keep the companion's
history out of public remotes.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
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
    """Find the nearest worktree marker before asking Git to change directories.

    Python can traverse long Windows paths that Git cannot use as its initial
    directory. Both ordinary .git directories and linked-worktree .git files
    establish a boundary; a nested invalid or bare repository cannot fall back
    to an enclosing companion worktree.
    """
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


def _marker_metadata(repository):
    """Bind both an ordinary marker and a linked worktree's administration."""
    marker = repository / ".git"
    try:
        info = marker.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise DataBoundaryError("Runtime Git marker cannot be an alias")
        identity = (info.st_dev, info.st_ino, info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            return identity, _directory_metadata(marker)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DataBoundaryError("Runtime Git marker must be a regular single-link file")
        body = marker.read_bytes()
        match = re.fullmatch(r"gitdir: ([^\r\n]+)\r?\n?", body.decode("utf-8"))
        if match is None:
            raise DataBoundaryError("Invalid runtime Git worktree marker")
        administration = Path(match.group(1))
        if not administration.is_absolute():
            administration = repository / administration
        metadata = _directory_metadata(administration)
        if not administration.is_dir():
            raise DataBoundaryError("Runtime Git administration is missing")
        after = marker.lstat()
        if (identity != (after.st_dev, after.st_ino, after.st_mode)
                or info.st_size != after.st_size or info.st_mtime_ns != after.st_mtime_ns
                or after.st_nlink != 1):
            raise DataBoundaryError("Runtime Git marker changed during inspection")
        return identity, hashlib.sha256(body).hexdigest(), str(administration.resolve()), metadata
    except (OSError, UnicodeError) as exc:
        raise DataBoundaryError("Cannot inspect runtime Git marker identity") from exc


def _directory_location(value):
    requested = Path(value).expanduser()
    path = _safe_path(requested)
    metadata = _directory_metadata(requested)
    if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise DataBoundaryError("Runtime data requires a separate companion repository")
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise DataBoundaryError("Runtime directory resolves to a file")
    return path, _nearest_repository(existing), metadata


def verify_directory(value, *, expected_repo=None):
    """Return (path, repository) for a runtime directory using path checks only.

    The governing repository is the nearest `.git` marker; it must be valid, separate from this tool
    tree and, when given, equal to `expected_repo`. No Git process runs and no remote is consulted.
    """
    path, repository, metadata = _directory_location(value)
    _marker_metadata(repository)
    if (not path.is_relative_to(repository) or repository.is_relative_to(ROOT)
            or ROOT.is_relative_to(repository)
            or expected_repo is not None and repository != Path(expected_repo)):
        raise DataBoundaryError('Runtime path crossed its private repository boundary')
    if _directory_metadata(Path(value).expanduser()) != metadata or _safe_path(value) != path:
        raise DataBoundaryError('Runtime directory changed during verification')
    return path, repository


def _private_root_context():
    """Discover the configured companion data root and its repository (path checks only)."""
    guard_path = ROOT/'guards/tools/datadir.py'
    if not guard_path.is_file():
        raise DataBoundaryError('Missing guards kit; run git submodule update --init --recursive')
    explicit = os.environ.get('SELF_EVOLVE_DATA_DIR')
    if explicit:
        root, repo = verify_directory(explicit)
        if root != repo/'data':
            raise DataBoundaryError('SELF_EVOLVE_DATA_DIR must select the companion data/ layout')
        return root, repo
    configured = None
    for name in ('SELF_EVOLVE_CONFIG', 'SELF_EVOLVE_CONFIG_DIR'):
        value = os.environ.get(name)
        if value:
            configured = _safe_path(value)
            if not configured.is_dir():
                raise DataBoundaryError(name+' must name an existing companion repository')
            break
    spec = importlib.util.spec_from_file_location('_self_evolve_runtime_datadir', guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    # Bind this private module instance to its known consumer, including worktrees.
    guard._own_repo_root = lambda: str(ROOT)
    value = guard.resolve_companion_root('self-evolve')
    if value is None:
        raise DataBoundaryError('Uninitialized: clone the PRIVATE self-evolve-config companion, or set '
                                'SELF_EVOLVE_CONFIG or SELF_EVOLVE_DATA_DIR to its Git repository')
    selected, repo = verify_directory(value)
    if selected != repo or configured is not None and configured != repo:
        raise DataBoundaryError('SELF_EVOLVE_CONFIG must select the companion repository root')
    return verify_directory(repo/'data', expected_repo=repo)



def private_root():
    """Discover through the pinned guard, then check the path before any mkdir."""
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
    """Locate source-only TOOL worktrees without creating a persistent DATA copy.

    Existing legacy candidates retain their original location until reviewed
    migration. sandbox.make_worktree validates their owning target before resume.
    """
    validate_run_id(run_id)
    target_path = Path(target).expanduser().resolve(strict=True)
    if not target_path.is_dir():
        raise ValueError('target must be a directory')
    root, repo = _private_root_context()
    identity = hashlib.sha256(os.path.normcase(str(target_path)).encode('utf-8')).hexdigest()
    legacy = root/'targets'/identity/'worktrees'/run_id
    if os.path.lexists(legacy):
        _directory_metadata(legacy)
        return legacy
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


def _authorize_artifact(value, *, directory=False):
    """Refuse a destination outside the companion data/ layout before the first mutation."""
    data_root, _ = _private_root_context()
    requested = Path(value).expanduser().absolute()
    if not requested.is_relative_to(data_root):
        raise DataBoundaryError('Runtime artifact writes must stay in the companion data/ layout')
    return requested


def private_file_path(value):
    path = _safe_path(value)
    parent = runtime_directory(path.parent)
    path = _file_in_parent(value, parent)
    return _authorize_artifact(path)


def runtime_directory(value):
    """Check that the governing repository is the configured companion."""
    root, repo = _private_root_context()
    path, _ = verify_directory(value, expected_repo=repo)
    return path


def make_directory(value):
    path = runtime_directory(value)
    _authorize_artifact(path, directory=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(value, payload, *, append=False):
    """Write unchanged JSON payloads only after checking every destination."""
    path = private_file_path(value)
    parent = path.parent
    temporary = _file_in_parent(str(path)+'.tmp', parent) if not append else path
    if not append:
        _authorize_artifact(temporary)
    parent.mkdir(parents=True, exist_ok=True)
    _file_in_parent(path, parent)
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
        _file_in_parent(temporary, parent)
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        _file_in_parent(temporary, parent)
        _file_in_parent(path, parent)
        os.replace(temporary, path)


def temporary_directory(prefix):
    """Allocate grader scratch alongside other runtime DATA, never in system temp."""
    validate_run_id(prefix)
    from tools.storage_retention import enforce_capacity
    data_root = private_root()
    enforce_capacity(data_root, 'grader-work')
    root = make_directory(data_root/'grader-work')
    path = _new_scratch_directory(root, prefix)
    return str(runtime_directory(path))


def _new_scratch_directory(root, prefix):
    """Check the concrete scratch name before exclusive directory creation."""
    validate_run_id(prefix)
    path = _authorize_artifact(Path(root)/(prefix+uuid.uuid4().hex), directory=True)
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
    _authorize_artifact(scratch, directory=True)
    scratch.mkdir(parents=True, exist_ok=True)
    verify_directory(scratch, expected_repo=repo)
    path = _new_scratch_directory(scratch, 'call-')
    try:
        path, _ = verify_directory(path, expected_repo=repo)
        yield path
    finally:
        _directory_metadata(path)
        if path.exists():
            shutil.rmtree(path)
