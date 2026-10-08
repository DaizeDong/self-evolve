"""Generate a PRIVATE companion for offline end-to-end tests."""
import json
import subprocess

import pytest

from tools.make_fixtures import runtime_samples


def initialize_companion_history(root, sample):
    """Give a generated PRIVATE test companion a real, empty history."""
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, text=True, encoding='utf-8').stdout.strip()
    tree = git('write-tree')
    commit = git('-c', 'user.name='+sample['git_name'], '-c', 'user.email='+sample['git_email'],
                 'commit-tree', tree, '-m', sample['git_message'])
    git('update-ref', 'HEAD', commit)


@pytest.fixture(scope='session')
def synthetic_runtime_companion(tmp_path_factory):
    # All pytest temporary run directories belong to this generated companion.
    root = tmp_path_factory.getbasetemp()
    data, home = root/'data', root/'synthetic-home'
    data.mkdir()
    proof = home/'.pii-guard/visibility.json'
    proof.parent.mkdir(parents=True)
    sample = runtime_samples()
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'remote','add','origin',sample['origin']],check=True)
    initialize_companion_history(root, sample)
    proof.write_text(json.dumps({'_refreshed':sample['fresh'],sample['slug']:'PRIVATE'}),encoding='utf-8')
    return data, home


@pytest.fixture
def tmp_path(synthetic_runtime_companion):
    """Keep test-owned outputs in an admitted disposable namespace."""
    import tempfile
    data, _ = synthetic_runtime_companion
    scratch = data/'grader-work'
    scratch.mkdir(exist_ok=True)
    from pathlib import Path
    return Path(tempfile.mkdtemp(prefix='case-', dir=scratch))


@pytest.fixture(autouse=True)
def synthetic_runtime_environment(synthetic_runtime_companion, monkeypatch):
    data, home = synthetic_runtime_companion
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR',str(data))
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.delenv('SELF_EVOLVE_CONFIG',raising=False)
    monkeypatch.delenv('SELF_EVOLVE_CONFIG_DIR',raising=False)
