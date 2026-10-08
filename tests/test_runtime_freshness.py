"""Generated fresh-boundary regressions preserve validation between user calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.make_fixtures import runtime_samples, source14_boundary_inputs
from tools.sie import runtime_data


class RuntimeFreshnessTests(unittest.TestCase):
    def setUp(self):
        # This unit isolates PRIVATE freshness; full artifact admission is tested separately.
        patcher = mock.patch.object(runtime_data, '_authorize_artifact',
                                    side_effect=lambda value, **kwargs: Path(value))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_directory_call_proves_root_once_and_target_once(self):
        recipe = source14_boundary_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            target = base / recipe['target_name']
            target.mkdir()
            roots = [base / name / 'data' for name in recipe['root_names']]
            for operation in recipe['operations']:
                with self.subTest(operation=operation):
                    calls = []

                    def verify(value, *, expected_repo=None):
                        path = Path(value)
                        calls.append((path, expected_repo))
                        return path, Path(os.environ['SELF_EVOLVE_DATA_DIR']).parent

                    with mock.patch.object(runtime_data, 'verify_directory', side_effect=verify):
                        for root in roots:
                            with mock.patch.dict(os.environ, SELF_EVOLVE_DATA_DIR=str(root)):
                                before = len(calls)
                                if operation == 'runtime_directory':
                                    requested = root / recipe['output_name']
                                    self.assertEqual(runtime_data.runtime_directory(requested), requested)
                                else:
                                    getattr(runtime_data, operation)(target, recipe['run_id'])
                                current = calls[before:]
                                self.assertEqual(len(current), 1 if operation == 'worktree_directory' else recipe['directory_proofs'])
                                self.assertEqual(current[0], (root, None))
                                if operation != 'worktree_directory':
                                    self.assertEqual(current[1][1], root.parent)

    def test_public_private_root_refreshes_the_environment_each_time(self):
        recipe = source14_boundary_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            roots = [base / name / 'data' for name in recipe['root_names']]
            with mock.patch.object(runtime_data, 'verify_directory',
                                   side_effect=lambda path: (Path(path), Path(path).parent)) as verify:
                for root in roots:
                    with mock.patch.dict(os.environ, SELF_EVOLVE_DATA_DIR=str(root)):
                        self.assertEqual(runtime_data.private_root(), root)
                self.assertEqual(verify.call_args_list, [mock.call(str(root)) for root in roots])

    def test_agent_scratch_retains_post_creation_proofs(self):
        recipe = source14_boundary_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            calls = []

            def verify(value, *, expected_repo=None):
                path = Path(value)
                calls.append((path, expected_repo))
                return path, Path(os.environ['SELF_EVOLVE_DATA_DIR']).parent

            root = base / 'data'
            with mock.patch.dict(os.environ, SELF_EVOLVE_DATA_DIR=str(root)):
                with mock.patch.object(runtime_data, 'verify_directory', side_effect=verify):
                    with runtime_data.agent_scratch() as path:
                        self.assertTrue(path.is_dir())
                        self.assertEqual(len(calls), recipe['scratch_proofs'])
                        self.assertEqual(calls[0], (root, None))
                        self.assertEqual(calls[1:3], [(root / 'agent-work', base)] * 2)
                        self.assertEqual(calls[3], (path, base))
                    self.assertFalse(path.exists())

    def test_changes_after_success_reject_before_the_next_write(self):
        recipe = source14_boundary_inputs()
        for mutation in recipe['mutations']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                sample = runtime_samples()
                home = base / 'home'
                companion = base / 'companion'
                data = companion / 'data'
                data.mkdir(parents=True)
                visibility = home / '.pii-guard/visibility.json'
                visibility.parent.mkdir(parents=True)
                document = {'_refreshed': sample['fresh'], sample['slug']: 'PRIVATE',
                            sample['nested_slug']: 'PUBLIC'}
                visibility.write_text(json.dumps(document), encoding='utf-8')
                empty_config = home / 'empty.gitconfig'
                empty_config.write_text('', encoding='utf-8')
                environment = {key: value for key, value in os.environ.items()
                               if key.upper() in {'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR',
                                                  'PATH', 'TEMP', 'TMP'}}
                environment.update(HOME=str(home), USERPROFILE=str(home),
                                   SELF_EVOLVE_DATA_DIR=str(data),
                                   GIT_CONFIG_GLOBAL=str(empty_config), GIT_CONFIG_NOSYSTEM='1',
                                   GIT_TERMINAL_PROMPT='0', GIT_ALLOW_PROTOCOL='file',
                                   GIT_OPTIONAL_LOCKS='0')
                with mock.patch.dict(os.environ, environment, clear=True):
                    def git(repo, *arguments):
                        subprocess.run(['git', '-C', str(repo), *arguments], check=True,
                                       capture_output=True, text=True, encoding='utf-8', timeout=15)

                    git(companion, 'init', '-q')
                    git(companion, 'config', 'remote.origin.url', sample['origin'])
                    requested = data / recipe['nested_name'] / recipe['output_name']
                    self.assertEqual(runtime_data.runtime_directory(requested), requested)
                    self.assertFalse(requested.exists())
                    overrides = {}
                    if mutation.startswith('visibility_'):
                        if mutation == 'visibility_missing':
                            document.pop(sample['slug'])
                        else:
                            document[sample['slug']] = mutation.removeprefix('visibility_').upper()
                        visibility.write_text(json.dumps(document), encoding='utf-8')
                    elif mutation == 'effective_public_push':
                        overrides.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='remote.origin.pushurl',
                                         GIT_CONFIG_VALUE_0=sample['nested_origin'])
                    elif mutation == 'unversioned_root':
                        unversioned = base / recipe['root_names'][1]
                        unversioned.mkdir()
                        overrides['SELF_EVOLVE_DATA_DIR'] = str(unversioned)
                        requested = unversioned / recipe['output_name']
                    elif mutation == 'nested_private':
                        nested = requested.parent
                        nested.mkdir()
                        git(nested, 'init', '-q')
                        git(nested, 'config', 'remote.origin.url', sample['nested_origin'])
                        document[sample['nested_slug']] = 'PRIVATE'
                        visibility.write_text(json.dumps(document), encoding='utf-8')
                    else:
                        self.fail('Unimplemented generated mutation: ' + mutation)
                    with mock.patch.dict(os.environ, overrides):
                        with self.assertRaises(runtime_data.DataBoundaryError):
                            runtime_data.make_directory(requested)
                    self.assertFalse(requested.exists())


if __name__ == '__main__':
    unittest.main()
