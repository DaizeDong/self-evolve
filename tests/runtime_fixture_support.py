"""Generate a PRIVATE companion for offline end-to-end tests."""
import json
import subprocess

import pytest

from tools.make_fixtures import runtime_samples


@pytest.fixture(scope='session')
def synthetic_runtime_companion(tmp_path_factory):
    # All pytest temporary run directories belong to this generated companion.
    root = tmp_path_factory.getbasetemp()
    data, home = root/'synthetic-runtime-data', root/'synthetic-home'
    data.mkdir()
    proof = home/'.pii-guard/visibility.json'
    proof.parent.mkdir(parents=True)
    sample = runtime_samples()
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'remote','add','origin',sample['origin']],check=True)
    proof.write_text(json.dumps({'_refreshed':sample['fresh'],sample['slug']:'PRIVATE'}),encoding='utf-8')
    return data, home


@pytest.fixture(autouse=True)
def synthetic_runtime_environment(synthetic_runtime_companion, monkeypatch):
    data, home = synthetic_runtime_companion
    monkeypatch.setenv('SELF_EVOLVE_DATA_DIR',str(data))
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.delenv('SELF_EVOLVE_CONFIG',raising=False)
    monkeypatch.delenv('SELF_EVOLVE_CONFIG_DIR',raising=False)
