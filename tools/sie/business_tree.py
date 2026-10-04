"""Snapshot and restore business files without changing Git metadata."""
import hashlib
import os
from pathlib import Path
import shutil
import stat
from contextlib import contextmanager
from contextvars import ContextVar

from . import runtime_data

EXCLUDED = frozenset({'.git', '__pycache__', '.sie'})
CACHE_DIRECTORIES = frozenset({
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', '.nox', '.venv', 'node_modules',
})
_SELECTED_SNAPSHOT = ContextVar('self_evolve_selected_snapshot', default=None)


@contextmanager
def selected_snapshot(path):
    """Bind the legacy one-argument discard API to the selected accepted tree."""
    token = _SELECTED_SNAPSHOT.set(path)
    try:
        yield
    finally:
        _SELECTED_SNAPSHOT.reset(token)



def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _cache_only_directory(path):
    """Recognize ordinary cache ancestors without treating empty dirs as caches."""
    info = path.lstat()
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        return False
    children = list(path.iterdir())
    if not children:
        return False
    for child in children:
        info = child.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            return False
        if child.name in CACHE_DIRECTORIES or child.name == '__pycache__':
            continue
        if child.name in EXCLUDED or not _cache_only_directory(child):
            return False
    return True


def _excluded(path):
    if path.name in EXCLUDED:
        return True
    if path.name not in CACHE_DIRECTORIES:
        return False
    info = path.lstat()
    # Do not hide a link or a legitimate regular file behind a cache-like name.
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        return False
    return True


def _entry(path, root, *, missing_ok=False):
    """Inspect one entry only after proving its parents stay inside this tree."""
    relative = path.relative_to(root)
    parent = root
    for component in (None, *relative.parts[:-1]):
        if component is not None:
            parent /= component
        info = parent.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise OSError(f'Linked or non-directory business parent: {parent}')
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    if not _linked(info) and not path.resolve().is_relative_to(root):
        raise OSError(f'Business entry escaped its tree: {path}')
    return info


def manifest(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise FileNotFoundError(f'Business tree is unavailable: {root}')
    entries = {}
    def visit(directory):
        _entry(directory, root)
        for path in directory.iterdir():
            if _excluded(path):
                continue
            info = _entry(path, root)
            name = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                entries[name] = ('symlink', os.readlink(path))
            elif _linked(info):
                raise OSError(f'Unsupported business reparse point: {path}')
            elif stat.S_ISDIR(info.st_mode):
                entries[name] = ('directory',)
                visit(path)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                entries[name] = ('file', hashlib.sha256(path.read_bytes()).hexdigest())
            else:
                raise OSError(f'Unsupported or hardlinked business file: {path}')
    visit(root)
    return entries


def _manifest_matches(expected, actual, destination):
    if any(actual.get(name) != entry for name, entry in expected.items()):
        return False
    root = Path(destination).resolve(strict=True)
    return all(actual[name] == ('directory',) and _cache_only_directory(root / name)
               for name in sorted(actual.keys() - expected.keys()))


def matches(snapshot, destination):
    """Require the snapshot's entries, allowing only extra cache-only directories.

    This comparison is directional: required empty business directories cannot
    disappear, while an unrelated ancestor of retained caches may remain.
    """
    return _manifest_matches(manifest(snapshot), manifest(destination), destination)


def _private_tree(root):
    root = runtime_data.runtime_directory(root)
    if root.exists():
        for directory, names, files in os.walk(root, followlinks=False):
            runtime_data.runtime_directory(directory)
            for name in names:
                runtime_data.runtime_directory(Path(directory)/name)
            for name in files:
                runtime_data.private_file_path(Path(directory)/name)
    return root


def snapshot(source, destination):
    """Copy a complete business tree after proving every existing destination."""
    source = Path(source).resolve(strict=True)
    destination = _private_tree(destination)
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Snapshot and source must be separate trees')
    expected = manifest(source)
    if destination.exists():
        shutil.rmtree(destination)
    def ignored(directory, names):
        return [name for name in names if _excluded(Path(directory) / name)]
    shutil.copytree(source, destination, symlinks=True, ignore=ignored)
    if manifest(destination) != expected:
        raise OSError('Snapshot does not match the business tree')


def restore(source, destination):
    """Mirror a selected snapshot exactly; any failure propagates to the loop."""
    source = runtime_data.runtime_directory(source)
    destination = runtime_data._safe_path(destination)
    _, companion = runtime_data.verify_directory(runtime_data.private_root())
    if destination == companion or not destination.is_relative_to(companion):
        raise runtime_data.DataBoundaryError('Restoration requires a candidate inside the private companion')
    if not destination.is_dir() or source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Restoration requires separate existing trees')
    expected = manifest(source)

    def remove(path):
        info = _entry(path, destination)
        if _linked(info):
            if stat.S_ISDIR(info.st_mode):
                path.rmdir()
            else:
                path.unlink()
            return
        if not stat.S_ISDIR(info.st_mode):
            path.unlink()
            return
        for child in path.iterdir():
            if not _excluded(child):
                remove(child)
        _entry(path, destination)
        if not any(path.iterdir()):
            path.rmdir()

    def mirror(src, dst):
        source_info = _entry(src, source)
        if _linked(source_info) or not stat.S_ISDIR(source_info.st_mode):
            raise OSError(f'Business source directory changed: {src}')
        _entry(dst, destination, missing_ok=True)
        dst.mkdir(parents=True, exist_ok=True)
        destination_info = _entry(dst, destination)
        if _linked(destination_info) or not stat.S_ISDIR(destination_info.st_mode):
            raise OSError(f'Business destination directory changed: {dst}')
        wanted = {p.name: p for p in src.iterdir() if not _excluded(p)}
        for path in dst.iterdir():
            if not _excluded(path) and path.name not in wanted:
                remove(path)
        for name, path in wanted.items():
            info = _entry(path, source)
            target = dst / name
            target_info = _entry(target, destination, missing_ok=True)
            if stat.S_ISLNK(info.st_mode):
                if target_info is not None:
                    remove(target)
                target.symlink_to(os.readlink(path), target_is_directory=bool(
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_DIRECTORY))
            elif _linked(info):
                raise OSError(f'Unsupported business reparse point: {path}')
            elif stat.S_ISDIR(info.st_mode):
                if target_info is not None and (_linked(target_info) or not stat.S_ISDIR(target_info.st_mode)):
                    remove(target)
                mirror(path, target)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                if target_info is not None and (_linked(target_info) or stat.S_ISDIR(target_info.st_mode)
                                                or target_info.st_nlink > 1):
                    remove(target)
                _entry(target, destination, missing_ok=True)
                shutil.copy2(path, target)
            else:
                raise OSError(f'Unsupported or hardlinked business file: {path}')

    mirror(source, destination)
    if (not _manifest_matches(expected, manifest(destination), destination)
            or manifest(source) != expected):
        raise OSError('Restored business tree does not match the selected snapshot')
