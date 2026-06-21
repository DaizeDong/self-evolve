"""profile.py — A/B/C 三档可叠加 tier 判定 + target.json 冻结（铁律4）.

run_profile(target, base_ref) -> dict  # A/B/C 可叠加
freeze_target(run_dir, prof) -> None   # 原子写 target.json
load_target(run_dir) -> dict           # resume 读 (不重跑)

A 档判定（三条件 AND）:
  1. has_tests         — 目标仓库下存在测试文件
  2. exit_code == 0    — 基线测试全绿
  3. mutation_killed   — 注入已知 bug 后测试变红（grader 有效）

B 档判定（fact 锚数量 >= anchor_set_min=24）:
  - 扫产物 JSON 提取结构化锚（claim/span/source_url 三件套）
  - visible 锚进 target.json 供评测计分
  - holdout 锚真值物理隔离落 _holdout/holdout.json（铁律5: proposer 不读 holdout）
  - target.json 只存 anchors_holdout_ref（路径指针 + 计数，不存真值）

C 档: A/B 均不满足。

A/B 可叠加: 如 "A+B", "A", "B", "C"。tier 只首次 PROFILE 冻结（铁律4）。
"""
from __future__ import annotations

import json
import os

TARGET_FILE = "target.json"

_DEFAULT_HOLDOUT_FRAC = 0.3


def _exec_signal(target: str, base_ref: str) -> dict | None:
    """Run exec probe sandbox and return exec_res dict, or None on failure.

    Extracted as a named function so tests can monkeypatch it cleanly.
    Returns the exec_probe result dict if the target is a valid git repo,
    None otherwise (graceful degradation — not all targets are repos).
    """
    try:
        from tools.sie.sandbox import make_worktree
        from tools.sie.probes.exec_probe import run_exec_probe

        sandbox_root = make_worktree(target, base_ref, "profile_probe")
        return run_exec_probe(sandbox_root)
    except Exception:
        return None


def run_profile(target: str, base_ref: str, run_dir: str | None = None) -> dict:
    """Create profile dict with A/B/C tier (可叠加), visible/holdout anchor split.

    A 档: exec probe passes (has_tests + exit_code==0 + mutation_killed).
    B 档: fact anchors >= _ANCHOR_SET_MIN (from fact_probe).
    C 档: neither A nor B.
    Tiers are additive: "A+B", "A", "B", "C".

    Visible anchors are stored in target.json for scoring.
    Holdout anchors (truth values) are physically isolated to
    <holdout_dir>/_holdout/holdout.json — proposer must not read this (铁律5).
    target.json stores only anchors_holdout_ref (path pointer + count).

    If run_dir is provided, automatically freeze the profile to target.json (铁律4).

    Args:
        target: Path to target repo or research artifact directory.
        base_ref: Git base reference for exec probe.
        run_dir: Optional run directory; if given, auto-freezes target.json (铁律4).

    Returns:
        Profile dict with: tier, verifiability_score, anchors_visible,
        anchors_holdout_ref, probe_evidence, probes, base_ref.
    """
    from .probes import fact_probe as _fact_probe
    from . import anchors as _anchors

    tiers: set[str] = set()

    # --- A 维: exec 探针 ---
    exec_res = _exec_signal(target, base_ref)
    if exec_res is not None:
        verifiable = (
            exec_res.get("has_tests")
            and exec_res.get("exit_code") == 0
            and exec_res.get("mutation_killed")
        )
        if verifiable:
            tiers.add("A")
    else:
        exec_res = {}  # no exec signal — treat as empty

    # --- B 维: fact 探针 + visible/holdout 拆分 (铁律5) ---
    fp = _fact_probe.probe(target, base_ref)
    anchors_visible: list[dict] = []
    holdout_ref: dict = {"path": "", "count": 0, "ref": "isolated"}

    if fp["tier_signal"] == "B":
        tiers.add("B")

        # Collect all anchors from artifacts
        all_anchors: list[dict] = []
        for path in _fact_probe._find_artifacts(target):
            try:
                all_anchors.extend(_anchors.extract_anchors(path))
            except Exception:
                pass

        # Deterministic split: seed from run_dir basename or base_ref
        seed = (os.path.basename(run_dir) if run_dir else "") or base_ref
        frac = _DEFAULT_HOLDOUT_FRAC
        visible, holdout = _anchors.split_visible_holdout(all_anchors, frac, seed=seed)
        anchors_visible = visible

        # 铁律5: holdout 真值物理隔离 — 写独立目录, target.json 只存指针
        # holdout_dir: inside run_dir if provided, else sibling _run/_holdout of target
        if run_dir is not None:
            holdout_dir = os.path.join(run_dir, "_holdout")
        else:
            holdout_dir = os.path.join(target, "_run", "_holdout")
        os.makedirs(holdout_dir, exist_ok=True)
        holdout_path = os.path.join(holdout_dir, "holdout.json")
        with open(holdout_path, "w", encoding="utf-8") as fh:
            json.dump(holdout, fh, ensure_ascii=False, indent=2)

        holdout_ref = {
            "path": holdout_path,
            "count": len(holdout),
            "ref": "isolated",
        }

    # 铁律: holdout 真值绝不进 prof (只有 ref 指针)
    # C 档: neither A nor B
    tier_str = "+".join(sorted(tiers)) if tiers else "C"

    verifiability_score = 1.0 if "A" in tiers else 0.0

    prof: dict = {
        "tier": tier_str,
        "verifiability_score": verifiability_score,
        "anchors_visible": anchors_visible,
        "anchors_holdout_ref": holdout_ref,  # pointer only — no holdout truth values
        "probe_evidence": {
            "fact": fp["evidence"],
            "anchor_count": fp["anchor_count"],
        },
        "probes": {"exec": exec_res},
        "base_ref": base_ref,
        # Legacy fields kept for backward compat with existing tests
        "visible": [],
        "holdout": [],
    }

    # 铁律4: if run_dir provided, auto-freeze (首次 PROFILE 后不重跑)
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
