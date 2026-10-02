"""Generated-data controls for frozen factual evidence; external collaborators are inert."""
import ast
import math
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(relative, names, namespace):
    path = ROOT / relative
    tree = ast.parse(path.read_bytes(), str(path))
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                and node.name in names]
    if len(selected) != len(names):
        raise AssertionError("Definition set changed")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def samples():
    namespace = {}
    definitions("tools/make_fixtures.py", {"review10_btier_samples"}, namespace)
    return namespace["review10_btier_samples"]()


def evaluator():
    anchors = {"datetime": datetime, "timezone": timezone, "_REL_TOL": 0.01, "_ABS_TOL": 0.01}
    definitions("tools/sie/anchors.py", {"_within_tol", "verify_anchor", "coverage", "marginal_gain"}, anchors)
    namespace = {"_anchors": SimpleNamespace(**anchors), "math": math}
    names = {"_btier_match_key", "build_btier_scores", "_verify_visible", "_evaluate_btier"}
    definitions("tools/sie/evaluate.py", names, namespace)
    return namespace


class FrozenBTests(unittest.TestCase):
    def test_loss_variants_keep_the_negative_pairs_and_frozen_coverage(self):
        case = samples()
        namespace = evaluator()
        fetch = lambda anchor: case["truth"].get((str(anchor.get("cik")),
                                                 anchor.get("metric"), anchor.get("period")))
        for name in ("proper", "rekeyed", "shortened"):
            with self.subTest(variant=name):
                scored = namespace["build_btier_scores"](case["frozen"], case[name], fetch)
                result = namespace["_evaluate_btier"]({"tier": "B", "round": 1, **scored, "fetcher": fetch})
                self.assertEqual(len(result["b_paired"]), 48)
                self.assertEqual(sum(before for before, after in result["b_paired"]), 32)
                expected_after = 48 if name == "proper" else 16
                self.assertEqual(sum(after for before, after in result["b_paired"]), expected_after)
                self.assertAlmostEqual(result["coverage"], expected_after / 48)
                self.assertEqual({a["anchor_id"] for a in scored["anchors_visible"]},
                                 {a["anchor_id"] for a in case["frozen"]})
                self.assertEqual([len(a["span"]) for a in scored["anchors_visible"]],
                                 [len(a["span"]) for a in case["frozen"]])
                if name == "proper":
                    self.assertGreater(result["visible_anchor_gain"], 0)
                else:
                    self.assertLess(result["visible_anchor_gain"], 0)

    def test_empty_candidate_is_explicitly_scored_as_lost_facts(self):
        case = samples()
        namespace = evaluator()
        fetch = lambda anchor: case["truth"].get((str(anchor.get("cik")),
                                                 anchor.get("metric"), anchor.get("period")))
        scored = namespace["build_btier_scores"](case["frozen"], [], fetch)
        result = namespace["_evaluate_btier"]({"tier": "B", "round": 1, **scored, "fetcher": fetch})
        self.assertEqual(len(result["b_paired"]), 48)
        self.assertEqual(sum(before for before, after in result["b_paired"]), 32)
        self.assertEqual(sum(after for before, after in result["b_paired"]), 0)
        self.assertEqual(result["coverage"], 0)


def acceptance_route(evaluation):
    import builtins
    from urllib.parse import urlparse
    anchors = {"math": math, "urlparse": urlparse}
    definitions("tools/sie/anchors.py", {"_source_cluster_key", "effective_independent_count"}, anchors)
    deception = {"RunState": SimpleNamespace, "_EPS": 0.02, "_ALERT_BAND": 0.15}
    definitions("tools/sie/selfdeception.py", {"index"}, deception)
    modules = SimpleNamespace(anchors=SimpleNamespace(**anchors),
                              selfdeception=SimpleNamespace(**deception),
                              gate_human=SimpleNamespace(enqueue=lambda *args: None))
    real_import = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "numpy" or name.startswith("confseq"):
            raise ImportError("Optional statistics package absent in author control")
        return modules if name == "" else real_import(name, *args, **kwargs)
    namespace = {"RunState": SimpleNamespace, "_PASS": 1.0,
                 "__builtins__": dict(vars(builtins), __import__=importing)}
    definitions("tools/sie/acceptor.py",
                {"_ons_betting_wealth", "_wealth_betting", "_pace_threshold",
                 "_decorrelate_downweight", "decide"}, namespace)
    definitions("tools/sie/statemachine.py", {"resolve_accept"}, namespace)
    state = SimpleNamespace(tier="B", drift_count=0, no_progress=0,
                            forced_review=0, continue_count=0, round=1, run_id="synthetic-run")
    return namespace["resolve_accept"](state, evaluation, {}, run_dir="/synthetic/review")


def artifact_proposal(case, variant):
    import copy
    import json
    import sys
    original = json.dumps({"sections": [{"anchors": case["frozen"]}]})
    proposed = json.dumps({"sections": [{"anchors": case[variant]}]})
    class InertPath:
        def __init__(self, value):
            self.value = value
        def __truediv__(self, relative):
            return InertPath(self.value + "/" + relative)
        def resolve(self):
            return self
        def is_relative_to(self, other):
            return self.value.startswith(other.value + "/")
        def stat(self):
            return SimpleNamespace(st_size=len(original))
        def read_text(self, **kwargs):
            return original
    adapter = SimpleNamespace(
        strip_truth=lambda value: copy.deepcopy(value),
        invoke_agent=lambda prompt: {"ok": True, "result": json.dumps({
            "file_rel": "report.json", "new_content": proposed})},
        parse_object=json.loads)
    namespace = {"copy": copy, "json": json, "math": math, "sys": sys,
                 "Path": InertPath, "_MAX_ARTIFACT_BYTES": 200000,
                 "llm_adapter": adapter, "_find_target_artifact": lambda *args: "report.json",
                 "_extract_findings": lambda value: value}
    definitions("tools/sie/backends/llm.py",
                {"ProposalBatch", "_empty", "_artifact_anchors", "_numeric_anchor",
                 "_valid_numeric_anchor", "generate_artifact"}, namespace)
    proposals = namespace["generate_artifact"]("/synthetic/candidate", [])
    return (namespace["_artifact_anchors"](json.loads(proposals[0]["new_content"]))
            if proposals else None)


class CompleteBRouteTests(unittest.TestCase):
    def test_proposer_scoring_and_actual_acceptor_preserve_negative_facts(self):
        case, namespace = samples(), evaluator()
        fetch = lambda anchor: case["truth"].get((str(anchor.get("cik")),
                                                 anchor.get("metric"), anchor.get("period")))
        for variant in ("proper", "empty", "partial", "rekeyed", "shortened"):
            with self.subTest(variant=variant):
                proposed = artifact_proposal(case, variant)
                scored = namespace["build_btier_scores"](case["frozen"], case[variant], fetch)
                result = namespace["_evaluate_btier"]({"tier": "B", "round": 1, **scored, "fetcher": fetch})
                self.assertEqual(len(result["b_paired"]), 48)
                self.assertEqual(sum(before for before, after in result["b_paired"]), 32)
                outcome = acceptance_route(result)
                if variant == "proper":
                    self.assertIsNotNone(proposed)
                    chained = namespace["build_btier_scores"](case["frozen"], proposed, fetch)
                    chained_result = namespace["_evaluate_btier"](
                        {"tier": "B", "round": 1, **chained, "fetcher": fetch})
                    self.assertEqual(acceptance_route(chained_result)["acceptor_decision"], "ACCEPT")
                    self.assertEqual(outcome["acceptor_decision"], "ACCEPT")
                else:
                    self.assertNotEqual(outcome["acceptor_decision"], "ACCEPT")
                    if variant == "shortened":
                        self.assertIsNotNone(proposed)
                        self.assertAlmostEqual(result["coverage"], 16 / 48)
                    else:
                        self.assertIsNone(proposed)
