"""profile.py — A/C 二分 tier 判定 + target.json 冻结（铁律4）.

run_profile(target, base_ref) -> dict  # M1a 只做 A/C 二分
freeze_target(run_dir, prof) -> None   # 原子写 target.json
load_target(run_dir) -> dict           # resume 读 (不重跑)

A 档判定（三条件 AND）:
  1. has_tests         — 目标仓库下存在测试文件
  2. exit_code == 0    — 基线测试全绿
  3. mutation_killed   — 注入已知 bug 后测试变红（grader 有效）

C 档: 以上任一条件不满足（无测试 / 测试失败 / 假 grader）。
B 档（锚）在后续 M2 实现，本文件不涉及。
"""
from __future__ import annotations

import json
import os

from tools.sie.sandbox import make_worktree
from tools.sie.probes.exec_probe import run_exec_probe

TARGET_FILE = "target.json"


def run_profile(target: str, base_ref: str, run_dir: str | None = None) -> dict:
    """Create worktree sandbox, run exec probe, return A/C tier profile dict.

    If run_dir is provided, automatically freeze the profile to target.json (铁律4).
    """
    sandbox_root = make_worktree(target, base_ref, "profile_probe")
    exec_res = run_exec_probe(sandbox_root)
    # A 档判定: 有 test + 基线全绿 + 变异被杀死(grader 有效)
    verifiable = (
        exec_res["has_tests"]
        and exec_res["exit_code"] == 0
        and exec_res["mutation_killed"]
    )
    tier = "A" if verifiable else "C"
    score = 1.0 if verifiable else 0.0
    prof = {
        "tier": tier,
        "verifiability_score": score,
        "visible": [],  # B 档锚 M2 才填
        "holdout": [],
        "probes": {"exec": exec_res},
        "base_ref": base_ref,
    }
    # 铁律4: 如果提供 run_dir，自动冻结 tier（首次 PROFILE 后不重跑）
    if run_dir is not None:
        freeze_target(run_dir, prof)
    return prof


def freeze_target(run_dir: str, prof: dict) -> None:
    """铁律4: tier 在 run 首次 PROFILE 冻结，resume 不重跑。原子写。"""
    os.makedirs(run_dir, exist_ok=True)
    final = os.path.join(run_dir, TARGET_FILE)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(prof, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, final)


def load_target(run_dir: str) -> dict:
    """Load frozen target.json (for resume — no re-profiling)."""
    with open(os.path.join(run_dir, TARGET_FILE), "r", encoding="utf-8") as fh:
        return json.load(fh)
