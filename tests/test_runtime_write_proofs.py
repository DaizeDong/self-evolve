"""Same-operation file checks avoid redundant proofs without caching authority."""
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.make_fixtures import source15_write_inputs
from tools.sie import runtime_data


class RuntimeWriteProofTests(unittest.TestCase):
    def test_each_write_proves_its_parent_afresh_and_preserves_json(self):
        recipe = source15_write_inputs()
        for append in (False, True):
            with self.subTest(append=append), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                path = root / recipe['file_name']
                with mock.patch.object(runtime_data, 'runtime_directory',
                                       side_effect=lambda value: Path(value)) as prove:
                    for index, payload in enumerate(recipe['payloads'], 1):
                        runtime_data.write_json(path, payload, append=append)
                        self.assertEqual(prove.call_count, index)
                        self.assertEqual(prove.call_args, mock.call(root))
                text = path.read_text(encoding='utf-8')
                if append:
                    self.assertEqual([json.loads(line) for line in text.splitlines()],
                                     recipe['payloads'])
                else:
                    self.assertEqual(json.loads(text), recipe['payloads'][-1])
                self.assertFalse(Path(str(path) + '.tmp').exists())

    def test_later_denial_preserves_the_previous_file(self):
        recipe = source15_write_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / recipe['file_name']
            with mock.patch.object(runtime_data, 'runtime_directory', side_effect=[
                    root, runtime_data.DataBoundaryError(recipe['denial'])]) as prove:
                runtime_data.write_json(path, recipe['payloads'][0])
                previous = path.read_bytes()
                with self.assertRaises(runtime_data.DataBoundaryError):
                    runtime_data.write_json(path, recipe['payloads'][1])
                self.assertEqual(prove.call_count, 2)
                self.assertEqual(path.read_bytes(), previous)
                self.assertFalse(Path(str(path) + '.tmp').exists())

    def test_both_destinations_reject_unsafe_file_metadata_before_writing(self):
        recipe = source15_write_inputs()
        modes = {'directory': stat.S_IFDIR, 'symlink': stat.S_IFLNK,
                 'reparse': stat.S_IFREG, 'hardlink': stat.S_IFREG,
                 'special': stat.S_IFIFO}
        for role in recipe['file_roles']:
            for kind in recipe['invalid_file_kinds']:
                with self.subTest(role=role, kind=kind), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary).resolve()
                    path = root / recipe['file_name']
                    path.write_text(recipe['previous_text'], encoding='utf-8')
                    temp_path = Path(str(path) + '.tmp')
                    unsafe = path if role == 'final' else temp_path
                    original_lstat = Path.lstat

                    def metadata(current, *args, **kwargs):
                        if current == unsafe:
                            return SimpleNamespace(st_mode=modes[kind] | 0o600,
                                                   st_nlink=2 if kind == 'hardlink' else 1,
                                                   st_file_attributes=1024 if kind == 'reparse' else 0)
                        return original_lstat(current, *args, **kwargs)

                    with mock.patch.object(runtime_data, 'runtime_directory', return_value=root):
                        with mock.patch.object(Path, 'lstat', metadata):
                            with self.assertRaises(runtime_data.DataBoundaryError):
                                runtime_data.write_json(path, recipe['payloads'][0])
                    self.assertEqual(path.read_text(encoding='utf-8'), recipe['previous_text'])
                    self.assertFalse(temp_path.exists())

    def test_unsafe_parent_metadata_rejects_before_open(self):
        recipe = source15_write_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / recipe['file_name']
            original_lstat = Path.lstat

            def metadata(current, *args, **kwargs):
                if current == root:
                    return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_nlink=1,
                                           st_file_attributes=1024)
                return original_lstat(current, *args, **kwargs)

            with mock.patch.object(runtime_data, 'runtime_directory', return_value=root):
                with mock.patch.object(Path, 'lstat', metadata):
                    with self.assertRaises(runtime_data.DataBoundaryError):
                        runtime_data.write_json(path, recipe['payloads'][0])
            self.assertFalse(path.exists())

    def test_changed_final_metadata_blocks_atomic_replace(self):
        recipe = source15_write_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / recipe['file_name']
            path.write_text(recipe['previous_text'], encoding='utf-8')
            original_lstat, original_dump = Path.lstat, json.dump
            serialized = False

            def dump(*args, **kwargs):
                nonlocal serialized
                original_dump(*args, **kwargs)
                serialized = True

            def metadata(current, *args, **kwargs):
                if serialized and current == path:
                    return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=2,
                                           st_file_attributes=0)
                return original_lstat(current, *args, **kwargs)

            with mock.patch.object(runtime_data, 'runtime_directory', return_value=root):
                with mock.patch.object(json, 'dump', dump), mock.patch.object(Path, 'lstat', metadata):
                    with self.assertRaises(runtime_data.DataBoundaryError):
                        runtime_data.write_json(path, recipe['payloads'][1])
            self.assertTrue(serialized)
            self.assertEqual(path.read_text(encoding='utf-8'), recipe['previous_text'])
