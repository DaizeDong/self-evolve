"""Archive and frozen-grader controls with generated inputs and in-memory storage."""
import ast
import builtins
import copy
import io
import json
import math
import posixpath
import statistics
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, required, namespace, optional=()):
    source = globals().get("BEFORE_SOURCES", {}).get(relative)
    path = ROOT / relative
    tree = ast.parse(source if source is not None else path.read_bytes(), str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in required | set(optional)]
    if not required.issubset({node.name for node in nodes}):
        raise AssertionError("Required definition set changed")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def fixture():
    namespace = {}
    definitions("tools/make_fixtures.py", {"review10_btier_samples", "review10_loop_samples", "review10_archive_samples"}, namespace)
    return namespace["review10_archive_samples"]()


def archived():
    store = {}
    def read(path, *args, **kwargs):
        return io.StringIO(json.dumps(store[path]))
    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(join=posixpath.join, exists=lambda path: path in store)),
        "json": json, "math": math, "statistics": statistics, "open": read,
        "LINEAGE": "lineage.json", "_HARD_DIMS": ("A", "anchor"), "_SOFT_DIMS": ("judge",),
        "runtime_data": SimpleNamespace(validate_run_id=lambda value: value,
            private_file_path=lambda path: path, make_directory=lambda path: path,
            write_json=lambda path, value: store.update({path: copy.deepcopy(value)})),
    }
    definitions("tools/sie/archive.py",
                {"add_version", "lineage", "_load_versions", "_dominates", "pareto_front", "selectable_parents"},
                namespace, optional={"_score_record", "_version_record"})
    return namespace, store


class ArchiveGradeTests(unittest.TestCase):
    def test_two_loop_shaped_acceptances_reach_status_pareto(self):
        case = fixture()
        namespace, store = archived()
        before = copy.deepcopy(case["tasks"])
        before[0]["score"] = 0.0
        namespace["add_version"](case["run_dir"], "v1", before, None)
        namespace["add_version"](case["run_dir"], "v2", case["tasks"], "v1")
        entries = namespace["lineage"](case["run_dir"] + "/archive")
        self.assertIsInstance(entries[0]["scores"], dict)
        self.assertEqual(entries[0]["task_dimensions"], before)
        self.assertEqual(entries[1]["task_dimensions"], case["tasks"])
        self.assertEqual(entries[0]["scores"]["A"], 0.5)
        self.assertEqual(entries[1]["scores"]["A"], 1.0)
        self.assertEqual(namespace["pareto_front"](case["run_dir"] + "/archive"), ["v2"])
        self.assertEqual(namespace["selectable_parents"](case["run_dir"] + "/archive"), ["v2"])

    def test_bad_archive_scores_refuse_at_writer_and_reader(self):
        case = fixture()
        invalid = case["invalid_archive_scores"]
        for scores in invalid:
            with self.subTest(shape=type(scores).__name__):
                namespace, store = archived()
                with self.assertRaises(ValueError):
                    namespace["add_version"](case["run_dir"], "v1", scores, None)
                self.assertEqual(store, {})
                store[case["run_dir"] + "/archive/lineage.json"] = [{"vid": "v1", "scores": scores}]
                with self.assertRaises(ValueError):
                    namespace["lineage"](case["run_dir"] + "/archive")

    def test_frozen_grader_preserves_passed_and_removed_task_identities(self):
        case = fixture()
        output = {"stdout": "\n".join(task["name"] + " PASSED" for task in case["tasks"])}
        process = SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=output["stdout"], stderr=""))
        grader_env = lambda root: ({}, "/synthetic/site", "/synthetic/jail")
        real_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == "shutil":
                return SimpleNamespace(rmtree=lambda *args, **kwargs: None)
            if name == "tools.sie.verifiable":
                return SimpleNamespace(_grader_env=grader_env)
            return real_import(name, *args, **kwargs)
        base_namespace = {"__builtins__": dict(vars(builtins), __import__=importing),
                          "subprocess": process, "sys": SimpleNamespace(executable="synthetic-python"),
                          "native_cwd": lambda path: path, "_grader_env": grader_env}
        normal = definitions("tools/sie/evaluate.py", {"_grade_pytest_per_task", "_parse_per_test",
                                                       "pair_parent_dimensions"}, dict(base_namespace))
        frozen = definitions("tools/sie/verifiable.py", {"grade_pytest"}, dict(base_namespace),
                             optional={"_parse_task_results"})
        supervisor_module = definitions("tools/sie/supervisor.py", {"Supervisor"}, {})
        supervisor = object.__new__(supervisor_module["Supervisor"])
        supervisor._verifiable = SimpleNamespace(**frozen)
        before = normal["_grade_pytest_per_task"](case["target"])
        current = supervisor.grade({}, case["self_candidate"], self_mode=True)
        self.assertEqual(normal["pair_parent_dimensions"](before["dimensions"], current["dimensions"]),
                         [(1.0, 1.0), (1.0, 1.0)])
        output["stdout"] = case["tasks"][0]["name"] + " PASSED"
        current = supervisor.grade({}, case["self_candidate"], self_mode=True)
        self.assertEqual(normal["pair_parent_dimensions"](before["dimensions"], current["dimensions"]),
                         [(1.0, 1.0), (1.0, 0.0)])
