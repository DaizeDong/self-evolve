"""Resolve run state and disposable agent workspaces in a PRIVATE Git companion."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MAX_PROOF_AGE_DAYS = 30


class DataBoundaryError(RuntimeError):
    """Runtime output has no verified private destination."""


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


def _git(*args):
    try:
        result = subprocess.run(['git', *args], capture_output=True, text=True,
                                encoding='utf-8', check=True,
                                env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr or f'Git exited with status {exc.returncode}'
        else:
            detail = str(exc) or type(exc).__name__
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', errors='replace')
        detail = ' '.join(detail.split())[:480]
        raise DataBoundaryError('Cannot verify the runtime Git companion: '+detail) from exc
    return result.stdout.strip()


def _nearest_repository(path):
    """Find the nearest worktree marker before asking Git to change directories.

    Python can traverse long Windows paths that Git cannot use as its initial
    directory. Both ordinary .git directories and linked-worktree .git files
    establish a boundary; a nested invalid or bare repository cannot fall back
    to an enclosing PRIVATE worktree.
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


def _ssh_hostname(alias):
    """Read ordinary Host/HostName rules without evaluating SSH commands."""
    try:
        lines = (Path.home()/'.ssh/config').read_text(encoding='utf-8').splitlines()
        active, hostname = True, None
        for line in lines:
            tokens = shlex.split(re.sub(r'^(\s*\w+)\s*=\s*', r'\1 ', line), comments=True)
            if not tokens:
                continue
            keyword, values = tokens[0].lower(), tokens[1:]
            if keyword in {'include', 'match', 'canonicaldomains'} or keyword.startswith('canonicalize'):
                raise DataBoundaryError('SSH alias verification supports only ordinary Host/HostName rules')
            if keyword == 'host':
                if not values:
                    raise DataBoundaryError('SSH Host rule has no patterns')
                positive, negated = False, False
                for pattern in values:
                    expression = re.escape(pattern.removeprefix('!').lower()).replace(r'\*', '.*').replace(r'\?', '.')
                    if re.fullmatch(expression, alias.lower()):
                        if pattern.startswith('!'):
                            negated = True
                        else:
                            positive = True
                active = positive and not negated
            elif keyword == 'hostname':
                if len(values) != 1:
                    raise DataBoundaryError('SSH HostName rule must contain one hostname')
                if active and hostname is None:
                    hostname = values[0].lower()
        return hostname
    except (OSError, ValueError) as exc:
        raise DataBoundaryError('Cannot resolve SSH alias from ordinary user configuration') from exc


def _slug(remote):
    is_ssh = True
    if '://' in remote:
        url = urlsplit(remote)
        if url.scheme not in {'https', 'ssh'} or url.password or url.query or url.fragment:
            raise DataBoundaryError('Companion origin must identify a GitHub repository')
        host, name = url.hostname, url.path.lstrip('/')
        is_ssh = url.scheme == 'ssh'
    else:
        match = re.fullmatch(r'(?:[^@/:\s]+@)?([^/:\s]+):([^\s]+)', remote)
        if not match:
            raise DataBoundaryError('Companion origin is missing or unsupported')
        host, name = match.groups()
    host = host.lower() if host else None
    if is_ssh and host and host != 'github.com':
        host = _ssh_hostname(host)
    if host != 'github.com':
        raise DataBoundaryError('Companion origin must identify a GitHub repository')
    name = name.removesuffix('.git')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        raise DataBoundaryError('Invalid companion GitHub identity')
    return name


def _private_visibility(slug):
    path = Path.home()/'.pii-guard/visibility.json'
    try:
        proof = json.loads(path.read_text(encoding='utf-8'))
        stamp = proof['_refreshed']
        if not isinstance(stamp, str):
            raise ValueError('missing timestamp')
        refreshed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if refreshed.tzinfo is None:
            raise ValueError('timestamp must include timezone')
        age = (datetime.now(timezone.utc) - refreshed).total_seconds()
        if not 0 <= age <= MAX_PROOF_AGE_DAYS * 86400:
            raise ValueError('stale or future visibility proof')
        matching = [value for key, value in proof.items() if key.casefold() == slug.casefold()]
        if len(matching) != 1:
            raise ValueError('missing or ambiguous repository proof')
        value = matching[0]
        if isinstance(value, dict):
            value = value.get('v')
        if value != 'PRIVATE':
            raise ValueError('companion is public or visibility is unknown')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DataBoundaryError('PRIVATE companion visibility is unavailable; refresh '
                                '~/.pii-guard/visibility.json before writing runtime data') from exc


def _shared_data_boundary():
    """Load the pinned kit's proof; missing capability cannot authorize a write."""
    path = ROOT/'guards/tools/data_boundary.py'
    if not path.is_file():
        raise DataBoundaryError('Missing guards kit; run git submodule update --init --recursive')
    spec = importlib.util.spec_from_file_location('_self_evolve_data_boundary', path)
    if spec is None or spec.loader is None:
        raise DataBoundaryError('Cannot load the guards data-boundary module')
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        raise DataBoundaryError('Cannot load the guards data-boundary module') from exc
    if (not callable(getattr(module, '_companion_git_context', None))
            or not callable(getattr(module, '_companion_visibility', None))
            or not isinstance(getattr(module, 'GitError', None), type)):
        raise DataBoundaryError('The guards kit lacks the required PRIVATE proof; update its submodule')
    return module


_DIRECTORY_PROOF = ContextVar("self_evolve_directory_proof", default=None)


@contextmanager
def _directory_operation():
    """Own one root/target proof pair; never share authorization between calls."""
    operation = {}
    token = _DIRECTORY_PROOF.set(operation)
    try:
        yield
    finally:
        operation.clear()
        _DIRECTORY_PROOF.reset(token)


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
        raise DataBoundaryError("Runtime data requires a separate PRIVATE companion")
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise DataBoundaryError("Runtime directory resolves to a file")
    return path, _nearest_repository(existing), metadata


def _proof_environment():
    # Compare only in memory; environment values are never logged or persisted.
    return str(ROOT), tuple(sorted(os.environ.items()))


@contextmanager
def _proof_queries(boundary):
    """Record this fresh module's proof inputs without suppressing any Git calls."""
    captured = {"configurations": [], "endpoints": []}
    run = getattr(boundary, "_run", None)
    if not callable(run):
        yield captured
        return

    def record(command, *args, **kwargs):
        result = run(command, *args, **kwargs)
        if tuple(command) == ("git", "config", "--null", "--list"):
            captured["configurations"].append((dict(kwargs.get("env") or {}), result))
        elif tuple(command[:3]) == ("git", "remote", "get-url"):
            captured["endpoints"].extend(result.splitlines())
        return result

    boundary._run = record
    try:
        yield captured
    finally:
        boundary._run = run


def _same_operation_directory(value, expected_repo, proof):
    path, repository, metadata = _directory_location(value)
    if (repository != proof["repo"] or repository != expected_repo
            or not path.is_relative_to(repository)):
        raise DataBoundaryError("Runtime path crossed its private repository boundary")
    if (_proof_environment() != proof["environment"]
            or _directory_metadata(proof["requested"]) != proof["root_metadata"]
            or _marker_metadata(repository) != proof["marker"]
            or _directory_metadata(Path(value).expanduser()) != metadata
            or _safe_path(value) != path):
        raise DataBoundaryError("Runtime PRIVATE proof inputs changed during this operation")
    try:
        for environment, expected in proof["configurations"]:
            current = proof["read_config"](
                ["git", "config", "--null", "--list"], str(repository), env=environment)
            if current != expected:
                raise DataBoundaryError("Runtime Git configuration changed during this operation")
        for destination in proof["destinations"]:
            _private_visibility(destination)
    except (proof["git_error"], OSError, ValueError) as exc:
        raise DataBoundaryError("Cannot revalidate the runtime PRIVATE proof") from exc
    if (_proof_environment() != proof["environment"]
            or _directory_metadata(proof["requested"]) != proof["root_metadata"]
            or _marker_metadata(repository) != proof["marker"]
            or _directory_metadata(Path(value).expanduser()) != metadata
            or _safe_path(value) != path):
        raise DataBoundaryError("Runtime PRIVATE proof inputs changed during revalidation")
    return path, repository


def _only_missing_directories_created(before, after):
    """Allow one resnapshot only when all existing directory identities survived."""
    if len(before) != len(after):
        return False
    created = False
    for (old_path, old_identity), (new_path, new_identity) in zip(before, after):
        if old_path != new_path:
            return False
        if old_identity == new_identity:
            continue
        if (old_identity is not None or new_identity is None
                or not stat.S_ISDIR(new_identity[2])):
            return False
        created = True
    return created


def verify_directory(value, *, expected_repo=None):
    """Prove PRIVATE, allowing one fully rechecked concurrent directory creation."""
    operation = _DIRECTORY_PROOF.get()
    if (operation is not None and operation.get("proof") is not None
            and expected_repo is not None and not operation.get("used")):
        operation["used"] = True
        return _same_operation_directory(value, expected_repo, operation["proof"])
    previous = None
    for attempt in range(2):
        path, repository_marker, metadata = _directory_location(value)
        marker = _marker_metadata(repository_marker)
        environment = _proof_environment()
        if previous is not None and (
                (path, repository_marker, metadata) != previous["location"]
                or marker != previous["marker"] or environment != previous["environment"]):
            raise DataBoundaryError("Runtime PRIVATE proof inputs changed before revalidation")
        boundary = _shared_data_boundary()
        with _proof_queries(boundary) as captured:
            try:
                context = boundary._companion_git_context(str(repository_marker))
                repo = Path(context[0]).resolve()
            except (boundary.GitError, OSError, ValueError) as exc:
                detail = ' '.join(str(exc).split())[:480]
                raise DataBoundaryError('Cannot verify the runtime Git companion: '+detail) from exc
            if (repo != repository_marker or not path.is_relative_to(repo)
                    or repo.is_relative_to(ROOT) or ROOT.is_relative_to(repo)
                    or expected_repo is not None and repo != expected_repo):
                raise DataBoundaryError('Runtime path crossed its private repository boundary')
            try:
                destinations, errors = boundary._companion_visibility(
                    str(repo), str(Path.home()/'.pii-guard/visibility.json'), git_context=context)
            except (boundary.GitError, OSError, ValueError) as exc:
                detail = ' '.join(str(exc).split())[:480]
                raise DataBoundaryError('PRIVATE companion visibility is unavailable: '+detail) from exc
            if errors or not destinations:
                detail = '; '.join(errors)[:480] if errors else 'no PRIVATE destination was proved'
                raise DataBoundaryError('PRIVATE companion visibility is unavailable: '+detail)
        after_path, after_repository, after = _directory_location(value)
        if (after_path != path or after_repository != repository_marker
                or _marker_metadata(repository_marker) != marker
                or _proof_environment() != environment or _safe_path(value) != path):
            raise DataBoundaryError("Runtime PRIVATE proof inputs changed during verification")
        if previous is not None and (
                context != previous["context"] or captured != previous["queries"]
                or tuple(destinations) != previous["destinations"]):
            raise DataBoundaryError("Runtime PRIVATE proof authority changed during revalidation")
        if after != metadata:
            if (attempt or not _only_missing_directories_created(metadata, after)
                    or len(captured["configurations"]) != 3 or not captured["endpoints"]):
                raise DataBoundaryError("Runtime PRIVATE proof inputs changed during verification")
            location = _directory_location(value)
            if (location != (path, repository_marker, after)
                    or _marker_metadata(repository_marker) != marker
                    or _proof_environment() != environment):
                raise DataBoundaryError("Runtime PRIVATE proof inputs changed before revalidation")
            # Bind the newly observed identities, then repeat every Git/PRIVATE query.
            # No failed proof, changed authority, or second creation receives a retry.
            previous = {"location": location, "marker": marker, "environment": environment,
                        "context": context, "queries": captured,
                        "destinations": tuple(destinations)}
            continue
        configurations = captured["configurations"]
        endpoints = captured["endpoints"]
        # HTTPS routing is determined by the rechecked config/environment. SSH also
        # depends on external policy files, so it retains a complete second proof.
        reusable = (len(configurations) == 3 and endpoints
                    and all(isinstance(url, str) and url.startswith("https://github.com/")
                            for url in endpoints))
        if operation is not None and not operation and expected_repo is None and reusable:
            operation["proof"] = {"requested": Path(value).expanduser(), "repo": repo,
                                  "root_metadata": metadata, "marker": marker,
                                  "environment": environment,
                                  "configurations": configurations[-2:],
                                  "destinations": tuple(destinations),
                                  "read_config": boundary._run, "git_error": boundary.GitError}
        return path, repo
    raise DataBoundaryError("Runtime PRIVATE directory proof did not stabilize")


def _private_root_context():
    """Discover and freshly prove the configured PRIVATE root and its repository."""
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
                raise DataBoundaryError(name+' must name an existing PRIVATE companion')
            break
    spec = importlib.util.spec_from_file_location('_self_evolve_runtime_datadir', guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    # Bind this private module instance to its known consumer, including worktrees.
    guard._own_repo_root = lambda: str(ROOT)
    value = guard.resolve_companion_root('self-evolve')
    if value is None:
        raise DataBoundaryError('Set SELF_EVOLVE_CONFIG or SELF_EVOLVE_DATA_DIR to a PRIVATE Git companion')
    selected, repo = verify_directory(value)
    if selected != repo or configured is not None and configured != repo:
        raise DataBoundaryError('SELF_EVOLVE_CONFIG must select the companion repository root')
    return verify_directory(repo/'data', expected_repo=repo)



def private_root():
    """Discover through the pinned guard, then prove PRIVATE before any mkdir."""
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
    with _directory_operation():
        return _target_component_in_operation(target, run_id, kind)


def _target_component_in_operation(target, run_id, kind):
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
    """Check one file against an operation's freshly proved parent."""
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
    """Ask the pinned source contract for permission before the first mutation."""
    helper = ROOT/'guards/tools/storage_contract.py'
    if not helper.is_file():
        raise DataBoundaryError('Missing guards storage contract helper; initialize or update guards')
    spec = importlib.util.spec_from_file_location('_self_evolve_storage_contract', helper)
    if spec is None or spec.loader is None:
        raise DataBoundaryError('Cannot load guards storage contract helper')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        authorize = getattr(module, 'authorize_artifact_write', None)
        if not callable(authorize):
            raise DataBoundaryError('The guards kit lacks source contract write authorization')
        data_root, repo = _private_root_context()
        requested = Path(value).expanduser().absolute()
        if not requested.is_relative_to(data_root):
            raise DataBoundaryError('Runtime artifact writes must stay in the companion data/ layout')
        relative = requested.relative_to(repo).as_posix()
        authorization = authorize(ROOT, repo, relative, directory=directory,
                                  visibility_map=Path.home()/'.pii-guard/visibility.json')
        if not directory and authorization.artifact_id.startswith('runtime-container-'):
            raise DataBoundaryError('Runtime structural directory cannot receive file writes')
        if Path(authorization.path) != requested:
            raise DataBoundaryError('Source contract returned another artifact destination')
        return Path(authorization.path)
    except DataBoundaryError:
        raise
    except (OSError, ImportError, ValueError, RuntimeError) as exc:
        raise DataBoundaryError('Source storage contract refused the artifact: '+str(exc)[:480]) from exc


def private_file_path(value):
    path = _safe_path(value)
    parent = runtime_directory(path.parent)
    path = _file_in_parent(value, parent)
    return _authorize_artifact(path)


def runtime_directory(value):
    """Prove the actual governing repository is the configured PRIVATE companion."""
    with _directory_operation():
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
    """Authorize the concrete scratch name before exclusive directory creation."""
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
