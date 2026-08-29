"""exec_probe.py — exec 信号探测 + 变异测试二次校验.

run_exec_probe(sandbox_root) -> {
    "has_tests": bool,
    "exit_code": int | None,
    "mutation_killed": bool,
}

变异注入策略：往被测源文件尾部追加 `raise RuntimeError('SIE_MUTANT')`，
重跑测试，期望退出码非 0（被杀死）。若注入 bug 后测试仍全绿 → grader 无效。
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

PYTEST = [sys.executable, "-m", "pytest", "-q", "--no-header"]

# How long the probe waits for a target's suite. Was a hardcoded 60s, which is shorter than a real
# repo's suite: measured 2026-08-28 on a target with 1121 passing tests, a warm run took 58.6s and a
# cold sandbox worktree (no __pycache__) is slower still, so the probe timed out, and the timeout was
# returned as exit code 1. That collapsed "the tests FAILED" into "we ran out of time to find out",
# and since tier A requires exit_code == 0, a target with a large healthy suite was demoted to the
# weakest signal tier with `verifiability_score: 0.0`. The strongest evidence a target had was
# discarded by a stopwatch, silently. Override with SIE_EXEC_PROBE_TIMEOUT.
_DEFAULT_TIMEOUT_S = 600

# Distinct from any pytest exit code (pytest uses 0..5), so a timeout can never be mistaken for a
# verdict about the tests themselves.
TIMEOUT_CODE = -1


def _timeout_s() -> float:
    raw = os.environ.get("SIE_EXEC_PROBE_TIMEOUT", "").strip()
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return float(_DEFAULT_TIMEOUT_S)


def _has_tests(root: str) -> bool:
    return bool(
        glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True)
        or glob.glob(os.path.join(root, "**", "*_test.py"), recursive=True)
    )


def _run_pytest(root: str) -> int:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(PYTEST, cwd=root, capture_output=True, text=True, env=env,
                              timeout=_timeout_s())
        return proc.returncode  # 0=pass, 1=fail, 5=no tests collected
    except subprocess.TimeoutExpired:
        # NOT 1. A timeout is the absence of a verdict, not a failing verdict, and returning 1 here
        # made an unmeasured target indistinguishable from a broken one.
        return TIMEOUT_CODE


def _pick_src(root: str) -> str | None:
    # Exclude test files, conftest, __init__, setup, etc. + sort for determinism
    excludes = {"__init__.py", "setup.py", "conftest.py"}
    candidates = sorted([
        p for p in glob.glob(os.path.join(root, "**", "*.py"), recursive=True)
        if not (os.path.basename(p).startswith("test_")
                or os.path.basename(p).endswith("_test.py")
                or os.path.basename(p) in excludes)
    ])
    return candidates[0] if candidates else None


def run_exec_probe(sandbox_root: str) -> dict:
    """Probe exec signal: run tests baseline then inject mutation to verify grader validity."""
    out = {
        "has_tests": _has_tests(sandbox_root),
        "exit_code": None,
        "mutation_killed": False,
        # WHY the strongest signal tier was not taken. Without this the caller sees only a number and
        # cannot tell a broken suite from one that never finished, and both silently mean tier C.
        "unavailable_reason": None,
    }
    if not out["has_tests"]:
        out["unavailable_reason"] = "no test files found"
        return out

    out["exit_code"] = _run_pytest(sandbox_root)
    # 基线必须先全绿(0) 才有资格做变异;
    # 退出码 5(无收集)/1(fail) 都不算有效 grader
    if out["exit_code"] != 0:
        out["unavailable_reason"] = (
            "baseline suite TIMED OUT after %gs, so nothing is known about it; raise "
            "SIE_EXEC_PROBE_TIMEOUT" % _timeout_s()
            if out["exit_code"] == TIMEOUT_CODE else
            "baseline suite exited %s (5 = collected nothing, other = failing)" % out["exit_code"])
        return out

    src = _pick_src(sandbox_root)
    if not src:
        out["unavailable_reason"] = "no mutable source file to inject a mutant into"
        return out

    with open(src, "r", encoding="utf-8") as fh:
        original = fh.read()
    try:
        with open(src, "a", encoding="utf-8") as fh:
            fh.write("\nraise RuntimeError('SIE_MUTANT')\n")
        mutant_code = _run_pytest(sandbox_root)
        # 注入 bug 须变红。A TIMEOUT is not a kill: `mutant_code != 0` alone would have counted a
        # probe that ran out of time as proof that the suite catches bugs, which is a gate passing
        # because it did not finish checking. The mutant must be observed to fail.
        out["mutation_killed"] = mutant_code not in (0, TIMEOUT_CODE)
        if mutant_code == TIMEOUT_CODE:
            out["unavailable_reason"] = (
                "mutation check TIMED OUT after %gs, so the suite was never shown to catch an "
                "injected bug; raise SIE_EXEC_PROBE_TIMEOUT" % _timeout_s())
        elif mutant_code == 0:
            out["unavailable_reason"] = (
                "the suite stayed GREEN with a mutant injected, so it cannot adjudicate changes")
    finally:
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(original)
    return out
