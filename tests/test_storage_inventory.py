"""Metadata inventories never consume runtime payloads or authorize cleanup."""
import builtins
import json
import os
from pathlib import Path

import pytest

from tools.make_fixtures import storage_samples
from tools.sie import runtime_data, storage


@pytest.fixture
def stored_run(tmp_path):
    sample = storage_samples()
    target = tmp_path / 'target'
    target.mkdir()
    run = runtime_data.run_directory(target, sample['run_id'])
    candidate = runtime_data.worktree_directory(target, sample['run_id'])
    for root, files in ((run, sample['run_files']), (candidate, sample['candidate_files'])):
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return target, run, candidate, sample


def test_inventory_reads_no_payloads_and_is_read_only(stored_run, monkeypatch):
    target, run, candidate, sample = stored_run
    previous = {path.relative_to(run) for path in run.rglob('*')}
    original_open, original_path_open = builtins.open, Path.open

    def reject_payload(file):
        if isinstance(file, (str, os.PathLike)):
            path = Path(file)
            if any(path.is_relative_to(root) for root in (run, candidate)):
                raise AssertionError('Inventory opened a runtime payload')

    def guarded_open(file, *args, **kwargs):
        reject_payload(file)
        return original_open(file, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        reject_payload(path)
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', guarded_open)
    monkeypatch.setattr(Path, 'open', guarded_path_open)
    result = storage.inventory(target, sample['run_id'])
    assert result['areas']['run']['files'] == len(sample['run_files'])
    assert result['areas']['candidate']['files'] == 1  # Git metadata is excluded.
    assert result['categories']['CORE']['files'] == 8
    assert result['categories']['UNKNOWN']['files'] == 1
    assert result['issues'] == [{'area': 'run', 'path': 'unclassified.bin', 'kind': 'unclassified_file'}]
    assert result['cleanup_allowed'] is False
    assert result['recovery_verified'] is False
    assert result['status'] == 'review_required'
    assert {path.relative_to(run) for path in run.rglob('*')} == previous


def test_manifest_write_is_explicit_and_does_not_count_itself(stored_run):
    target, run, candidate, sample = stored_run
    before = storage.inventory(target, sample['run_id'])
    assert not (run / storage.MANIFEST_FILE).exists()
    assert storage.inventory(target, sample['run_id'], write=True) == before
    assert json.loads((run / storage.MANIFEST_FILE).read_text(encoding='utf-8')) == before
    assert storage.inventory(target, sample['run_id'], write=True) == before


def test_missing_run_stays_missing_and_cannot_receive_a_manifest(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    run_id = storage_samples()['run_id']
    run = runtime_data.run_directory(target, run_id)
    result = storage.inventory(target, run_id)
    assert result['areas']['run']['exists'] is False
    assert result['status'] == 'uninitialized'
    assert not run.exists()
    with pytest.raises(FileNotFoundError):
        storage.inventory(target, run_id, write=True)
    assert not run.exists()


def test_unknown_files_stay_visible_with_bounded_issue_samples(stored_run):
    target, run, candidate, sample = stored_run
    for index in range(80):
        (run / ('unknown-%03d.bin' % index)).write_bytes(sample['outside_bytes'])
    result = storage.inventory(target, sample['run_id'])
    assert result['categories']['UNKNOWN']['files'] == 81
    assert result['unknown_count'] == 81
    assert len(result['issues']) == 64
    assert result['issues_omitted'] == 17


def test_empty_unknown_directory_is_not_hidden(stored_run):
    target, run, candidate, sample = stored_run
    (run / 'unclassified-directory').mkdir()
    result = storage.inventory(target, sample['run_id'])
    assert result['unknown_count'] == 2
    assert {'area': 'run', 'path': 'unclassified-directory', 'kind': 'unclassified_directory'} in result['issues']


def test_cache_named_regular_file_stays_unknown(stored_run):
    target, run, candidate, sample = stored_run
    (run / '.venv').write_bytes(sample['outside_bytes'])
    (run / '.mypy_cache').mkdir()
    (run / '.mypy_cache' / 'cache.bin').write_bytes(sample['outside_bytes'])
    result = storage.inventory(target, sample['run_id'])
    assert result['unknown_count'] == 2
    assert {'area': 'run', 'path': '.venv', 'kind': 'unclassified_file'} in result['issues']
    assert not any(issue['path'].startswith('.mypy_cache') for issue in result['issues'])


def test_directory_links_are_reported_without_traversal(stored_run, tmp_path):
    target, run, candidate, sample = stored_run
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'sentinel.bin'
    sentinel.write_bytes(sample['outside_bytes'])
    alias = run / 'linked-output'
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(outside), str(alias))
    else:
        alias.symlink_to(outside, target_is_directory=True)
    try:
        result = storage.inventory(target, sample['run_id'])
        assert result['areas']['run']['links'] == 1
        assert result['areas']['run']['files'] == len(sample['run_files'])
        assert {'area': 'run', 'path': 'linked-output', 'kind': 'link_not_followed'} in result['issues']
        assert sentinel.read_bytes() == sample['outside_bytes']
    finally:
        alias.rmdir() if os.name == 'nt' else alias.unlink()


def test_scan_error_is_not_an_empty_success(stored_run, monkeypatch):
    target, run, candidate, sample = stored_run
    original = os.scandir

    def unavailable(path):
        if Path(path) == run:
            raise OSError('Synthetic metadata read failure')
        return original(path)

    monkeypatch.setattr(os, 'scandir', unavailable)
    with pytest.raises(OSError, match='metadata read failure'):
        storage.inventory(target, sample['run_id'], write=True)
    assert not (run / storage.MANIFEST_FILE).exists()


def test_cli_inventory_and_explicit_manifest(stored_run, capsys):
    from tools.sie.cli import main

    target, run, candidate, sample = stored_run
    args = ['storage', '--target', str(target), '--run-id', sample['run_id']]
    assert main(args) == 1
    expected = json.loads(capsys.readouterr().out)
    assert expected['status'] == 'review_required'
    assert not (run / storage.MANIFEST_FILE).exists()
    assert main([*args, '--write-manifest']) == 1
    assert json.loads(capsys.readouterr().out) == expected
    assert json.loads((run / storage.MANIFEST_FILE).read_text(encoding='utf-8')) == expected


def test_cli_missing_run_read_and_write_have_distinct_results(tmp_path, capsys):
    from tools.sie.cli import main

    target = tmp_path / 'target'
    target.mkdir()
    run_id = storage_samples()['run_id']
    args = ['storage', '--target', str(target), '--run-id', run_id]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'uninitialized'
    assert main([*args, '--write-manifest']) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'failed'
    assert not runtime_data.run_directory(target, run_id).exists()


def test_cli_private_proof_failure_is_reported_without_writing(tmp_path, monkeypatch, capsys):
    from tools.sie.cli import main

    def deny(*args, **kwargs):
        raise runtime_data.DataBoundaryError('Synthetic PRIVATE proof failure')

    monkeypatch.setattr(runtime_data, 'run_directory', deny)
    assert main(['storage', '--target', str(tmp_path), '--run-id', storage_samples()['run_id'],
                 '--write-manifest']) == 2
    assert 'PRIVATE proof failure' in json.loads(capsys.readouterr().err)['error']
    assert not list(tmp_path.iterdir())
