"""Whole-loop producer controls with generated data and inert collaborator boundaries."""
import ast
import builtins
import copy
import hashlib
import io
import json
import math
import posixpath
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, names, namespace, source=None):
    path = ROOT / relative
    tree = ast.parse(path.read_bytes() if source is None else source, str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in names]
    if len(nodes) != len(names):
        raise AssertionError("Definition set changed")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def fixture():
    namespace = {}
    definitions("tools/make_fixtures.py", {"review10_btier_samples", "review10_loop_samples"}, namespace)
    return namespace["review10_loop_samples"]()


def measurement():
    anchors = {"datetime": datetime, "timezone": timezone, "_REL_TOL": 0.01, "_ABS_TOL": 0.01}
    definitions("tools/sie/anchors.py", {"_within_tol", "verify_anchor"}, anchors)
    evaluate = {"_anchors": SimpleNamespace(**anchors)}
    definitions("tools/sie/evaluate.py", {"_btier_match_key", "build_btier_scores"}, evaluate)
    return SimpleNamespace(**evaluate)


def loop(*, tier="B", holdout_missing=False, self_mode=False, holdout_mode=None):
    case = fixture()
    seen = {"contexts": [], "patch_roots": [], "grade_roots": [], "snapshots": [],
            "events": [], "baselines": [], "worktrees": [], "archives": []}
    visible = copy.deepcopy(case["frozen"][:16])
    current = copy.deepcopy(case["proper"] + case["holdout"])
    holdout_bytes = json.dumps(case["holdout"], sort_keys=True, separators=(",", ":")).encode()
    profile = {"tier": tier, "anchors_visible": visible, "anchors_holdout_ref": {
        "path": case["holdout_path"], "count": len(case["holdout"]),
        "sha256": hashlib.sha256(holdout_bytes).hexdigest()}}
    if holdout_mode == "digest":
        profile["anchors_holdout_ref"]["sha256"] = "0" * 64
    elif holdout_mode == "count":
        profile["anchors_holdout_ref"]["count"] = True
    elif holdout_mode == "unpinned":
        del profile["anchors_holdout_ref"]["sha256"]
    elif holdout_mode == "overlap":
        holdout_bytes = json.dumps(visible[:1], sort_keys=True, separators=(",", ":")).encode()
        profile["anchors_holdout_ref"]["sha256"] = hashlib.sha256(holdout_bytes).hexdigest()
    state = SimpleNamespace(phase="INIT", tier=tier, round=0, parent_vid=None,
                            no_progress=0, continue_count=0, forced_review=0, drift_count=0)
    def step(root, event):
        seen["events"].append(event)
        for name in ("phase", "tier", "round", "parent_vid"):
            if name in event:
                setattr(state, name, event[name])
        return state
    def open_virtual(path, *args, **kwargs):
        if path == case["holdout_path"] and not holdout_missing:
            return io.StringIO(holdout_bytes.decode())
        raise FileNotFoundError("Synthetic missing input")
    def extract(path):
        return copy.deepcopy(current)
    def evaluate(context, *args, **kwargs):
        if isinstance(context, dict):
            seen["contexts"].append(copy.deepcopy(context))
            return {"tier": "B", "b_paired": [(0, 1)], "coverage": 1.0}
        seen["grade_roots"].append(context)
        return {"result": {"dimensions": case["tasks"]}, "paired": [(1, 1), (1, 1)]}
    def patch(root, *args, **kwargs):
        seen["patch_roots"].append(root)
        return {"status": "APPLIED"}
    def grade(task, root, **kwargs):
        seen["grade_roots"].append(root)
        return {"dimensions": copy.deepcopy(case["tasks"])}
    def worktree(*args):
        seen["worktrees"].append(args)
        return case["candidate"]
    def snapshot(root, destination):
        seen["snapshots"].append(root)
    archive = SimpleNamespace(
        lineage=lambda root: [],
        next_version_id=lambda root: "v%d" % (len(seen["archives"]) + 1),
        snapshot_version=lambda arch, vid, root: seen["snapshots"].append(root),
        add_version=lambda *args: seen["archives"].append(args))
    evaluator = measurement()
    evaluator.pair_parent_dimensions = lambda before, after: [(1, 1), (1, 1)]
    modules = {
        "tools.sie": SimpleNamespace(evaluate=evaluator,
                                    anchors=SimpleNamespace(extract_anchors=extract)),
        "tools.sie.evaluate": evaluator,
        "tools.sie.probes": SimpleNamespace(fact_probe=SimpleNamespace(
            _find_artifacts=lambda root: [root + "/report.json"])),
    }
    real_import = builtins.__import__
    def importing(name, *args, **kwargs):
        return modules[name] if name in modules else real_import(name, *args, **kwargs)
    def baseline(*args, **kwargs):
        seen["baselines"].append(args)
        return {"dimensions": copy.deepcopy(case["tasks"])}
    namespace = {
        "__builtins__": dict(vars(builtins), __import__=importing, open=open_virtual),
        "json": json, "os": SimpleNamespace(path=SimpleNamespace(
            join=posixpath.join, exists=lambda path: path.endswith("target.json") or
            (path == case["holdout_path"] and not holdout_missing),
            realpath=posixpath.abspath, normcase=lambda path: path)),
        "runtime_data": SimpleNamespace(make_directory=lambda path: path),
        "_run_dir": lambda *args: case["run_dir"], "make_worktree": worktree,
        "_step": step, "load_target": lambda root: copy.deepcopy(profile),
        "run_profile": lambda *args: copy.deepcopy(profile), "freeze_target": lambda *args: None,
        "business_tree": SimpleNamespace(snapshot=snapshot, manifest=lambda path: {},
                                        selected_snapshot=lambda path: nullcontext()),
        "archive": archive, "select_parent": lambda root, st: "base" if st.round == 0 else "v1",
        "reflect": lambda *args, **kwargs: [{}], "check": lambda *args: True,
        "propose": lambda *args, **kwargs: [case["proposal"]], "apply_patch": patch,
        "_record_model_stage": lambda *args: None, "evaluate": evaluate,
        "resolve_accept": lambda *args, **kwargs: {"next_state": "8"},
        "_round_record": lambda *args, **kwargs: {}, "_parent_baseline": baseline,
        "_usable_baseline": lambda value: value, "_discard_rejected_changes": lambda *args: None,
        "_pause_for_baseline": lambda *args: (state, "baseline_unavailable"),
        "_restore_failed": lambda *args: state, "circuit_check": lambda *args: None,
        "decide": lambda *args: {"decision": "ACCEPT"},
        "apply_acceptor_outcome": lambda *args: "ARCHIVE",
    }
    source = globals().get("BEFORE_LOOP_SOURCE")
    names = {"run_loop", "BaselineUnavailable"}
    if source is None:
        names.add("_btier_round_context")
    definitions("tools/sie/statemachine.py", names, namespace, source)
    supervisor = SimpleNamespace(grade=grade, decide=lambda *args: {"decision": "ACCEPT"},
        assert_candidate_intact=lambda root: None) if self_mode else None
    def fetch(anchor):
        if holdout_mode == "unobserved" and anchor.get("cik") == case["holdout"][0]["cik"]:
            return None
        return case["truth"].get((str(anchor.get("cik")), anchor.get("metric"), anchor.get("period")))
    result = namespace["run_loop"](
        case["target"], case["base_ref"], case["run_id"], max_rounds=5, fetcher=fetch,
        supervisor=supervisor, candidate_worktree=case["self_candidate"] if self_mode else None)
    return result, seen, case


class LoopProducerTests(unittest.TestCase):
    def test_sampled_holdout_is_measured_in_correctness_units(self):
        result, seen, case = loop()
        sampled = seen["contexts"][-1]
        self.assertEqual(sampled["round"], 5)
        self.assertEqual(sampled["holdout_base"], 1.0)
        self.assertEqual(sampled["holdout_with"], 1.0)
        self.assertEqual(sampled["holdout_with"] - sampled["holdout_base"], 0.0)

    def test_missing_scheduled_holdout_cannot_accept_that_round(self):
        result, seen, case = loop(holdout_missing=True)
        self.assertEqual(len(result["accepted_versions"]), 4)
        self.assertEqual(result.get("halt_reason"), "baseline_unavailable")
        self.assertEqual(len(seen["contexts"]), 4)

    def test_parent_selection_never_expands_frozen_visible_identities(self):
        result, seen, case = loop()
        expected = {anchor["anchor_id"] for anchor in case["frozen"][:16]}
        self.assertEqual(len(seen["contexts"]), 5)
        for context in seen["contexts"]:
            self.assertEqual({anchor["anchor_id"] for anchor in context["anchors_visible"]}, expected)

    def test_composite_tier_refuses_instead_of_skipping_a(self):
        with self.assertRaisesRegex(ValueError, "A.B"):
            loop(tier="A+B")

    def test_selfboot_patches_grades_and_archives_one_candidate(self):
        result, seen, case = loop(tier="A", self_mode=True)
        self.assertEqual(seen["worktrees"], [])
        self.assertEqual(set(seen["patch_roots"]), {case["self_candidate"]})
        self.assertEqual(set(seen["grade_roots"]), {case["self_candidate"]})
        self.assertEqual(set(seen["snapshots"]), {case["self_candidate"]})


    def test_invalid_or_unobserved_scheduled_holdout_cannot_accept_that_round(self):
        for mode in ("digest", "count", "unpinned", "overlap", "unobserved"):
            with self.subTest(mode=mode):
                result, seen, case = loop(holdout_mode=mode)
                self.assertEqual(len(result["accepted_versions"]), 4)
                self.assertEqual(result.get("halt_reason"), "baseline_unavailable")
                self.assertEqual(len(seen["contexts"]), 4)
