"""Restoration changes only the selected business tree, including Windows junctions."""
import os
from pathlib import Path
import stat

import pytest

from tools.make_fixtures import business_tree_samples
from tools.sie import business_tree, runtime_data


def _populate(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))


def _assert_files(root, files):
    for name, content in files.items():
        assert (root / name).read_bytes() == content.encode('utf-8')


def _junction(target, alias):
    if os.name != 'nt':
        pytest.skip('Windows junction regression')
    import _winapi
    _winapi.CreateJunction(str(target), str(alias))


def _remove_remaining_junction(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if getattr(info, 'st_reparse_tag', 0) == stat.IO_REPARSE_TAG_MOUNT_POINT:
        # rmdir removes this junction itself; never recurse through its target.
        path.rmdir()


@pytest.fixture
def trees(tmp_path, monkeypatch):
    sample = business_tree_samples()
    source, destination, outside = (tmp_path / name for name in ('source', 'candidate', 'outside'))
    _populate(source, sample['accepted_tree'])
    _populate(destination, sample['rejected_tree'])
    _populate(outside, sample['outside_tree'])
    # This suite isolates recursive restoration from the separately tested Git proof.
    monkeypatch.setattr(runtime_data, 'runtime_directory', lambda p: Path(p).resolve())
    monkeypatch.setattr(runtime_data, 'private_root', lambda: tmp_path)
    monkeypatch.setattr(runtime_data, 'verify_directory', lambda p: (Path(p).resolve(), tmp_path))
    monkeypatch.setattr(runtime_data, '_authorize_artifact', lambda p, **kwargs: Path(p))
    return source, destination, outside, sample


@pytest.mark.parametrize('kind,name', business_tree_samples()['junction_cases'])
def test_restore_removes_child_junction_without_touching_target(trees, kind, name):
    source, destination, outside, sample = trees
    alias = destination / name
    _junction(outside, alias)
    try:
        business_tree.restore(source, destination)
    finally:
        _remove_remaining_junction(alias)
    _assert_files(outside, sample['outside_tree'])
    _assert_files(destination, sample['accepted_tree'])
    assert not (destination / 'unwanted').exists()
    assert business_tree.manifest(destination) == business_tree.manifest(source)


def test_restore_refuses_source_junction_before_destination_changes(trees):
    source, destination, outside, sample = trees
    alias = source / sample['source_junction']
    _junction(outside, alias)
    try:
        with pytest.raises((OSError, runtime_data.DataBoundaryError)):
            business_tree.restore(source, destination)
    finally:
        _remove_remaining_junction(alias)
    _assert_files(outside, sample['outside_tree'])
    _assert_files(destination, sample['rejected_tree'])
    assert sorted(p.name for p in destination.iterdir()) == sorted(sample['rejected_tree'])


def test_restore_breaks_destination_hardlink_without_changing_other_name(trees):
    source, destination, outside, sample = trees
    os.link(outside / 'kept.txt', destination / 'file.txt')
    business_tree.restore(source, destination)
    _assert_files(outside, sample['outside_tree'])
    _assert_files(destination, sample['accepted_tree'])
    assert (destination / 'file.txt').stat().st_nlink == 1


def test_restore_refuses_source_hardlink_before_destination_changes(trees):
    source, destination, outside, sample = trees
    alias = source / sample['hardlink_source']
    os.link(outside / 'kept.txt', alias)
    try:
        with pytest.raises((OSError, runtime_data.DataBoundaryError)):
            business_tree.restore(source, destination)
    finally:
        alias.unlink()
    _assert_files(outside, sample['outside_tree'])
    _assert_files(destination, sample['rejected_tree'])


def test_restore_preserves_excluded_metadata(trees):
    source, destination, outside, sample = trees
    metadata = destination / '.git'
    marker = sample['outside_tree']['untouched.txt']
    metadata.write_text(marker, encoding='utf-8')
    business_tree.restore(source, destination)
    assert metadata.read_text(encoding='utf-8') == marker
    _assert_files(destination, sample['accepted_tree'])
    _assert_files(source, sample['accepted_tree'])


def test_snapshots_omit_cache_directories_but_keep_business_inputs(trees):
    source, destination, outside, sample = trees
    _populate(source, sample['business_inputs'])
    for name in sample['cache_directories']:
        _populate(source / 'nested' / name, sample['outside_tree'])
        _populate(destination / 'nested' / name, sample['outside_tree'])
    snapshot = source.parent / 'snapshot'
    business_tree.snapshot(source, snapshot)
    _assert_files(snapshot, sample['accepted_tree'])
    _assert_files(snapshot, sample['business_inputs'])
    for name in sample['cache_directories']:
        assert not (snapshot / 'nested' / name).exists()
    business_tree.restore(snapshot, destination)
    _assert_files(destination, sample['business_inputs'])
    for name in sample['cache_directories']:
        _assert_files(destination / 'nested' / name, sample['outside_tree'])
    assert business_tree.manifest(snapshot) == business_tree.manifest(destination)


def test_regular_file_with_cache_directory_name_remains_business_data(trees):
    source, destination, outside, sample = trees
    content = sample['outside_tree']['kept.txt']
    (source / '.venv').write_text(content, encoding='utf-8')
    snapshot = source.parent / 'snapshot'
    business_tree.snapshot(source, snapshot)
    assert (snapshot / '.venv').read_text(encoding='utf-8') == content


@pytest.mark.parametrize('cache_name', business_tree_samples()['cache_only_cases'])
def test_cache_only_ancestors_preserve_data_and_match_selected_snapshot(trees, cache_name):
    source, destination, outside, sample = trees
    source_cache = source / 'cache-parent' / 'nested' / cache_name
    destination_cache = destination / 'candidate-only' / 'nested' / cache_name
    _populate(source_cache, sample['outside_tree'])
    _populate(destination_cache, sample['outside_tree'])
    (source / 'empty-business-directory').mkdir()
    required_cache = destination / 'empty-business-directory' / cache_name
    _populate(required_cache, sample['outside_tree'])
    snapshot = source.parent / 'snapshot'

    business_tree.snapshot(source, snapshot)
    assert (snapshot / 'cache-parent' / 'nested').is_dir()
    assert not (snapshot / 'cache-parent' / 'nested' / cache_name).exists()
    assert (snapshot / 'empty-business-directory').is_dir()
    business_tree.restore(snapshot, destination)

    _assert_files(source_cache, sample['outside_tree'])
    _assert_files(destination_cache, sample['outside_tree'])
    _assert_files(required_cache, sample['outside_tree'])
    assert (destination / 'empty-business-directory').is_dir()
    assert business_tree.manifest(source) == business_tree.manifest(snapshot)
    assert business_tree.manifest(destination) != business_tree.manifest(snapshot)
    assert business_tree.matches(snapshot, destination)


def test_matches_requires_business_files_and_empty_directories(trees):
    source, destination, outside, sample = trees
    business_tree.restore(source, destination)
    (source / 'required-empty').mkdir()
    assert not business_tree.matches(source, destination)
    _populate(destination / 'required-empty' / '.venv', sample['outside_tree'])
    assert business_tree.matches(source, destination)
    _populate(destination / 'extra-cache-parent' / '.venv', sample['outside_tree'])
    assert business_tree.matches(source, destination)
    assert not business_tree.matches(destination, source)
    (destination / 'extra-empty').mkdir()
    assert not business_tree.matches(source, destination)
    (destination / 'extra-empty').rmdir()
    (destination / 'main.py').unlink()
    assert not business_tree.matches(source, destination)


def test_matches_does_not_allow_cache_named_junctions(trees):
    source, destination, outside, sample = trees
    business_tree.restore(source, destination)
    parent = destination / 'candidate-only'
    parent.mkdir()
    alias = parent / '.venv'
    _junction(outside, alias)
    try:
        with pytest.raises(OSError, match='reparse point'):
            business_tree.matches(source, destination)
    finally:
        _remove_remaining_junction(alias)
    _assert_files(outside, sample['outside_tree'])


def test_cache_named_junction_is_not_hidden_from_source_boundary(trees):
    source, destination, outside, sample = trees
    alias = source / '.venv'
    _junction(outside, alias)
    try:
        with pytest.raises(OSError, match='reparse point'):
            business_tree.snapshot(source, source.parent / 'snapshot')
    finally:
        _remove_remaining_junction(alias)
    _assert_files(outside, sample['outside_tree'])
