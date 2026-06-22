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


def _has_tests(root: str) -> bool:
    return bool(
        glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True)
        or glob.glob(os.path.join(root, "**", "*_test.py"), recursive=True)
    )


def _run_pytest(root: str) -> int:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(PYTEST, cwd=root, capture_output=True, text=True, env=env, timeout=60)
        return proc.returncode  # 0=pass, 1=fail, 5=no tests collected
    except subprocess.TimeoutExpired:
        return 1  # timeout treated as test failure / signal unavailable


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
    }
    if not out["has_tests"]:
        return out

    out["exit_code"] = _run_pytest(sandbox_root)
    # 基线必须先全绿(0) 才有资格做变异;
    # 退出码 5(无收集)/1(fail) 都不算有效 grader
    if out["exit_code"] != 0:
        return out

    src = _pick_src(sandbox_root)
    if not src:
        return out

    with open(src, "r", encoding="utf-8") as fh:
        original = fh.read()
    try:
        with open(src, "a", encoding="utf-8") as fh:
            fh.write("\nraise RuntimeError('SIE_MUTANT')\n")
        mutant_code = _run_pytest(sandbox_root)
        out["mutation_killed"] = mutant_code != 0  # 注入 bug 须变红
    finally:
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(original)
    return out
