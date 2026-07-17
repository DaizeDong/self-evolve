"""
tests/test_mutation_gate.py — TDD tests for inject_mutants + mutation_validity_gate.

Covers:
  - inject_mutants produces variants (arithmetic mutants)
  - inject_mutants handles syntax errors (returns empty)
  - Real test kills all mutants → valid=True
  - Fake (watering) test lets mutants survive → valid=False
  - File is restored after gate runs (even for survivors)
  - Various mutation node types: arithmetic, comparison, bool constants
"""
import os
import textwrap

import pytest

from tools.sie.verifiable import inject_mutants, mutation_validity_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(wt: str, rel: str, content: str) -> str:
    """Write dedented content into wt/rel, creating dirs as needed. Returns rel."""
    p = os.path.join(wt, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    return rel


def _read(wt: str, rel: str) -> str:
    with open(os.path.join(wt, rel), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# inject_mutants, unit tests
# ---------------------------------------------------------------------------

def test_inject_mutants_produces_variants():
    src = "def f(a, b):\n    return a + b\n"
    muts = inject_mutants(src)
    assert muts, "should produce at least one mutant for '+'"
    assert all(m_src != src for _, m_src in muts), "every mutant must differ from source"


def test_inject_mutants_arithmetic_sub():
    src = "def f(a, b):\n    return a - b\n"
    muts = inject_mutants(src)
    assert muts, "should produce at least one mutant for '-'"
    ids = [mid for mid, _ in muts]
    srcs = [ms for _, ms in muts]
    # The Sub should be flipped to Add
    assert any("+" in ms for ms in srcs)


def test_inject_mutants_comparison_eq():
    src = "def f(a, b):\n    return a == b\n"
    muts = inject_mutants(src)
    assert muts, "should mutate '=='"
    # Flipped should contain !=
    assert any("!=" in ms for _, ms in muts)


def test_inject_mutants_comparison_lt_gte():
    src = "def f(a, b):\n    return a < b\n"
    muts = inject_mutants(src)
    assert muts, "should mutate '<'"


def test_inject_mutants_bool_constant():
    src = "def f():\n    return True\n"
    muts = inject_mutants(src)
    assert muts, "should mutate 'True'"
    assert any("False" in ms for _, ms in muts)


def test_inject_mutants_syntax_error_returns_empty():
    bad_src = "def f(\n    broken syntax (((\n"
    muts = inject_mutants(bad_src)
    assert muts == [], "syntax error should return empty list"


def test_inject_mutants_unique_ids():
    # Multiple mutation sites → unique IDs
    src = "def f(a, b, c):\n    return (a + b) + c\n"
    muts = inject_mutants(src)
    ids = [mid for mid, _ in muts]
    assert len(ids) == len(set(ids)), "mutant IDs must be unique"


# ---------------------------------------------------------------------------
# mutation_validity_gate, integration tests with fake run_one
# ---------------------------------------------------------------------------

def test_real_test_kills_all_mutants(tmp_path):
    """A genuine test suite (checks exact result) kills every arithmetic mutant."""
    wt = str(tmp_path)
    src_rel = _write(wt, "pkg/calc.py", """
        def add(a, b):
            return a + b
    """)

    def run_one(worktree):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "calc_under_test", os.path.join(worktree, src_rel)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.add(2, 3) == 5

    res = mutation_validity_gate(wt, [src_rel], run_one)
    assert res["valid"] is True
    assert res["kill_ratio"] == 1.0
    assert res["survivors"] == []
    assert res["killed"] == res["total"]
    assert res["total"] > 0


def test_fake_test_lets_mutant_survive(tmp_path):
    """A watering test (always True) lets mutants survive → gate flags invalid."""
    wt = str(tmp_path)
    src_rel = _write(wt, "pkg/calc.py", """
        def add(a, b):
            return a + b
    """)

    def run_one(worktree):  # never fails = watering grader
        return True

    res = mutation_validity_gate(wt, [src_rel], run_one)
    assert res["valid"] is False
    assert res["survivors"], "watering grader must leave survivors"
    assert res["kill_ratio"] < 1.0


def test_file_restored_after_gate(tmp_path):
    """Gate must restore source files to original content after running."""
    wt = str(tmp_path)
    original_content = textwrap.dedent("""
        def add(a, b):
            return a + b
    """)
    src_rel = _write(wt, "pkg/calc.py", original_content)

    def run_one(worktree):
        return True  # watering, ensures some mutants survive, exercises restore path

    mutation_validity_gate(wt, [src_rel], run_one)

    restored = _read(wt, src_rel)
    assert restored == original_content, "source file must be restored to original after gate"


def test_file_restored_even_after_exception(tmp_path):
    """File must be restored even if run_one raises an exception."""
    wt = str(tmp_path)
    original_content = textwrap.dedent("""
        def add(a, b):
            return a + b
    """)
    src_rel = _write(wt, "pkg/calc.py", original_content)

    call_count = [0]

    def run_one(worktree):
        call_count[0] += 1
        if call_count[0] > 1:
            raise RuntimeError("simulated grader crash")
        return True  # baseline passes

    # Gate should not propagate the exception and file should be restored
    try:
        mutation_validity_gate(wt, [src_rel], run_one)
    except Exception:
        pass

    restored = _read(wt, src_rel)
    assert restored == original_content, "source must be restored even after run_one exception"


def test_gate_baseline_false_marks_invalid(tmp_path):
    """If baseline run_one returns False, gate should mark as invalid (baseline not green)."""
    wt = str(tmp_path)
    src_rel = _write(wt, "pkg/calc.py", """
        def add(a, b):
            return a + b
    """)

    def run_one(worktree):
        return False  # baseline already red

    res = mutation_validity_gate(wt, [src_rel], run_one)
    assert res["valid"] is False


def test_gate_partial_kill_ratio(tmp_path):
    """With min_kill_ratio=0.5, partial kills can still pass the gate."""
    wt = str(tmp_path)
    # Source with two mutation sites: + and comparison
    src_rel = _write(wt, "pkg/calc.py", """
        def f(a, b):
            return a + b
    """)

    call_count = [0]

    def run_one(worktree):
        # Baseline call: True; subsequent mutations: alternate kill/survive
        call_count[0] += 1
        if call_count[0] == 1:
            return True  # baseline
        # Kill odd mutations, survive even ones
        return call_count[0] % 2 == 0  # True=survive(green), False=killed(red)

    res = mutation_validity_gate(wt, [src_rel], run_one, min_kill_ratio=0.0)
    # With min_kill_ratio=0.0, gate should be valid as long as total > 0
    assert res["valid"] is True
    assert res["total"] > 0


def test_gate_returns_expected_keys(tmp_path):
    """Gate return dict must have all required keys."""
    wt = str(tmp_path)
    src_rel = _write(wt, "pkg/calc.py", """
        def add(a, b):
            return a + b
    """)

    def run_one(worktree):
        return True

    res = mutation_validity_gate(wt, [src_rel], run_one)
    assert set(res.keys()) >= {"valid", "killed", "total", "kill_ratio", "survivors"}
