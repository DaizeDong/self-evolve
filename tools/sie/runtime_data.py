"""Resolve run state and disposable agent workspaces in a PRIVATE Git companion."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
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


def verify_directory(value, *, expected_repo=None):
    """Verify canonical containment and visibility without creating a directory."""
    path = _safe_path(value)
    if path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise DataBoundaryError('Runtime data requires a separate PRIVATE companion')
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise DataBoundaryError('Runtime directory resolves to a file')
    repository_marker = _nearest_repository(existing)
    repo = Path(_git('-C', str(repository_marker), 'rev-parse', '--show-toplevel')).resolve()
    if (repo != repository_marker or not path.is_relative_to(repo)
            or repo.is_relative_to(ROOT) or ROOT.is_relative_to(repo)
            or expected_repo is not None and repo != expected_repo):
        raise DataBoundaryError('Runtime path crossed its private repository boundary')
    slug = _slug(_git('-C', str(repo), 'config', '--get', 'remote.origin.url'))
    _private_visibility(slug)
    return path, repo


def private_root():
    """Discover through the pinned guard, then prove PRIVATE before any mkdir."""
    guard_path = ROOT/'guards/tools/datadir.py'
    if not guard_path.is_file():
        raise DataBoundaryError('Missing guards kit; run git submodule update --init --recursive')
    explicit = os.environ.get('SELF_EVOLVE_DATA_DIR')
    if explicit:
        return verify_directory(explicit)[0]
    for name in ('SELF_EVOLVE_CONFIG', 'SELF_EVOLVE_CONFIG_DIR'):
        value = os.environ.get(name)
        if value and not _safe_path(value).is_dir():
            raise DataBoundaryError(name+' must name an existing PRIVATE companion')
    spec = importlib.util.spec_from_file_location('_self_evolve_runtime_datadir', guard_path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    # Bind this private module instance to its known consumer, including worktrees.
    guard._own_repo_root = lambda: str(ROOT)
    value = guard.resolve_data_dir('self-evolve', create=False)
    if value is None:
        raise DataBoundaryError('Set SELF_EVOLVE_CONFIG or SELF_EVOLVE_DATA_DIR to a PRIVATE Git companion')
    return verify_directory(value)[0]


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
    root, repo = verify_directory(private_root())
    identity = hashlib.sha256(os.path.normcase(str(target_path)).encode('utf-8')).hexdigest()
    requested = root/'targets'/identity/kind/run_id
    if kind == 'worktrees':
        parent, _ = verify_directory(requested.parent, expected_repo=repo)
        path = _safe_path(requested)
        if path.parent != parent:
            raise DataBoundaryError('Candidate worktree escaped its private namespace')
    else:
        path, _ = verify_directory(requested, expected_repo=repo)
    if not path.is_relative_to(root):
        raise DataBoundaryError('Run directory escaped the private data root')
    return path


def run_directory(target, run_id):
    return _target_component(target, run_id, 'runs')


def worktree_directory(target, run_id):
    return _target_component(target, run_id, 'worktrees')


def private_file_path(value):
    path = _safe_path(value)
    parent = runtime_directory(path.parent)
    if path.parent != parent or path.is_dir():
        raise DataBoundaryError('Runtime report must be a file in the PRIVATE companion')
    if path.exists() and path.stat().st_nlink > 1:
        raise DataBoundaryError('Runtime report cannot be a hard link')
    return path


def runtime_directory(value):
    """Prove the actual governing repository is the configured PRIVATE companion."""
    root, repo = verify_directory(private_root())
    path, _ = verify_directory(value, expected_repo=repo)
    return path


def make_directory(value):
    path = runtime_directory(value)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(value, payload, *, append=False):
    """Write unchanged JSON payloads only after checking every destination."""
    path = private_file_path(value)
    temporary = private_file_path(str(path)+'.tmp') if not append else path
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, ensure_ascii=False)+'\n')
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
    root = make_directory(private_root()/'grader-work')
    path = tempfile.mkdtemp(prefix=prefix, dir=runtime_directory(root))
    return str(runtime_directory(path))


@contextmanager
def agent_scratch():
    """Own one private disposable working directory without changing process cwd."""
    root, repo = verify_directory(private_root())
    scratch, _ = verify_directory(root/'agent-work', expected_repo=repo)
    if not scratch.is_relative_to(root):
        raise DataBoundaryError('Agent workspace escaped the private data root')
    scratch.mkdir(parents=True, exist_ok=True)
    verify_directory(scratch, expected_repo=repo)
    with tempfile.TemporaryDirectory(prefix='call-', dir=scratch) as value:
        path, _ = verify_directory(value, expected_repo=repo)
        yield path
