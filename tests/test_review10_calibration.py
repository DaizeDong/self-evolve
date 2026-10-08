"""Actual calibration main with generated observations and inert runtime collaborators."""
import argparse
import ast
import builtins
import copy
import json
import posixpath
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, namespace, names=None):
    path = ROOT / relative
    tree = ast.parse(path.read_bytes(), str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and (names is None or node.name in names)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def fixture():
    namespace = {}
    definitions("tools/make_fixtures.py", namespace, {"review10_calibration_samples"})
    return namespace["review10_calibration_samples"]()


def drive(options=None):
    case = fixture()
    options = options or {}
    saved = []
    class ReportPath:
        def __str__(self):
            return case["out"]
        def write_text(self, text, **kwargs):
            saved.append(json.loads(text))
    runtime = SimpleNamespace(
        private_root=lambda: Path(case["workdir"]),
        runtime_directory=lambda value: value,
        make_directory=lambda value: value,
        _new_scratch_directory=lambda root, prefix: root / prefix,
        private_file_path=lambda path: ReportPath())
    real_import = builtins.__import__
    def importing(name, *args, **kwargs):
        return runtime if name == "tools.sie.runtime_data" else real_import(name, *args, **kwargs)
    namespace = {"__builtins__": dict(vars(builtins), __import__=importing),
                 "argparse": argparse, "json": json,
                 "os": SimpleNamespace(path=posixpath, makedirs=lambda *args, **kwargs: None),
                 "time": SimpleNamespace(time=lambda: 1.0)}
    definitions("tools/sie/calibrate.py", namespace)
    ids = case["ids"]
    post = {"repaired": list(options.get("repairs", ids)), "still_broken": [],
            "oracle_errors": []}
    post["still_broken"] = [key for key in ids if key not in post["repaired"]]
    if options.get("oracle_error"):
        post["oracle_errors"] = [{"id": ids[0], "why": "synthetic error"}]
    if options.get("duplicate"):
        post["repaired"] = [ids[0]] * 4
    def scoring(root, defects):
        return copy.deepcopy(post if root.endswith("/graded") else
                             {"repaired": [], "still_broken": ids, "oracle_errors": []})
    def scoring_root(*args):
        if options.get("downstream_error"):
            raise namespace["CalibrationError"]("synthetic grading unavailable")
        return case["workdir"] + "/graded"
    namespace.update({
        "load_defects": lambda only: [{"id": key} for key in ids],
        "validate": lambda *args: {"clean_suite_rc": 0, "clean_suite_tail": case["suite_tail"],
            "defects": [{"id": key, "usable": True, "why": ""} for key in ids]},
        "seed_copy": lambda *args: None,
        "run_suite": lambda root: (options.get("suite_rc", 0),
             options.get("suite_tail", case["suite_tail"])) if root.endswith("/graded")
             else (0, case["suite_tail"]),
        "score": scoring,
        "run_loop": lambda *args: {"init_rc": 0, "run_rc": options.get("loop_rc", 0),
                                   "run_seconds": 1},
        "read_events": lambda *args: {"present": options.get("events_present", True),
            "rounds_seen": 1, "accepted": 1, "static_rejected": 0, "rejected": 0},
        "attribute_decisions": lambda *args: {"error": "synthetic missing observation"}
            if options.get("attribution_error") else
            {"n_accepted": 1, "versions": [{"vid": "v1", "labels": ["REPAIR"]}], "totals": {}},
        "scoring_root": scoring_root,
        "check_sandbox_baseline": lambda *args: options.get("baseline_count", len(ids)),
    })
    result = namespace["main"](["--target", case["target"], "--workdir", case["workdir"],
                               "--out", case["out"]])
    return result, saved[-1]


class CalibrationVerdictTests(unittest.TestCase):
    def test_completed_main_requires_repairs_suite_and_observation_chain(self):
        for name, options, works in fixture()["cases"]:
            with self.subTest(case=name):
                result, report = drive(options)
                self.assertEqual(report["prereg_threshold"], 4)
                self.assertEqual(report["verdict"], "WORKS" if works else "BROKEN")
                self.assertEqual(result == 0, works)

    def test_downstream_failure_retains_partial_report_and_returns_nonzero(self):
        result, report = drive({"downstream_error": True})
        self.assertNotEqual(result, 0)
        self.assertEqual(report["verdict"], "BROKEN")
        self.assertIn("loop", report)
        self.assertIn("events", report)
        self.assertIn("error", report)


    def test_actual_score_distinguishes_test_failure_from_oracle_execution_error(self):
        case = fixture()
        for rc, bucket in case["oracle_exits"]:
            with self.subTest(rc=rc):
                namespace = {"run_oracle": lambda *args: (rc, "")}
                definitions("tools/sie/calibrate.py", namespace, {"score"})
                result = namespace["score"](case["target"], [{"id": case["ids"][0], "oracle": ""}])
                self.assertEqual(len(result[bucket]), 1)
                self.assertEqual(sum(len(value) for value in result.values()), 1)
