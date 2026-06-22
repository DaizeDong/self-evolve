"""evaluate.py — A 档 verifiable 编排 (M1a) + B 档 visible/holdout/coverage (M2.12).

Public API:
  evaluate(sandbox_root, tier, base_result=None) -> dict
    A-tier (M1a): Returns {"result": <A-grade contract>, "paired": [...], "coverage": float}
    paired 给 acceptor: before=parent grade score, after=current sandbox grade score。
    per-task paired: 每个 pytest test item 产一对 (before, after)。
    base_result=None 时视为全 fail 基线，before=0.0。

  evaluate(round_ctx: dict) -> dict
    B-tier dispatch (M2.12): first positional arg is a dict with "tier": "B".
    Returns A-tier keys PLUS:
      b_paired: list[tuple[float,float]]  — per-anchor (bg, wg) 零均值化配对喂 acceptor
      visible_anchor_gain: float          — mean(wg - bg) across verified anchors
      holdout_gain: float | None          — None 非抽检轮; 抽检轮=max(0, hw-hb)
      coverage: float                     — 已核验 span / 总 span
      coverage_floor_violation: bool      — coverage<floor (可选 intent 门控；无 intent 时回退原始信号)
"""
from __future__ import annotations
from tools.sie.verifiable import grade_pytest, minimal_env
from . import anchors as _anchors

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


def _verify_visible(anchors: list[dict], ctx: dict) -> list[dict]:
    """核查 visible 锚列表，未核验的通过 anchors.verify_anchor 处理。

    Tests inject a monkeypatch on this module-level function so no network
    calls are made in the test suite. Production path calls verify_anchor
    (which may use edgar; always inject fetcher in tests via ctx["fetcher"]).
    """
    fetcher = ctx.get("fetcher")
    out: list[dict] = []
    for a in anchors:
        if a.get("verified"):
            out.append(a)
        else:
            out.append(_anchors.verify_anchor(a, fetcher=fetcher))
    return out


def _btier_match_key(a: dict) -> tuple:
    """匹配 baseline↔candidate 锚的稳定键: (cik, metric, period)。
    跨 claim/expected 编辑稳定(proposer 改正错值会改 claim → anchor_id 变, 故不能用 id 匹配)。"""
    return (str(a.get("cik", "")), str(a.get("metric", "")), str(a.get("period", "")))


def build_btier_scores(prof_visible_anchors: list[dict],
                       candidate_anchors: list[dict],
                       fetcher=None) -> dict:
    """从 baseline frozen visible 锚 + candidate(改后)锚, 用真 verify 构造 B 档 per-anchor 打分。

    每锚 0/1 = 是否经 verify_anchor 核验通过。按 (cik,metric,period) 匹配 baseline↔candidate
    (保铁律5 frozen visible 集合: 只取 baseline visible 键对应的 candidate 锚)。

    Returns dict:
      anchors_visible: candidate 锚(已 verify, 带 verified 标记) — 喂 _evaluate_btier;
      base_scores:     {candidate_anchor_id: baseline 核验 0/1};
      with_scores:     {candidate_anchor_id: candidate 核验 0/1}.
    候选修正了某错锚 → base=0/with=1 → marginal_gain 计正增益(candidate verified=True)。
    """
    cand_by_key = {_btier_match_key(c): c for c in candidate_anchors}
    anchors_visible: list[dict] = []
    base_scores: dict[str, float] = {}
    with_scores: dict[str, float] = {}
    for a in prof_visible_anchors:
        key = _btier_match_key(a)
        cand = cand_by_key.get(key)
        if cand is None:
            continue  # 候选删了此锚 → 不计(保守, 不奖励删锚)
        bv = _anchors.verify_anchor(a, fetcher=fetcher)
        cv = _anchors.verify_anchor(cand, fetcher=fetcher)
        cv_with_flag = dict(cand, verified=bool(cv.get("verified")))
        aid = cv_with_flag.get("anchor_id") or key  # extract_anchors 已带 anchor_id
        anchors_visible.append(cv_with_flag)
        base_scores[aid] = 1.0 if bv.get("verified") else 0.0
        with_scores[aid] = 1.0 if cv.get("verified") else 0.0
    return {"anchors_visible": anchors_visible,
            "base_scores": base_scores, "with_scores": with_scores}


def _evaluate_btier(ctx: dict) -> dict:
    """B 档评测编排: visible 锚计分 + coverage 门(含 accept 意图可选门控) + holdout 每 K 轮抽检背离.

    Args:
        ctx: B-tier round context dict with keys:
            tier (str): must contain "B"
            round (int): current round number
            K (int): holdout sampling interval (default 5)
            coverage_floor (float): minimum coverage threshold (default 0.5)
            anchors_visible (list[dict]): visible anchor set
            base_scores (dict[str, float]): anchor_id -> score without proposal
            with_scores (dict[str, float]): anchor_id -> score with proposal
            holdout_base (float, optional): holdout mean score without proposal
            holdout_with (float, optional): holdout mean score with proposal
            intended_accept (bool, optional): if provided, gates coverage_floor_violation
                on both low coverage AND acceptance intent (spec gating);
                if None, falls back to raw signal (coverage < floor)
            fetcher (callable, optional): injected fetcher for verify_anchor (tests)

    Returns:
        dict with keys:
            tier, b_paired, visible_anchor_gain, holdout_gain,
            coverage, coverage_floor_violation, anchors_visible_verified
        coverage_floor_violation: bool
            When intended_accept is provided: True iff coverage < floor AND acceptor
                intends to ACCEPT (spec-gated for M2.13 statemachine).
            When intended_accept is None: True iff coverage < floor (raw signal;
                M2.13 statemachine must re-gate via acceptor decision before enforcing).
    """
    vis = _verify_visible(ctx.get("anchors_visible", []), ctx)
    base = ctx.get("base_scores", {})
    with_ = ctx.get("with_scores", {})

    # ① visible 锚逐个 marginal_gain → 零均值化配对 b_paired
    # bg = gain(anchor, 0 → base[aid])  wg = gain(anchor, 0 → with[aid])
    # visible_anchor_gain = mean(wg - bg)  across all anchors (incl. unverified → 0)
    paired: list[tuple[float, float]] = []
    gains: list[float] = []
    for a in vis:
        aid = a["anchor_id"]
        bg = _anchors.marginal_gain(a, base_score=0.0, with_score=base.get(aid, 0.0))
        wg = _anchors.marginal_gain(a, base_score=0.0, with_score=with_.get(aid, 0.0))
        paired.append((bg, wg))
        gains.append(wg - bg)
    visible_anchor_gain = (sum(gains) / len(gains)) if gains else 0.0

    # ② coverage 门: coverage < coverage_floor with optional accept-intent gating
    cov = _anchors.coverage(vis)
    cov_floor = float(ctx.get("coverage_floor", 0.5))
    cov_low = cov < cov_floor
    # If intended_accept is provided, gate violation on both low coverage AND acceptance intent;
    # otherwise fall back to raw signal (M2.13 statemachine must gate via acceptor decision).
    _intent = ctx.get("intended_accept")  # bool | None
    coverage_floor_violation = cov_low if _intent is None else (cov_low and bool(_intent))

    # ③ holdout 每 K 轮抽检: round % K == 0 → 计算 holdout_gain 喂 selfdeception
    K = int(ctx.get("K", 5))
    rnd = int(ctx.get("round", 0))
    holdout_gain: float | None = None
    if rnd > 0 and rnd % K == 0:
        hb = ctx.get("holdout_base")
        hw = ctx.get("holdout_with")
        if hb is not None and hw is not None:
            delta = float(hw) - float(hb)
            holdout_gain = delta if delta > 0.0 else 0.0

    return {
        "tier": "B",
        "b_paired": paired,
        "visible_anchor_gain": visible_anchor_gain,
        "holdout_gain": holdout_gain,
        "coverage": cov,
        "coverage_floor_violation": coverage_floor_violation,
        "anchors_visible_verified": vis,
    }


def evaluate(sandbox_root_or_ctx, tier: str = "A",
             base_result: dict | None = None) -> dict:
    """A 档 verifiable 编排 (M1a) + B 档 visible/holdout/coverage (M2.12).

    Backward-compatible dispatch:
      - If first arg is a dict with "tier" containing "B" → B-tier path (_evaluate_btier).
      - Otherwise → A-tier path (sandbox_root: str, tier: str, base_result=None).

    A-tier Returns:
        {
          "result": <A-grade contract from grade_pytest>,
          "paired": [(before_score, after_score), ...],  # per-task
          "coverage": float
        }

    B-tier Returns (additional keys):
        {
          "tier": "B",
          "b_paired": [(bg, wg), ...],       # per-anchor zero-mean pairs for acceptor
          "visible_anchor_gain": float,       # mean marginal gain across visible anchors
          "holdout_gain": float | None,       # None on non-K rounds; computed on K rounds
          "coverage": float,                  # verified span / total span
          "coverage_floor_violation": bool,   # True if coverage < coverage_floor
          "anchors_visible_verified": [...],  # verified anchor list
        }
    """
    # B-tier dispatch: first arg is a context dict with "tier" containing "B"
    if isinstance(sandbox_root_or_ctx, dict):
        ctx = sandbox_root_or_ctx
        if "B" in str(ctx.get("tier", "")):
            return _evaluate_btier(ctx)

    # A-tier path (M1a): sandbox_root is a string path
    sandbox_root: str = sandbox_root_or_ctx
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


# ---------------------------------------------------------------------------
# M3.7: C 档评测 + contract 外 judge 主观分注入
# ---------------------------------------------------------------------------

from tools.sie.acceptor import c_tier_no_regression  # noqa: E402
from tools.sie import judges as _judges  # noqa: E402


def evaluate_c_tier(artifact_path: str, regression_replay: list[dict],
                    internal_consistency: list[tuple[float, float]]) -> dict:
    """C 档兜底评测: 无客观信号; 硬门=不退化(历史成功 replay 全保持)+内部一致性配对.

    Args:
        artifact_path: Path to artifact file (informational; not read here).
        regression_replay: List of {"task": str, "before": bool, "after": bool} dicts.
            任一 before=True 且 after=False → no_regression=False (退化).
        internal_consistency: List of (before_score, after_score) float tuples.
            Passed through verbatim as consistency_paired.

    Returns:
        {
            "no_regression": bool,            # c_tier_no_regression(regression_replay)
            "consistency_paired": list[tuple], # internal_consistency passed through
            "coverage": 0.0,                  # C 档无可验证锚，恒 0.0
        }
    """
    return {
        "no_regression": c_tier_no_regression(regression_replay),
        "consistency_paired": list(internal_consistency),
        "coverage": 0.0,
    }


def inject_judge_scores(artifact_path: str, anchors_visible: list[dict],
                        holdout: list[dict]) -> dict:
    """Contract 外注入 judge 主观分（spec §8）——candidate 不能自报 judge 分.

    Judge 走独立联网进程（codex / claude）由 harness 独立调用；alpha 由 harness
    计算，候选人无法干预。candidate 提供的任何 judge 字段均被忽略——此函数是
    judge 主观分进入评测系统的唯一入口。

    Args:
        artifact_path: Path to artifact file (UTF-8 text).
        anchors_visible: Visible anchor list; only "span" field used by judges.
        holdout: Independent holdout anchors for judge↔anchor calibration.
            Must be separate from visible set (caller responsible for isolation).

    Returns:
        {
            "codex": dict,        # judges.score(..., "codex") result
            "claude": dict,       # judges.score(..., "claude") result
            "alpha": float|None,  # pairwise_agreement(codex, claude); None if either unavailable
            "calibration": dict,  # calibrate_judge_anchor(primary_judge, holdout)
            "judge_gain": float,  # primary judge aggregate (codex if available, else claude, else 0)
        }
    """
    codex = _judges.score(artifact_path, anchors_visible, "codex")
    claude = _judges.score(artifact_path, anchors_visible, "claude")

    # alpha: pairwise agreement; None if either judge unavailable (下游 alpha_gate 处理 None)
    alpha = _judges.pairwise_agreement(codex, claude)

    # 主 judge=codex 优先；不可用→claude；双不可用→零分 degenerate
    if codex.get("available"):
        judge_gain = float(codex["aggregate"])
        calibration = _judges.calibrate_judge_anchor(codex, holdout)
    elif claude.get("available"):
        judge_gain = float(claude["aggregate"])
        calibration = _judges.calibrate_judge_anchor(claude, holdout)
    else:
        judge_gain = 0.0
        calibration = {"corr": 0.0, "n_used": 0, "degenerate": True}

    return {
        "codex": codex,
        "claude": claude,
        "alpha": alpha,
        "calibration": calibration,
        "judge_gain": judge_gain,
    }
