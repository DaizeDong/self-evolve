"""Parse-only admission controls for aliases, keywords and pathlib boundaries."""
import ast
import posixpath
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def scanner():
    path = ROOT / "tools/sie/patch.py"
    tree = ast.parse(path.read_bytes(), str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef))]
    namespace = {"ast": ast, "os": SimpleNamespace(path=SimpleNamespace(
        realpath=posixpath.abspath, isabs=posixpath.isabs, dirname=posixpath.dirname,
        join=posixpath.join, commonpath=posixpath.commonpath, relpath=posixpath.relpath))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    namespace["_first_party_modules"] = lambda *args: set()
    return namespace


def samples():
    path = ROOT / "tools/make_fixtures.py"
    tree = ast.parse(path.read_bytes(), str(path))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "review10_patch_samples")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["review10_patch_samples"]()


class PatchAdmissionTests(unittest.TestCase):
    def test_combined_admission_handles_aliases_and_equivalent_path_forms(self):
        namespace, case = scanner(), samples()
        for name, source, admitted in case["cases"]:
            with self.subTest(case=name):
                imported, reason = namespace["import_gate"](
                    source, allow=case["allowed"], sandbox_root=case["sandbox"], file_rel="module.py")
                violations = namespace["scan_ast_dangerous"](
                    source, allow_imports=case["allowed"], sandbox_root=case["sandbox"],
                    target_path=case["target"])
                self.assertEqual(imported and not violations, admitted)

    def test_sandbox_only_keyword_path_check_does_not_need_target_filename(self):
        namespace, case = scanner(), samples()
        source = next(source for name, source, allowed in case["cases"] if name == "keyword-open")
        self.assertTrue(namespace["scan_ast_dangerous"](source, sandbox_root=case["sandbox"]))
