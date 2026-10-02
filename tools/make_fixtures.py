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



def source14_boundary_inputs():
    """Generate fresh-proof call shapes and between-call boundary mutations."""
    return {
        'root_names': ['synthetic-data-one', 'synthetic-data-two'],
        'target_name': 'synthetic-target',
        'output_name': 'uncreated-output',
        'nested_name': 'synthetic-nested',
        'run_id': 'synthetic-fresh-proof',
        'directory_proofs': 2,
        'scratch_proofs': 4,
        'operations': ['runtime_directory', 'run_directory', 'worktree_directory'],
        'mutations': [
            'visibility_public', 'visibility_unknown', 'visibility_missing',
            'effective_public_push', 'unversioned_root', 'nested_private',
        ],
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




def review10_btier_samples():
    """Generate fixed B obligations, lossy proposals and an independent holdout."""
    import copy
    anchors = []
    truth = {}
    for index in range(48):
        key = ("synthetic-%d" % index, "synthetic-metric", "2000-FY")
        truth[key] = 100.0 + index
        anchors.append({
            "anchor_id": "frozen-%d" % index,
            "claim": "Synthetic measurement %d" % index,
            "span": "Synthetic fixed span " + ("x" * 32),
            "source_url": "https://source%d.example.com/report" % index,
            "cik": key[0], "metric": key[1], "period": key[2],
            "expected": truth[key] if index < 32 else truth[key] * 9,
            "verified": False,
        })
    proper = copy.deepcopy(anchors)
    for current in proper:
        current["expected"] = truth[(current["cik"], current["metric"], current["period"])]
    rekeyed = copy.deepcopy(proper)
    shortened = copy.deepcopy(proper)
    for index in range(32):
        rekeyed[index]["metric"] = "substituted-metric"
        shortened[index]["expected"] *= 9
        shortened[index]["span"] = "x"
    for current in shortened[32:]:
        current["span"] = "x" * 4096
    holdout = [{
        "anchor_id": "held-out", "claim": "Synthetic held-out measurement",
        "span": "Synthetic held-out span", "source_url": "https://heldout.example.com/report",
        "cik": "synthetic-heldout", "metric": "synthetic-metric", "period": "2000-FY",
        "expected": 100.0, "verified": False,
    }]
    truth[("synthetic-heldout", "synthetic-metric", "2000-FY")] = 100.0
    return {"frozen": anchors, "proper": proper, "rekeyed": rekeyed, "shortened": shortened,
            "holdout": holdout, "truth": truth, "empty": [], "partial": copy.deepcopy(proper[32:])}


def review10_loop_samples():
    """Generate complete in-memory loop roots and observations."""
    case = review10_btier_samples()
    case.update({
        "run_id": "synthetic-run", "target": "/synthetic/target", "base_ref": "synthetic-base",
        "run_dir": "/synthetic/run", "candidate": "/synthetic/candidate",
        "self_candidate": "/synthetic/self-candidate", "holdout_path": "/synthetic/holdout.json",
        "proposal": {"file_rel": "report.json", "new_content": "{}"},
        "tasks": [{"name": "tests/test_synthetic.py::test_one", "tier": "A", "score": 1.0, "weight": 1.0},
                  {"name": "tests/test_synthetic.py::test_two", "tier": "A", "score": 1.0, "weight": 1.0}],
    })
    return case


def review10_archive_samples():
    """Generate malformed archive inputs alongside the loop task identities."""
    case = review10_loop_samples()
    case["invalid_archive_scores"] = [
        None, {"A": float("nan")}, [{"name": "synthetic-invalid", "score": "invalid"}]]
    return case


def review10_patch_samples():
    """Candidate snippets are parsed only; no snippet is executed."""
    return {
        "sandbox": "/synthetic/sandbox", "target": "/synthetic/sandbox/module.py",
        "allowed": {"os", "pathlib", "builtins", "io"},
        "cases": [
            ("math-future", "from __future__ import annotations\nimport math\nvalue = math.sqrt(4)\n", True),
            ("inside-path", "from pathlib import Path\nPath('result.txt').write_text('Synthetic')\n", True),
            ("direct-os", "import os\nos.system('synthetic-command')\n", False),
            ("os-alias", "import os as runner\nrunner.system('synthetic-command')\n", False),
            ("assigned-os", "import os as runner\nlaunch = runner.system\nlaunch('synthetic-command')\n", False),
            ("keyword-open", "open(file='/synthetic/outside.txt', mode='w')\n", False),
            ("alias-open", "from builtins import open as read_file\nread_file(file='/synthetic/outside.txt')\n", False),
            ("direct-path", "from pathlib import Path\nPath('/synthetic/outside.txt').write_text('Synthetic')\n", False),
            ("alias-path", "from pathlib import Path as P\np = P('/synthetic/outside.txt')\np.unlink()\n", False),
            ("joined-path", "import pathlib as paths\np = paths.Path('/synthetic') / 'outside.txt'\np.read_text()\n", False),
            ("path-destination", "from pathlib import Path\nPath('inside.txt').rename('/synthetic/outside.txt')\n", False),
            ("dynamic-open", "open(file=unknown_path, mode='w')\n", False),
            ("path-bound-alias", "from pathlib import Path\np = Path('/synthetic/outside.txt')\nremove = p.unlink\nremove()\n", False),
            ("path-transform", "from pathlib import Path\nPath('/synthetic/outside.txt').with_name('other.txt').read_text()\n", False),
            ("path-classmethod", "from pathlib import Path\nPath.home().joinpath('other.txt').read_text()\n", False),
            ("path-unbound", "from pathlib import Path\nPath.read_text(Path('/synthetic/outside.txt'))\n", False),

        ],
    }


def review10_calibration_samples():
    """Generate calibration observations with no real target or oracle."""
    ids = ["synthetic-defect-%d" % i for i in range(4)]
    return {
        "ids": ids, "target": "/synthetic/target", "workdir": "/synthetic/work",
        "out": "/synthetic/report.json", "suite_tail": "4 passed in 0.01s",
        "oracle_exits": [(0, "repaired"), (1, "still_broken"), (2, "oracle_errors"),
                         (5, "oracle_errors"), (-1, "oracle_errors")],
        "cases": [
            ("works", {}, True),
            ("suite-fails", {"suite_rc": 1}, False),
            ("zero-repairs", {"repairs": []}, False),
            ("oracle-error", {"oracle_error": True}, False),
            ("duplicate-repair", {"duplicate": True}, False),
            ("suite-unobserved", {"suite_tail": ""}, False),
            ("loop-fails", {"loop_rc": 1}, False),
            ("events-missing", {"events_present": False}, False),
            ("attribution-error", {"attribution_error": True}, False),
            ("baseline-incomplete", {"baseline_count": 3}, False),
        ],
    }


def review11_behavior_samples():
    """Generate synthetic accepted trees, events and probe observations in memory."""
    return {
        "target": "/synthetic/target", "run_id": "r1",
        "run": "/synthetic/private/runs/r1", "sandbox": "/synthetic/private/worktrees/r1",
        "files": {"module.py": "VALUE = 1\n", "notes.md": "Synthetic accepted notes\n"},
        "new_content": "VALUE = 4\n", "extra_file": "pending.txt",
        "extra_directory": "pending-directory", "extra_text": "Synthetic pending edit\n",
        "versions": [{"vid": "v1", "scores": {"A": 1.0}, "parent_vid": "base"},
                     {"vid": "v2", "scores": {"A": 1.0}, "parent_vid": "v1"}],
        "scoring": [
            ("match", True), ("pending-edit", False), ("added-file", False),
            ("deleted-file", False), ("added-directory", False), ("latest-match", True),
            ("stale-match", False), ("no-lineage", False), ("missing-snapshot", False),
            ("malformed-lineage", False), ("non-list-lineage", False),
            ("bad-version", False), ("duplicate-version", False),
        ],
        "bad_version": "../outside", "malformed_lineage": "[",
        "invalid_events": ["{", "[]", "1", '{"type": []}'],
        "init_event": {"type": "INIT", "run_id": "r1", "phase": "INIT", "round": 0,
                       "parent_vid": "base", "tier": "A"},
        "round_event": {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 1},
        "accept_event": {"type": "ACCEPT", "phase": "ARCHIVE", "parent_vid": "v1"},
        "append_tails": [
            ("empty", b""), ("normal-newline", b"\n"),
            ("torn-json", b'{"type": "BROKEN"'),
            ("torn-json-newline", b'{"type": "BROKEN"\n'),
            ("torn-utf8", b'{"type":"BROKEN","note":"\xe4\xb8'),
            ("valid-no-newline", b'{"type":"ROUND_BEGIN","phase":"REFLECT","round":1}'),
        ],
        "mutation": [(0, False), (1, True), (2, True), (3, False), (4, False), (5, False),
                     (-1, False), (17, False)],
        "status": ["before-init", "after-init", "saved-state"],
    }


def runtime_destination_samples():
    """Generate physical/effective Git destination cases without personal records."""
    sample = runtime_samples()
    return {
        "sample": sample,
        "unknown_origin": sample["nested_origin"].replace("synthetic-nested", "synthetic-unseen"),
        "cases": [
            "private", "public", "borrowed_gitdir", "borrowed_origin_override",
            "public_push", "unknown_push", "public_push_override", "public_fetch_rewrite",
            "public_push_rewrite", "borrowed_url_override", "public_secondary_remote",
            "private_secondary_remote", "private_path_with_irrelevant_gitdir",
        ],
    }



def synthetic_artifact(anchor_count=24):
    """Build generated example anchors, with no real issuer or factual source."""
    if not isinstance(anchor_count, int) or isinstance(anchor_count, bool) or anchor_count < 1:
        raise ValueError("anchor_count must be a positive integer")
    return {
        "_fixture": "Synthetic generated data; not a financial report or verified evidence.",
        "title": "Synthetic anchor artifact",
        "sections": [{
            "title": "Generated measurements",
            "anchors": [{
                "claim": f"Synthetic issuer {index:02d} has generated measurement {100 + index}.",
                "span": f"Synthetic measurement {index:02d}: {100 + index}.",
                "source_url": f"https://source{index:02d}.example.com/synthetic-report",
                "metric": "synthetic_measurement",
                "cik": f"synthetic-issuer-{index:02d}",
                "period": "2000-FY",
                "expected": float(100 + index),
            } for index in range(anchor_count)],
        }],
    }


def disk_fixture_payloads():
    """The complete declared set of deterministic public JSON fixtures."""
    return {
        "anchored_artifact.json": synthetic_artifact(2),
        "smallcap_artifact.json": synthetic_artifact(24),
    }


def _fixture_output_path(value):
    """Reject linked directories and files before writing generated fixtures."""
    import os
    import stat
    path = Path(os.path.abspath(value))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("fixture output cannot traverse a linked path")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("fixture output cannot overwrite a hard link")
    return path


def write_disk_fixtures(out):
    """Write fixture basenames under --out, as required by the data-boundary gate."""
    import json
    destination = _fixture_output_path(out)
    destination.mkdir(parents=True, exist_ok=True)
    for filename, payload in disk_fixture_payloads().items():
        path = _fixture_output_path(destination / filename)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    test_path = _fixture_output_path(destination / "test_runtime_operation_proofs.py")
    test_path.write_text(operation_proof_test_source(), encoding="utf-8", newline="\n")
    byte_test = _fixture_output_path(destination / "test_source_byte_preservation.py")
    byte_test.write_text(byte_preservation_test_source(), encoding="utf-8", newline="\n")
    grader_test = _fixture_output_path(destination / "test_mutation_grader_failures.py")
    grader_test.write_text(mutation_grader_failure_test_source(), encoding="utf-8", newline="\n")


def source13_repair_inputs():
    """Generate synthetic cases for repair contracts and independent-state checks."""
    dimensions = [{"name": f"synthetic_test_{i}", "tier": "A", "score": 1.0, "weight": 1.0}
                  for i in range(4)]
    return {
        "grade": {"task_passed": True, "grader_exit_code": 0, "dimensions": dimensions,
                  "verifiable_coverage": 1.0, "anchors": []},
        "profile": {"tier": "A", "anchors_visible": [], "base_ref": "synthetic-base"},
        "invalid_grade_variants": ["failed_exit", "false_pass", "duplicate", "missing_parent",
                                   "invalid_score", "not_a_result", "unavailable", "missing_exit",
                                   "empty_dimensions", "oversized_score", "nan_score", "infinite_score"],
        "invalid_score_values": {"oversized_score": 10 ** 512, "nan_score": float("nan"),
                                 "infinite_score": float("inf")},
        "history": [{"round": 1, "summary": "Synthetic prior result",
                     "details": {"notes": []}}],
        "filesystem": [
            ('local-copy', "import shutil\nshutil.copyfile('input.txt', 'output.txt')\n", True),
            ('local-delete', "import os\nos.remove('old.txt')\n", True),
            ('local-joined', "import os\nos.unlink(os.path.join('cache', 'old.txt'))\n", True),
            ('escape-copy', "import shutil as storage\nstorage.copy2('../private.txt', 'copy.txt')\n", False),
            ('escape-move', "from shutil import move as transfer\ntransfer('item.txt', '../moved.txt')\n", False),
            ('escape-alias', "import os\nremove = os.unlink\nremove('../private.txt')\n", False),
            ('dynamic-delete', 'import os\ndef remove(path):\n    os.remove(path)\n', False),
            ('dynamic-getattr', "import os\ngetattr(os, 'unlink')('../private.txt')\n", False),
            ('unproven-descriptor', "import os\nos.write(descriptor, b'synthetic')\n", False),
            ('default-temp', 'import tempfile\ntempfile.TemporaryDirectory()\n', False),
            ('outside-log', "import logging\nlogging.FileHandler('../private.log')\n", False),
            ('pure-path', "import os\nvalue = os.path.basename('synthetic.txt')\n", True),
            ('local-temp', "import tempfile\ntempfile.TemporaryDirectory(dir='scratch')\n", True),
            ('local-log', "import logging\nlogging.basicConfig(filename='synthetic.log')\n", True),
            ('pure-memory-io', "import io\nvalue = io.StringIO('synthetic')\n", True),
            ('expanded-log', 'import logging\nlogging.basicConfig(**options)\n', False),
            ('dynamic-log-config', 'import logging.config\nlogging.config.dictConfig(settings)\n', False),
            ('expanded-open', "open('synthetic.txt', **options)\n", False),
            ('outside-pattern', "from pathlib import Path\nlist(Path('cache').glob('../../outside/*'))\n", False),
            ('dynamic-path-getattr', "from pathlib import Path\ngetattr(Path('synthetic.txt'), operation)()\n", False),
            ('unbound-outside-pattern', "from pathlib import Path\nlist(Path.glob(Path('cache'), '../../outside/*'))\n", False),
        ],
        "loop_change": {'file_rel': 'synthetic.py', 'new_content': 'VALUE = 1\n', 'fix_content': 'VALUE = 1\n', 'target_failure': 'Synthetic change'},
        "calibration": {
            "defect": {"id": "synthetic-settings", "file_rel": "reader.py", "oracle": "settings"},
            "source": "SETTING_NAME = 'enabled'\n",
            "settings": [{"enabled": True}, {"enabled": False}],
            "versions": [{"vid": "v1", "parent_vid": "base"},
                         {"vid": "v2", "parent_vid": "v1"}],
        },
    }


def source15_write_inputs():
    """Generate same-parent writer and changed-file boundary controls."""
    return {
        'file_name': 'synthetic-state.json',
        'payloads': [{'value': 1}, {'value': 2}],
        'previous_text': '{"value": 0}',
        'invalid_file_kinds': ['directory', 'symlink', 'reparse', 'hardlink', 'special'],
        'file_roles': ['final', 'temporary'],
        'denial': 'Synthetic destination proof denied',
    }


def operation_proof_inputs(immutable_names=()):
    """Synthetic proof costs, boundary changes and committed frozen-file bytes."""
    return {
        "runtime": runtime_samples(),
        "file_name": "synthetic-state.json",
        "payloads": [{"value": 1}, {"value": 2}],
        "proof_queries": 15,
        "standalone_queries": 13,
        "between_calls": ["public", "unknown", "stale", "future", "fetch", "push", "transport"],
        "within_call": ["visibility", "unknown", "stale", "future", "fetch", "push", "transport", "environment",
                        "marker", "configured_root", "nested_repository"],
        "base_ref": "synthetic-base",
        "frozen": {name: (f"# Generated immutable sample {index}\r\nVALUE = {index}\r\n").encode("utf-8")
                   for index, name in enumerate(immutable_names)},
        "candidate_edit": "# Generated candidate mutation\nVALUE = -1\n",
    }


def operation_proof_test_source():
    return r'''"""Generator-owned operation-scoped PRIVATE proof regressions; no live network."""
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from tools.make_fixtures import operation_proof_inputs
from tools.sie import immutable, runtime_data as runtime

RECIPE = operation_proof_inputs()


@pytest.fixture
def scene(tmp_path, monkeypatch):
    repository = tmp_path / "companion"
    (repository / ".git").mkdir(parents=True)
    data = repository / "data"
    data.mkdir()
    home = tmp_path / "home"
    visibility = home / ".pii-guard/visibility.json"
    visibility.parent.mkdir(parents=True)
    sample = RECIPE["runtime"]
    document = {"_refreshed": sample["fresh"], sample["slug"]: "PRIVATE",
                sample["nested_slug"]: "PUBLIC"}
    visibility.write_text(json.dumps(document), encoding="utf-8")
    for key in list(os.environ):
        if key.upper().startswith("GIT_") or key.lower() in {
            "http_proxy", "https_proxy", "all_proxy", "curl_ca_bundle",
            "ssl_cert_file", "ssl_cert_dir", "curl_ssl_backend",
        }:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(data))
    monkeypatch.delenv("SELF_EVOLVE_CONFIG", raising=False)
    monkeypatch.delenv("SELF_EVOLVE_CONFIG_DIR", raising=False)
    state = {"repository": repository, "administration": repository / ".git",
             "fetch": sample["origin"], "push": sample["origin"], "extra": ""}
    calls = []
    boundary_factory = runtime._shared_data_boundary
    boundary = boundary_factory()

    def git(command, cwd, *, env=None):
        calls.append(tuple(command))
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return str(state["repository"])
        if command == ["git", "rev-parse", "--absolute-git-dir"]:
            return str(state["administration"])
        if command == ["git", "config", "--null", "--list"]:
            return ("remote.origin.url\n" + state["fetch"] + "\0"
                    + "remote.origin.pushurl\n" + state["push"] + "\0" + state["extra"])
        if command == ["git", "remote"]:
            return "origin"
        if command[:3] == ["git", "remote", "get-url"]:
            return state["push"] if "--push" in command else state["fetch"]
        raise AssertionError(command)

    monkeypatch.setattr(boundary, "_run", git)
    monkeypatch.setattr(runtime, "_shared_data_boundary", lambda: boundary)
    return SimpleNamespace(repository=repository, data=data, state=state, calls=calls,
                           visibility=visibility, document=document, sample=sample,
                           boundary=boundary, home=home, boundary_factory=boundary_factory, git=git)


def mutate(scene, kind, monkeypatch):
    if kind in {"public", "unknown", "visibility"}:
        scene.document[scene.sample["slug"]] = "UNKNOWN" if kind == "unknown" else "PUBLIC"
        scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    elif kind in {"stale", "future"}:
        scene.document["_refreshed"] = scene.sample[kind]
        scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    elif kind in {"fetch", "push"}:
        scene.state[kind] = scene.sample["nested_origin"]
    elif kind == "transport":
        scene.state["extra"] = "remote.origin.receivepack\nsynthetic-command\0"
    elif kind == "environment":
        monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    elif kind == "marker":
        old = scene.repository / ".git"
        old.rename(scene.repository / "saved-marker")
        old.mkdir()
    elif kind == "configured_root":
        monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(scene.repository / "other-data"))
    elif kind == "nested_repository":
        (scene.data / "nested" / ".git").mkdir()
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("append", [False, True])
def test_each_write_has_one_fresh_proof_and_rechecks_both_configurations(scene, append):
    path = scene.data / RECIPE["file_name"]
    for index, payload in enumerate(RECIPE["payloads"], 1):
        runtime.write_json(path, payload, append=append)
        assert len(scene.calls) == index * RECIPE["proof_queries"]
        assert runtime._DIRECTORY_PROOF.get() is None
    text = path.read_text(encoding="utf-8")
    assert ([json.loads(line) for line in text.splitlines()] if append else json.loads(text)) == (
        RECIPE["payloads"] if append else RECIPE["payloads"][-1])
    assert not Path(str(path) + ".tmp").exists()


def test_standalone_proofs_remain_fresh_and_same_repo_sibling_output_remains_valid(scene):
    target = scene.repository / "sibling" / RECIPE["file_name"]
    for _ in range(2):
        assert runtime.verify_directory(target.parent) == (target.parent, scene.repository)
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]
    scene.calls.clear()
    assert runtime.private_file_path(target) == target
    assert len(scene.calls) == RECIPE["proof_queries"]
    assert not target.exists()


@pytest.mark.parametrize("operation", ["run_directory", "worktree_directory"])
def test_target_namespaces_share_only_the_current_proof_pair(scene, tmp_path, operation):
    target = tmp_path / "target"
    target.mkdir()
    result = getattr(runtime, operation)(target, RECIPE["runtime"]["run_id"])
    assert result.is_relative_to(scene.data)
    assert result.name == RECIPE["runtime"]["run_id"]
    assert len(scene.calls) == RECIPE["proof_queries"]
    assert not result.exists()


@pytest.mark.parametrize("kind", RECIPE["between_calls"])
def test_changed_authority_between_writes_rejects_without_overwrite(scene, monkeypatch, kind):
    path = scene.data / RECIPE["file_name"]
    runtime.write_json(path, RECIPE["payloads"][0])
    before = path.read_bytes()
    count = len(scene.calls)
    mutate(scene, kind, monkeypatch)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][1])
    assert len(scene.calls) > count
    assert path.read_bytes() == before and not Path(str(path) + ".tmp").exists()
    assert runtime._DIRECTORY_PROOF.get() is None


@pytest.mark.parametrize("kind", RECIPE["within_call"])
def test_changed_endpoint_during_proof_pair_cannot_reuse_authority(scene, monkeypatch, kind):
    parent = scene.data / "nested"
    parent.mkdir()
    path = parent / RECIPE["file_name"]
    path.write_text('{"value": 0}', encoding="utf-8")
    original = path.read_bytes()
    verify = runtime.verify_directory

    def change(value, *, expected_repo=None):
        result = verify(value, expected_repo=expected_repo)
        if expected_repo is None:
            mutate(scene, kind, monkeypatch)
        return result

    monkeypatch.setattr(runtime, "verify_directory", change)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][1])
    assert path.read_bytes() == original
    assert not Path(str(path) + ".tmp").exists()
    assert runtime._DIRECTORY_PROOF.get() is None


def test_failed_pair_resets_before_another_fresh_operation(scene, monkeypatch):
    path = scene.data / RECIPE["file_name"]
    verify = runtime.verify_directory
    rejected = False

    def fail_target(value, *, expected_repo=None):
        nonlocal rejected
        if expected_repo is not None and not rejected:
            rejected = True
            raise runtime.DataBoundaryError("Synthetic target refusal")
        return verify(value, expected_repo=expected_repo)

    monkeypatch.setattr(runtime, "verify_directory", fail_target)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(path, RECIPE["payloads"][0])
    assert runtime._DIRECTORY_PROOF.get() is None
    first = len(scene.calls)
    runtime.write_json(path, RECIPE["payloads"][1])
    assert len(scene.calls) - first == RECIPE["proof_queries"]
    assert json.loads(path.read_text()) == RECIPE["payloads"][1]


def test_new_configured_repository_gets_new_authority(scene, tmp_path, monkeypatch):
    runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][0])
    other = tmp_path / "other-companion"
    (other / ".git").mkdir(parents=True)
    other_data = other / "data"
    other_data.mkdir()
    scene.state.update(repository=other, administration=other / ".git",
                       fetch=scene.sample["nested_origin"], push=scene.sample["nested_origin"])
    scene.document[scene.sample["nested_slug"]] = "PRIVATE"
    scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(other_data))
    runtime.write_json(other_data / RECIPE["file_name"], RECIPE["payloads"][1])
    assert len(scene.calls) == 2 * RECIPE["proof_queries"]
    assert json.loads((other_data / RECIPE["file_name"]).read_text()) == RECIPE["payloads"][1]


def test_nested_repository_and_expected_repository_mismatch_are_refused(scene):
    nested = scene.data / "nested"
    (nested / ".git").mkdir(parents=True)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.private_file_path(nested / RECIPE["file_name"])
    with pytest.raises(runtime.DataBoundaryError):
        runtime.verify_directory(scene.data, expected_repo=nested)
    assert not (nested / RECIPE["file_name"]).exists()


def test_linked_worktree_marker_binds_its_actual_administration(scene):
    marker = scene.repository / ".git"
    marker.rmdir()
    administration = scene.repository.parent / "synthetic-linked-admin"
    administration.mkdir()
    marker.write_text("gitdir: " + str(administration) + "\n", encoding="utf-8")
    scene.state["administration"] = administration
    path = scene.data / RECIPE["file_name"]
    assert runtime.private_file_path(path) == path
    assert len(scene.calls) == RECIPE["proof_queries"]


@pytest.mark.parametrize("kind", ["symlink", "reparse", "file"])
def test_parent_metadata_is_rejected_before_any_git_proof(scene, monkeypatch, kind):
    original_lstat = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == scene.data:
            return SimpleNamespace(
                st_mode=stat.S_IFLNK if kind == "symlink" else stat.S_IFREG if kind == "file" else stat.S_IFDIR,
                st_file_attributes=1024 if kind == "reparse" else 0,
            )
        return original_lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.private_file_path(scene.data / RECIPE["file_name"])
    assert scene.calls == []


def test_missing_query_receipt_keeps_complete_second_proof(scene, monkeypatch):
    context = scene.boundary._companion_git_context
    visibility = scene.boundary._companion_visibility
    def unrecorded_context(*args):
        return context(*args)
    # A wrapper without the observable query seam cannot issue a reusable receipt.
    wrapper = SimpleNamespace(_companion_git_context=unrecorded_context,
                              _companion_visibility=visibility, GitError=scene.boundary.GitError)
    monkeypatch.setattr(runtime, "_shared_data_boundary", lambda: wrapper)
    assert runtime.runtime_directory(scene.data / "child") == scene.data / "child"
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]


def test_frozen_materialization_keeps_all_committed_bytes_hashes_and_isolation(scene, tmp_path, monkeypatch):
    recipe = operation_proof_inputs(immutable.IMMUTABLE_RELPATHS)
    source = tmp_path / "source"
    sie_root = source / "tools/sie"
    sie_root.mkdir(parents=True)
    for name, body in recipe["frozen"].items():
        (sie_root / name).write_bytes(body)
    native_calls = []

    def git(command, **kwargs):
        native_calls.append(command)
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return SimpleNamespace(stdout=str(source))
        if command[:2] == ["git", "show"]:
            name = command[-1].rsplit("/", 1)[-1]
            assert command[-1].startswith(recipe["base_ref"] + ":tools/sie/")
            return SimpleNamespace(stdout=recipe["frozen"][name])
        raise AssertionError(command)

    monkeypatch.setattr(immutable.subprocess, "run", git)
    frozen = scene.data / "frozen"
    digests = immutable.materialize_frozen(recipe["base_ref"], str(sie_root), str(frozen))
    assert set(digests) == set(immutable.IMMUTABLE_RELPATHS)
    assert len(native_calls) == 1 + len(immutable.IMMUTABLE_RELPATHS)
    assert len(scene.calls) == (1 + len(immutable.IMMUTABLE_RELPATHS)) * RECIPE["proof_queries"]
    for name, body in recipe["frozen"].items():
        assert (frozen / name).read_bytes() == body
        assert digests[name] == hashlib.sha256(body.replace(b"\r\n", b"\n")).hexdigest()
        assert not (frozen / name).stat().st_mode & stat.S_IWUSR
    immutable.verify_immutable(str(sie_root), digests)
    changed = immutable.IMMUTABLE_RELPATHS[0]
    (sie_root / changed).write_text(recipe["candidate_edit"], encoding="utf-8")
    with pytest.raises(immutable.ImmutableViolation):
        immutable.verify_immutable(str(sie_root), digests)
    assert (frozen / changed).read_bytes() == recipe["frozen"][changed]


def test_query_recorder_and_operation_reset_after_shared_proof_error(scene, monkeypatch):
    reader = scene.boundary._run
    context = scene.boundary._companion_git_context
    def fail(*args, **kwargs):
        raise scene.boundary.GitError("Synthetic proof interruption")
    monkeypatch.setattr(scene.boundary, "_companion_git_context", fail)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][0])
    assert scene.boundary._run is reader
    assert runtime._DIRECTORY_PROOF.get() is None
    monkeypatch.setattr(scene.boundary, "_companion_git_context", context)
    runtime.write_json(scene.data / RECIPE["file_name"], RECIPE["payloads"][1])
    assert len(scene.calls) == RECIPE["proof_queries"]


def test_ssh_policy_keeps_complete_proofs_instead_of_reusing_https_receipt(scene, monkeypatch):
    origin = "git@github.com:" + scene.sample["slug"] + ".git"
    scene.state.update(fetch=origin, push=origin)
    monkeypatch.setattr(scene.boundary, "_ssh_configuration_problem", lambda: None)
    assert runtime.runtime_directory(scene.data / "child") == scene.data / "child"
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]



def test_agent_scratch_first_use_survives_sibling_directory_creation(scene, monkeypatch, tmp_path):
    """Pause after the absent-path snapshot and let a sibling finish first."""
    from threading import Event, Thread, current_thread

    scratch = scene.data / "agent-work"
    snapshot_taken, sibling_finished = Event(), Event()
    observations, errors, paths = {}, {}, {}
    metadata = runtime._directory_metadata
    factory, git = scene.boundary_factory, scene.git

    def fresh_boundary():
        boundary = factory()
        boundary._run = git
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", fresh_boundary)

    def interleave(value):
        before = metadata(value)
        if (Path(value) == scratch and current_thread().name == "delayed-proof"
                and not snapshot_taken.is_set()):
            observations["before"] = before
            marker = runtime._marker_metadata(scene.repository)
            root_metadata = metadata(scene.data)
            environment = runtime._proof_environment()
            authority = dict(scene.state)
            snapshot_taken.set()
            if not sibling_finished.wait(15):
                raise AssertionError("Sibling did not finish the forced interleaving")
            observations["after"] = metadata(value)
            observations["marker_unchanged"] = marker == runtime._marker_metadata(scene.repository)
            observations["root_metadata_unchanged"] = root_metadata == metadata(scene.data)
            observations["environment_unchanged"] = environment == runtime._proof_environment()
            observations["configured_endpoints_unchanged"] = authority == scene.state
        return before

    monkeypatch.setattr(runtime, "_directory_metadata", interleave)

    def use_scratch(role):
        try:
            with runtime.agent_scratch() as path:
                paths[role] = path
                assert path.is_dir() and path.is_relative_to(scene.data)
        except BaseException as exc:
            errors[role] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if role == "sibling":
                sibling_finished.set()

    delayed = Thread(target=use_scratch, args=("delayed",), name="delayed-proof", daemon=True)
    sibling = Thread(target=use_scratch, args=("sibling",), name="sibling-proof", daemon=True)
    delayed.start()
    try:
        assert snapshot_taken.wait(15), "Absent-path metadata snapshot was not reached"
        sibling.start()
        sibling.join(20)
        delayed.join(20)
        assert not sibling.is_alive() and not delayed.is_alive(), "Workers did not finish"
    finally:
        sibling_finished.set()
        delayed.join(20)
        if sibling.ident is not None:
            sibling.join(20)

    before, after = observations["before"], observations["after"]
    assert before[:-1] == after[:-1]
    assert before[-1] == (str(scratch), None)
    assert after[-1][0] == str(scratch) and after[-1][1] is not None
    assert all(observations[key] for key in (
        "marker_unchanged", "root_metadata_unchanged",
        "environment_unchanged", "configured_endpoints_unchanged"))
    assert "sibling" in paths and "sibling" not in errors
    observations["errors"] = errors
    observations["fresh_boundary_instances"] = True
    observations["worker_paths_cleaned"] = all(not path.exists() for path in paths.values())
    receipt = tmp_path / "concurrency-proof-observation.json"
    receipt.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    assert not errors, json.dumps(observations, indent=2)
    assert len(set(paths.values())) == 2 and observations["worker_paths_cleaned"]



@pytest.mark.parametrize("protocol", ["https", "ssh"])
def test_plain_directory_creation_gets_one_complete_fresh_reproof(scene, monkeypatch, protocol):
    requested = scene.data / "created"
    factories = []
    factory, git = scene.boundary_factory, scene.git
    if protocol == "ssh":
        origin = "git@github.com:" + scene.sample["slug"] + ".git"
        scene.state.update(fetch=origin, push=origin)

    def load():
        boundary = factory()
        boundary._run = git
        if protocol == "ssh":
            boundary._ssh_configuration_problem = lambda: None
        factories.append(boundary)
        index = len(factories)
        visibility = boundary._companion_visibility

        def during_proof(*args, **kwargs):
            result = visibility(*args, **kwargs)
            if index == 1:
                requested.mkdir()
            return result

        boundary._companion_visibility = during_proof
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", load)
    assert runtime.verify_directory(requested, expected_repo=scene.repository) == (
        requested, scene.repository)
    assert len(factories) == 2 and factories[0] is not factories[1]
    assert len(scene.calls) == 2 * RECIPE["standalone_queries"]
    assert runtime._DIRECTORY_PROOF.get() is None


@pytest.mark.parametrize("kind, expected_proofs", [
    ("existing_identity", 1),
    ("removed_identity", 1),
    ("file", 1),
    ("alias", 1),
    ("reparse", 1),
    ("new_marker", 1),
    ("repository_marker", 1),
    ("environment", 1),
    ("no_receipt", 1),
    ("configuration", 2),
    ("fetch_private", 2),
    ("push_private", 2),
    ("visibility_public", 2),
    ("visibility_unknown", 2),
    ("visibility_stale", 2),
    ("git_failure", 2),
    ("second_creation", 2),
    ("changed_created_identity", 2),
    ("late_marker", 2),
])
def test_directory_creation_never_retries_changed_authority_or_identity(
        scene, monkeypatch, kind, expected_proofs):
    requested = scene.data / "created"
    if kind == "second_creation":
        requested = requested / "leaf"
    if kind in {"existing_identity", "removed_identity"}:
        requested.mkdir()
    scene.document[scene.sample["nested_slug"]] = "PRIVATE"
    scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")
    factory, git = scene.boundary_factory, scene.git
    factories = []
    original_lstat = Path.lstat

    def change(index):
        if index == 2:
            if kind == "second_creation":
                requested.mkdir()
            elif kind == "changed_created_identity":
                requested.rename(scene.data / "saved-created")
                requested.mkdir()
            elif kind == "late_marker":
                (requested / ".git").mkdir()
            return
        if kind in {"existing_identity", "removed_identity"}:
            requested.rename(scene.data / "saved-existing")
            if kind == "existing_identity":
                requested.mkdir()
            return
        if kind == "file":
            requested.write_text("Synthetic file ancestor", encoding="utf-8")
            return
        if kind == "second_creation":
            requested.parent.mkdir()
        else:
            requested.mkdir()
        if kind in {"alias", "reparse"}:
            def lstat(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                if path == requested:
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK if kind == "alias" else info.st_mode,
                        st_file_attributes=1024 if kind == "reparse" else 0,
                        st_dev=info.st_dev, st_ino=info.st_ino)
                return info
            monkeypatch.setattr(Path, "lstat", lstat)
        elif kind == "new_marker":
            (requested / ".git").mkdir()
        elif kind == "repository_marker":
            (scene.repository / ".git").rename(scene.repository / "saved-marker")
            (scene.repository / ".git").mkdir()
        elif kind == "environment":
            monkeypatch.setenv("SYNTHETIC_DIRECTORY_PROOF_CHANGE", "1")
        elif kind == "configuration":
            scene.state["extra"] = "synthetic.changed\n1\0"
        elif kind in {"fetch_private", "push_private"}:
            scene.state[kind.removesuffix("_private")] = scene.sample["nested_origin"]
        elif kind in {"visibility_public", "visibility_unknown", "visibility_stale"}:
            if kind == "visibility_stale":
                scene.document["_refreshed"] = scene.sample["stale"]
            else:
                scene.document[scene.sample["slug"]] = kind.removeprefix("visibility_").upper()
            scene.visibility.write_text(json.dumps(scene.document), encoding="utf-8")

    def load():
        boundary = factory()
        factories.append(boundary)
        index = len(factories)

        def run(command, cwd, *, env=None):
            if kind == "git_failure" and index == 2:
                raise boundary.GitError("Synthetic reproof failure")
            return git(command, cwd, env=env)

        boundary._run = run
        visibility = boundary._companion_visibility

        def during_proof(*args, **kwargs):
            result = visibility(*args, **kwargs)
            change(index)
            return result

        boundary._companion_visibility = during_proof
        if kind == "no_receipt":
            return SimpleNamespace(
                _companion_git_context=boundary._companion_git_context,
                _companion_visibility=boundary._companion_visibility,
                GitError=boundary.GitError)
        return boundary

    monkeypatch.setattr(runtime, "_shared_data_boundary", load)
    with pytest.raises(runtime.DataBoundaryError):
        runtime.verify_directory(requested, expected_repo=scene.repository)
    assert len(factories) == expected_proofs
    assert runtime._DIRECTORY_PROOF.get() is None


def test_directory_created_before_verification_keeps_one_fresh_proof(scene):
    requested = scene.data / "already-created"
    requested.mkdir()
    assert runtime.verify_directory(requested, expected_repo=scene.repository) == (
        requested, scene.repository)
    assert len(scene.calls) == RECIPE["standalone_queries"]
    assert runtime._DIRECTORY_PROOF.get() is None


def test_generated_test_source_is_reproducible():
    from tools.make_fixtures import operation_proof_test_source
    assert operation_proof_test_source() == Path(__file__).read_text(encoding="utf-8")
'''


def byte_preservation_inputs():
    """Generate source layouts and inert test bytes for exact restoration checks."""
    source = ("# Synthetic source for mutation checks.\n"
              "def combine(left, right):\n"
              "    return left + right, left == right, True\n")
    lines = source.splitlines()
    layouts = [
        ("lf", source.encode("utf-8"), 3),
        ("crlf", source.replace("\n", "\r\n").encode("utf-8"), 3),
        ("mixed", "".join(line + ("\r\n" if index % 2 else "\n")
                          for index, line in enumerate(lines)).encode("utf-8"), 3),
        ("non-ascii", ('LABEL = "caf\u00e9 \u03bb"\n' + source).encode("utf-8"), 3),
        ("utf8-bom", b"\xef\xbb\xbf" + source.encode("utf-8"), 0),
    ]
    return [
        {"name": name, "source": payload, "mutants": mutants,
         "test": b"def test_synthetic():\n    assert True\n"}
        for name, payload, mutants in layouts
    ]


def byte_preservation_invalid_utf8():
    """Generate bytes that retain the original UTF-8 decoding error contract."""
    return b"# Synthetic invalid UTF-8 source: \xff\n"


def byte_preservation_test_source():
    """Generate the complete byte-restoration regression module."""
    return r'''"""Generated byte-restoration regressions; all source payloads are synthetic."""
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import (
    byte_preservation_inputs, byte_preservation_invalid_utf8, byte_preservation_test_source,
)
from tools.sie.probes import exec_probe
from tools.sie import verifiable


CASES = byte_preservation_inputs()
MUTABLE_CASES = [case for case in CASES if case["mutants"]]


def scene(tmp_path, case):
    source = tmp_path / "module.py"
    source.write_bytes(case["source"])
    (tmp_path / "test_synthetic.py").write_bytes(case["test"])
    return source


def observe_probe(source, case, calls):
    payload = source.read_bytes()
    calls.append(payload)
    if len(calls) == 1:
        assert payload == case["source"]
    else:
        assert payload.startswith(case["source"])
        assert b"raise RuntimeError('SIE_MUTANT')" in payload[len(case["source"]):]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("verdict,killed,reason", [
    (1, True, None), (2, True, None), (0, False, "GREEN"),
    (exec_probe.TIMEOUT_CODE, False, "TIMED OUT"),
    (3, False, "exited 3"), (4, False, "exited 4"), (5, False, "exited 5"),
])
def test_exec_probe_restores_bytes_after_each_verdict(tmp_path, monkeypatch, case, verdict, killed, reason):
    source = scene(tmp_path, case)
    calls = []

    def run(_root):
        observe_probe(source, case, calls)
        return 0 if len(calls) == 1 else verdict

    monkeypatch.setattr(exec_probe, "_run_pytest", run)
    result = exec_probe.run_exec_probe(str(tmp_path))
    assert len(calls) == 2
    assert result["exit_code"] == 0 and result["mutation_killed"] is killed
    if reason is None:
        assert result["unavailable_reason"] is None
    else:
        assert reason in result["unavailable_reason"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_exec_probe_restores_bytes_and_propagates_grader_errors(tmp_path, monkeypatch, case, error_type):
    source = scene(tmp_path, case)
    calls = []
    error = error_type("Synthetic grader interruption")

    def run(_root):
        observe_probe(source, case, calls)
        if len(calls) == 1:
            return 0
        raise error

    monkeypatch.setattr(exec_probe, "_run_pytest", run)
    with pytest.raises(error_type) as raised:
        exec_probe.run_exec_probe(str(tmp_path))
    assert raised.value is error and len(calls) == 2
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_exec_probe_timeout_handler_restores_exact_source(tmp_path, monkeypatch, case):
    source = scene(tmp_path, case)
    calls = []

    def run(command, **kwargs):
        observe_probe(source, case, calls)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(exec_probe.subprocess, "run", run)
    result = exec_probe.run_exec_probe(str(tmp_path))
    assert len(calls) == 2
    assert not result["mutation_killed"] and "TIMED OUT" in result["unavailable_reason"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("verdict", [exec_probe.TIMEOUT_CODE, 1, 5])
def test_exec_probe_baseline_refusal_leaves_bytes_untouched(tmp_path, monkeypatch, case, verdict):
    source = scene(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        return verdict

    monkeypatch.setattr(exec_probe, "_run_pytest", run)
    result = exec_probe.run_exec_probe(str(tmp_path))
    assert calls == [case["source"]]
    assert result["exit_code"] == verdict and not result["mutation_killed"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("outcome", ["killed", "survived", "exception", "timeout"])
def test_mutation_gate_restores_bytes_for_verdicts_and_grader_errors(tmp_path, case, outcome):
    source = scene(tmp_path, case)
    calls = []

    error = (RuntimeError("Synthetic mutant grader failure") if outcome == "exception"
             else subprocess.TimeoutExpired("synthetic-grader", 1) if outcome == "timeout"
             else None)

    def run(_root):
        payload = source.read_bytes()
        calls.append(payload)
        if len(calls) == 1:
            assert payload == case["source"]
            return True
        assert payload != case["source"]
        if error is not None:
            raise error
        return outcome == "survived"

    if error is not None:
        with pytest.raises(type(error)) as raised:
            verifiable.mutation_validity_gate(str(tmp_path), [source.name], run)
        assert raised.value is error and len(calls) == 2
    else:
        result = verifiable.mutation_validity_gate(str(tmp_path), [source.name], run)
        assert len(calls) == 1 + case["mutants"]
        assert result["total"] == case["mutants"]
        killed = 0 if outcome == "survived" else case["mutants"]
        assert result["killed"] == killed and result["kill_ratio"] == killed / case["mutants"]
        assert result["valid"] is (outcome != "survived")
        assert len(result["survivors"]) == case["mutants"] - killed
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
def test_mutation_gate_restores_bytes_before_propagating_baseexception(tmp_path, case):
    source = scene(tmp_path, case)
    calls = []
    error = KeyboardInterrupt("Synthetic mutation interruption")

    def run(_root):
        calls.append(source.read_bytes())
        if len(calls) == 1:
            return True
        raise error

    with pytest.raises(KeyboardInterrupt) as raised:
        verifiable.mutation_validity_gate(str(tmp_path), [source.name], run)
    assert raised.value is error and len(calls) == 2
    assert source.read_bytes() == case["source"]


def test_mutation_gate_preserves_bom_without_changing_parser_behavior(tmp_path):
    case = next(case for case in CASES if case["name"] == "utf8-bom")
    source = scene(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        return True

    result = verifiable.mutation_validity_gate(str(tmp_path), [source.name], run)
    assert calls == [case["source"]]
    assert result == {"valid": False, "killed": 0, "total": 0, "kill_ratio": 0.0, "survivors": []}
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("operation,case", [
    (operation, case) for operation in ("exec", "mutation") for case in CASES
    if operation == "exec" or case["mutants"]
], ids=lambda value: value["name"] if isinstance(value, dict) else value)
def test_partial_mutant_write_failure_restores_bytes(tmp_path, monkeypatch, operation, case):
    import builtins

    source = scene(tmp_path, case)
    real_open = builtins.open
    error = OSError("Synthetic partial mutant write")
    module = exec_probe if operation == "exec" else verifiable
    mutation_mode = "a" if operation == "exec" else "w"
    writes = []

    class PartialWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def write(self, text):
            self.stream.write(text[:max(1, len(text) // 2)])
            self.stream.flush()
            writes.append(source.read_bytes())
            raise error

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

    def open_file(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if Path(path) == source and mode == mutation_mode:
            return PartialWriter(stream)
        return stream

    monkeypatch.setattr(module, "open", open_file, raising=False)
    if operation == "exec":
        monkeypatch.setattr(exec_probe, "_run_pytest", lambda _root: 0)
        invoke = lambda: exec_probe.run_exec_probe(str(tmp_path))
    else:
        invoke = lambda: verifiable.mutation_validity_gate(str(tmp_path), [source.name], lambda _root: True)
    with pytest.raises(OSError) as raised:
        invoke()
    assert raised.value is error and len(writes) == 1 and writes[0] != case["source"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("operation", ["exec", "mutation"])
def test_invalid_utf8_preserves_existing_error_without_writing_source(tmp_path, monkeypatch, operation):
    case = dict(CASES[0], source=byte_preservation_invalid_utf8())
    source = scene(tmp_path, case)
    calls = []

    def baseline(_root):
        calls.append(source.read_bytes())
        return 0 if operation == "exec" else True

    if operation == "exec":
        monkeypatch.setattr(exec_probe, "_run_pytest", baseline)
        invoke = lambda: exec_probe.run_exec_probe(str(tmp_path))
    else:
        invoke = lambda: verifiable.mutation_validity_gate(str(tmp_path), [source.name], baseline)
    with pytest.raises(UnicodeDecodeError):
        invoke()
    assert calls == [case["source"]] and source.read_bytes() == case["source"]


def test_generated_byte_preservation_source_is_reproducible():
    assert byte_preservation_test_source() == Path(__file__).read_text(encoding="utf-8")
'''


def mutation_grader_failure_test_source():
    """Generate the complete grader-failure regression module."""
    return r'''"""Generated mutation-grader regressions; all source payloads are synthetic."""
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import (
    byte_preservation_inputs, mutation_grader_failure_test_source,
)
from tools.sie.verifiable import mutation_validity_gate


CASES = byte_preservation_inputs()
MUTABLE_CASES = [case for case in CASES if case["mutants"]]


def source_file(tmp_path, case):
    source = tmp_path / "module.py"
    source.write_bytes(case["source"])
    return source


def grader_error(kind):
    if kind == "runtime":
        return RuntimeError("Synthetic mutant grader failure")
    return subprocess.TimeoutExpired("synthetic-grader", 1)


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("kind", ["runtime", "timeout"])
@pytest.mark.parametrize("minimum", [0.0, 1.0])
@pytest.mark.parametrize("completed", [(), (False,), (True,)],
                         ids=["first-mutant", "after-kill", "after-survivor"])
def test_mutant_grader_error_propagates_without_acceptance(tmp_path, case, kind, minimum, completed):
    source = source_file(tmp_path, case)
    error = grader_error(kind)
    calls = []

    def run(_root):
        payload = source.read_bytes()
        calls.append(payload)
        if len(calls) == 1:
            assert payload == case["source"]
            return True
        assert payload != case["source"]
        index = len(calls) - 2
        if index < len(completed):
            return completed[index]
        raise error

    with pytest.raises(type(error)) as raised:
        mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=minimum)
    assert raised.value is error
    assert len(calls) == 2 + len(completed)
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("outcome", ["false", "runtime", "timeout"])
def test_baseline_refusal_keeps_existing_invalid_result(tmp_path, case, outcome):
    source = source_file(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        if outcome == "false":
            return False
        raise grader_error(outcome)

    result = mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=0.0)
    assert result == {"valid": False, "killed": 0, "total": 0,
                      "kill_ratio": 0.0, "survivors": []}
    assert calls == [case["source"]]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("phase", ["baseline", "mutant"])
def test_baseexception_identity_and_restoration_are_preserved(tmp_path, case, error_type, phase):
    source = source_file(tmp_path, case)
    error = error_type("Synthetic grader interruption")
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        if phase == "mutant" and len(calls) == 1:
            return True
        raise error

    with pytest.raises(error_type) as raised:
        mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=0.0)
    assert raised.value is error
    assert len(calls) == (1 if phase == "baseline" else 2)
    assert calls[0] == case["source"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("verdict", [False, True])
@pytest.mark.parametrize("minimum", [0.0, 1.0])
def test_returned_boolean_verdicts_keep_existing_counts(tmp_path, case, verdict, minimum):
    source = source_file(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        return True if len(calls) == 1 else verdict

    result = mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=minimum)
    killed = 0 if verdict else case["mutants"]
    ratio = killed / case["mutants"]
    assert result == {
        "valid": ratio >= minimum,
        "killed": killed,
        "total": case["mutants"],
        "kill_ratio": ratio,
        "survivors": [f"{source.name}:mut_{index}" for index in range(case["mutants"])]
                     if verdict else [],
    }
    assert len(calls) == 1 + case["mutants"]
    assert source.read_bytes() == case["source"]


def test_generated_mutation_grader_source_is_reproducible():
    assert mutation_grader_failure_test_source() == Path(__file__).read_text(encoding="utf-8")
'''


def main(argv=None):
    """Preserve legacy stdout samples; --out writes deterministic public fixtures."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write declared fixture basenames to this directory")
    args = parser.parse_args(argv)
    if args.out is not None:
        write_disk_fixtures(args.out)
        return 0
    print(json.dumps({'runtime': runtime_samples(), 'llm': llm_samples(),
                     'artifact_schema': artifact_schema_samples(),
                     'c_evidence': c_evidence_samples(),
                     'numeric_scores': numeric_score_samples(),
                     'caller_contracts': caller_contract_samples(),
                     'business_trees': business_tree_samples(),
                     'repairs': repair_samples()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
