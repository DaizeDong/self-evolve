"""M1a: evaluate.py — 只走 verifiable(A 档)。B/C 档 evaluate 在 M2/M3 接入。

Public API:
  evaluate(sandbox_root, tier, base_result=None) -> dict
    Returns {"result": <A-grade contract>, "paired": [(before, after), ...], "coverage": float}
    paired 给 acceptor: before=parent grade score, after=current sandbox grade score。
    per-task paired: 每个 pytest test item 产一对 (before, after)，支持 e-process 统计显著性。
    缺省 base_result=None 时视为全 fail 基线，before=0.0。
"""
from __future__ import annotations
from tools.sie.verifiable import grade_pytest, minimal_env

import os
import subprocess
import sys


def _grade_pytest_per_task(sandbox_root: str) -> dict:
    """Run pytest with per-test result capture.

    Returns dict with keys:
      "task_passed": bool (all passed)
      "grader_exit_code": int
      "dimensions": list[dict] — one entry per test item (name, tier, score, weight)
      "anchors": []
      "verifiable_coverage": float
    """
    from tools.sie.verifiable import _grader_env

    env, site_dir, jail_dir = _grader_env(sandbox_root)
    grader_env = env.copy()
    grader_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=no", "--no-header"],
            cwd=sandbox_root,
            capture_output=True,
            text=True,
            env=grader_env,
        )
        code = proc.returncode
        dims = _parse_per_test(proc.stdout)
        if dims:
            # task_passed uses exit_code (consistent with profiler's baseline check).
            # Per-test score can be 0.0 for XFAIL even when exit_code==0 (expected fails).
            return {
                "task_passed": code == 0,
                "grader_exit_code": code,
                "dimensions": dims,
                "anchors": [],
                "verifiable_coverage": 1.0,
            }
        # Fallback: aggregate score
        score = 1.0 if code == 0 else 0.0
        return {
            "task_passed": code == 0,
            "grader_exit_code": code,
            "dimensions": [{"name": "pytest", "tier": "A", "score": score, "weight": 1.0}],
            "anchors": [],
            "verifiable_coverage": 1.0,
        }
    finally:
        import shutil
        for tmpdir in [site_dir, jail_dir]:
            try:
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


def _parse_per_test(stdout: str) -> list[dict]:
    """Parse `pytest -v --tb=no` output to get per-test pass/fail scores.

    Handles:
      PASSED  → score 1.0 (test assertion passed)
      FAILED  → score 0.0 (test assertion failed)
      ERROR   → score 0.0 (collection/fixture error)
      XFAIL   → score 0.0 (expected-fail, test is not yet passing)
      XPASS   → score 1.0 (unexpected-pass: fix made a xfail test pass!)

    Returns list of {"name": str, "tier": "A", "score": float, "weight": float}.
    Returns [] if no parseable per-test lines found.
    """
    import re
    dims = []
    # Match lines like: "path/test.py::test_name PASSED [ 33%]"
    # Also: "test.py::test_name XFAIL (reason) [60%]"
    pattern = re.compile(
        r"^(.+?)\s+(PASSED|FAILED|ERROR|XFAIL|XPASS)\b"
    )
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            name = m.group(1).strip()
            status = m.group(2)
            # XPASS = unexpected pass (fix worked!) = 1.0; XFAIL = still failing = 0.0
            score = 1.0 if status in ("PASSED", "XPASS") else 0.0
            dims.append({"name": name, "tier": "A", "score": score, "weight": 1.0})
    return dims


def evaluate(sandbox_root: str, tier: str,
             base_result: dict | None = None) -> dict:
    """M1a 只走 verifiable(A 档)。B/C 档 evaluate 在 M2/M3 接入。

    Returns per-task pairs for e-process statistical evidence:
    - If per-task grading is available: one (before, after) pair per test item.
    - Falls back to single aggregate pair if per-task parsing fails.

    Args:
        sandbox_root: 沙箱根目录路径。
        tier: 档位，M1a 只用 "A"。
        base_result: parent 版本的 grade 结果(A 档 contract dict)。
                     None 时视为全 fail 基线，before_score=0.0。

    Returns:
        {
          "result": <A-grade contract from grade_pytest>,
          "paired": [(before_score, after_score), ...],  # per-task
          "coverage": float
        }
    """
    after = _grade_pytest_per_task(sandbox_root)
    after_dims = after.get("dimensions", [])

    # Build per-task paired list
    if base_result and base_result.get("dimensions"):
        base_dims = base_result["dimensions"]
        # Align by index (same test order); truncate to shorter list
        n = min(len(after_dims), len(base_dims))
        paired = [
            (float(base_dims[i]["score"]), float(after_dims[i]["score"]))
            for i in range(n)
        ]
        # If lengths differ, append remaining after_dims against 0.0 baseline
        for i in range(n, len(after_dims)):
            paired.append((0.0, float(after_dims[i]["score"])))
    else:
        # 冷启动: before=0.0 for all tasks (全 fail 基线)
        paired = [(0.0, float(d["score"])) for d in after_dims]

    if not paired:
        # Final fallback: single aggregate pair
        after_score = after_dims[0]["score"] if after_dims else 0.0
        before_score = 0.0
        if base_result and base_result.get("dimensions"):
            before_score = base_result["dimensions"][0]["score"]
        paired = [(float(before_score), float(after_score))]

    return {
        "result": after,
        "paired": paired,
        "coverage": after.get("verifiable_coverage", 0.0),
    }
