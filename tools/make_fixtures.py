"""Generate synthetic examples used by the local regression suite."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.llm_fixtures import artifact_schema_samples, c_evidence_samples, llm_samples


def numeric_score_samples():
    """Generate score boundaries, including integers outside float conversion range."""
    return {
        'artifact': 'Synthetic scoring artifact.',
        'span': 'Synthetic measurement.',
        'attempts': [{'provider': 'codexg', 'success': True}],
        'cases': [
            ('oversized-positive', 10 ** 512, False),
            ('oversized-negative', -(10 ** 512), False),
            ('zero', 0, True),
            ('one', 1, True),
            ('one-quarter', 0.25, True),
            ('three-quarters', 0.75, True),
        ],
    }


def runtime_samples():
    now = datetime.now(timezone.utc)
    return {
        'origin': 'https://github.com/AcmeCorp/synthetic-self-evolve-config.git',
        'slug': 'AcmeCorp/synthetic-self-evolve-config',
        'fresh': now.isoformat(),
        'stale': (now - timedelta(days=31)).isoformat(),
        'future': (now + timedelta(days=1)).isoformat(),
        'run_id': 'synthetic-run',
        'edgar_identity': 'user1@example.com',
        'cache_record': '{}',
        'invalid_git_marker': 'gitdir: synthetic-missing-git-directory\n',
        'long_component': 'synthetic-descendant-' + 'x' * 32,
        'long_path_minimum': 310,
        'nested_origin': 'https://github.com/AcmeCorp/synthetic-nested-config.git',
        'nested_slug': 'AcmeCorp/synthetic-nested-config',
        'git_name': 'Synthetic Fixture',
        'git_email': 'user1@example.com',
        'git_message': 'Synthetic fixture baseline',
        'worktree_file': ('synthetic.txt', 'Synthetic worktree content.\n'),
        'worktree_edit': 'Synthetic local edit.\n',
        'worktree_python_files': {
            'native_sample.py': 'def value():\n    return 2\n',
            'test_native_sample.py': 'from native_sample import value\n\ndef test_value():\n    assert value() == 2\n',
        },
        'worktree_lengths': [('ordinary', 0), ('long', 230), ('extended', 280)],
        'persisted_state': {'run_id': 'synthetic-run', 'phase': 'REFLECT', 'round': 7,
                            'parent_vid': None, 'tier': 'A', 'no_progress': 2},
        'bad_run_ids': ['', '..', '../escape', 'nested/run', 'nested\\run', '/absolute',
                        'C:\\absolute', 'NUL', 'run.', 'run:stream'],
    }


def immutable_samples():
    """Generate committed Python blobs with explicit line endings."""
    identity = runtime_samples()
    return {
        'files': {
            'acceptor.py': b'ACCEPTOR_V1 = 1\n',
            'gate_human.py': b'GATE_V1 = 1\n',
            'propose.py': b'PROPOSE_V1 = 1\n',
        },
        'line_endings': [('lf', b'\n'), ('crlf', b'\r\n')],
        'git_name': identity['git_name'],
        'git_email': identity['git_email'],
        'git_message': identity['git_message'],
    }


def caller_contract_samples():
    """Generate synthetic caller outcomes, policy metadata and inert SSH rules."""
    return {
        'policy': {'group': 'synthetic-policy', 'groups_refused': ['synthetic-other-policy'],
                   'crossed': False},
        'failure': {'ok': False, 'result': '', 'provider': 'cc', 'family': 'claude',
                    'error': 'synthetic backend unavailable',
                    'attempts': [{'provider': 'cc', 'ok': False, 'error': 'synthetic attempt failed'}]},
        'ssh_alias': 'synthetic-git',
        'ssh_config': 'Host synthetic-*\n  HostName github.com\n  ProxyCommand synthetic-never-run\n',
        'ssh_dynamic': 'Match exec "synthetic-never-run"\n  HostName github.com\n',
        'origin_tail': 'AcmeCorp/synthetic-self-evolve-config.git',
        'code': 'value = 1\n',
        'code_path': 'sample.py',
        'artifact': {'sections': [{'anchors': [{'claim': 'Synthetic claim',
                     'span': 'Synthetic span', 'source_url': 'https://example.com/source'}]}]},
        'artifact_path': 'sample.json',
    }


def repair_samples():
    """Generate inert payloads for runtime boundaries and parent restoration."""
    return {
        'profile': {'tier': 'B', 'base_ref': 'synthetic-base'},
        'action': {'run_id': 'synthetic-review', 'round': 3,
                   'action_type': 'human_review', 'payload': {'reason': 'Synthetic review'}},
        'accepted_tree': {'main.py': 'value = 2\n', 'keep.txt': 'Synthetic accepted file.\n',
                          'nested/kept.txt': 'Synthetic nested file.\n'},
        'rejected_tree': {'main.py': 'value = 9\n', 'new.txt': 'Synthetic rejected file.\n'},
        'dimensions': [{'name': 'synthetic::first', 'tier': 'A', 'score': 0.0, 'weight': 1.0},
                       {'name': 'synthetic::second', 'tier': 'A', 'score': 1.0, 'weight': 1.0}],
        'supervisor_baseline': {'dimensions': [{'name': 'pytest', 'tier': 'A', 'score': 0.0, 'weight': 1.0}]},
        'anchors': [{'anchor_id': f'synthetic-{i}', 'claim': f'Synthetic claim {i}', 'span': f'Synthetic span {i}',
                     'source_url': f'https://example.com/source/{i}'} for i in range(30)],
    }



def business_tree_samples():
    """Generate tree contents and junction locations for restoration boundaries."""
    return {
        'accepted_tree': {'main.py': 'value = 2\n', 'file.txt': 'Synthetic accepted file.\n',
                          'nested/kept.txt': 'Synthetic accepted nested file.\n'},
        'rejected_tree': {'main.py': 'value = 9\n'},
        'outside_tree': {'kept.txt': 'Synthetic outside sentinel.\n',
                         'untouched.txt': 'Synthetic outside history.\n'},
        'junction_cases': [('extraneous', 'unwanted'), ('directory', 'nested'),
                           ('file', 'file.txt')],
        'source_junction': 'borrowed',
        'hardlink_source': 'borrowed.txt',
    }


if __name__ == '__main__':
    import json
    print(json.dumps({'runtime': runtime_samples(), 'llm': llm_samples(),
                     'artifact_schema': artifact_schema_samples(),
                     'c_evidence': c_evidence_samples(),
                     'numeric_scores': numeric_score_samples(),
                     'caller_contracts': caller_contract_samples(),
                     'business_trees': business_tree_samples(),
                     'repairs': repair_samples()}, indent=2))
