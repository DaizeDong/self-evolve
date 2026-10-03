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
from tools.sie.verifiable import grade_pytest, grader_timeout, minimal_env
from . import anchors as _anchors

import os
import math
import subprocess
import sys
from tools.sie.sandbox import native_cwd


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
            cwd=native_cwd(sandbox_root),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            env=grader_env,
            timeout=grader_timeout(),
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
        if a.get("verified") or a.get("verification_complete"):
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
                       fetcher=None, baseline_anchors: list[dict] | None = None) -> dict:
    """Score every frozen obligation independently on the parent and candidate.

    Match identities and coverage spans come from the frozen profile. Missing or ambiguous
    current facts score zero; they never remove a previously observed parent score.
    """
    def index(items):
        result = {}
        for item in items:
            result.setdefault(_btier_match_key(item), []).append(item)
        return result

    parent_by_key = index(prof_visible_anchors if baseline_anchors is None else baseline_anchors)
    candidate_by_key = index(candidate_anchors)
    anchors_visible = []
    base_scores, with_scores = {}, {}
    unobserved = []
    frozen_keys, frozen_ids = set(), set()
    for obligation in prof_visible_anchors:
        key = _btier_match_key(obligation)
        aid = obligation.get("anchor_id")
        if not aid or key in frozen_keys or aid in frozen_ids:
            raise ValueError("Frozen B obligations require unique match keys and identities")
        frozen_keys.add(key)
        frozen_ids.add(aid)
        parent_matches = parent_by_key.get(key, [])
        current_matches = candidate_by_key.get(key, [])
        before = (_anchors.verify_anchor(parent_matches[0], fetcher=fetcher)
                  if len(parent_matches) == 1 else None)
        after = (_anchors.verify_anchor(current_matches[0], fetcher=fetcher)
                 if len(current_matches) == 1 else None)
        for label, measured in (("parent", before), ("candidate", after)):
            if measured is not None and measured.get("observed") is None:
                unobserved.append({"anchor_id": aid, "side": label})
        measured = dict(obligation)
        measured.update(
            verified=bool(after and after.get("verified")), verification_complete=True,
            observed=after.get("observed") if after else None,
            verify_reason=after.get("verify_reason") if after else "missing or ambiguous candidate fact")
        anchors_visible.append(measured)
        base_scores[aid] = 1.0 if before and before.get("verified") else 0.0
        with_scores[aid] = 1.0 if after and after.get("verified") else 0.0
    return {"anchors_visible": anchors_visible, "base_scores": base_scores,
            "with_scores": with_scores, "unobserved": unobserved}


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

    # Parent and candidate correctness are independent measurements. A current failure
    # must retain its parent score; the frozen obligation remains in the denominator.
    paired: list[tuple[float, float]] = []
    gains: list[float] = []
    for a in vis:
        aid = a["anchor_id"]
        bg = float(base.get(aid, 0.0))
        wg = float(with_.get(aid, 0.0)) if a.get("verified") else 0.0
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in (bg, wg)):
            raise ValueError("B scores must be finite correctness values in [0, 1]")
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

    # Use the producer's durable schedule; legacy callers retain modulo sampling.
    K = int(ctx.get("K", 5))
    rnd = int(ctx.get("round", 0))
    if K <= 0:
        raise ValueError("K must be positive")
    holdout_gain: float | None = None
    holdout_missing = False
    if ctx.get("_holdout_due", rnd > 0 and rnd % K == 0):
        hb = ctx.get("holdout_base")
        hw = ctx.get("holdout_with")
        if hb is None or hw is None:
            holdout_missing = True
        else:
            values = (float(hb), float(hw))
            if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
                raise ValueError("Holdout scores must be finite correctness values in [0, 1]")
            delta = values[1] - values[0]
            holdout_gain = delta if delta > 0.0 else 0.0

    return {
        "tier": "B",
        "b_paired": paired,
        "visible_anchor_gain": visible_anchor_gain,
        "holdout_gain": holdout_gain,
        "holdout_missing": holdout_missing,
        "coverage": cov,
        "coverage_floor_violation": coverage_floor_violation,
        "anchors_visible_verified": vis,
        "archive_scores": {"anchor": sum(after for _, after in paired) / len(paired)} if paired else {},
    }


def candidate_grade_error(result, parent_dimensions=None):
    """Return a reason when candidate observations cannot support acceptance."""
    if not isinstance(result, dict) or result.get("available") is False:
        return "unavailable"
    if (type(result.get("grader_exit_code")) is not int
            or result["grader_exit_code"] != 0 or result.get("task_passed") is not True):
        return "grader_failed_or_incomplete"
    dimensions = result.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        return "empty_dimensions"
    names = set()
    for item in dimensions:
        if not isinstance(item, dict):
            return "invalid_dimensions"
        name, score = item.get("name"), item.get("score")
        if (not isinstance(name, str) or not name or name in names
                or type(score) not in (int, float) or not 0 <= score <= 1
                or not math.isfinite(score)):
            return "invalid_dimensions"
        names.add(name)
    if parent_dimensions and not (
            len(parent_dimensions) == 1 and parent_dimensions[0].get("name") == "pytest"):
        if any(item.get("name") not in names for item in parent_dimensions):
            return "parent_tasks_missing"
    return None


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
    grade_error = candidate_grade_error(
        after, base_result.get("dimensions") if isinstance(base_result, dict) else None)
    if grade_error is not None:
        coverage = after.get("verifiable_coverage", 0.0) if isinstance(after, dict) else 0.0
        return {"result": after, "paired": [], "coverage": coverage,
                "usable": False, "grade_error": grade_error}
    after_dims = after["dimensions"]

    # Build per-task paired list
    if base_result and base_result.get("dimensions"):
        base_dims = base_result["dimensions"]
        paired = pair_parent_dimensions(base_dims, after_dims)
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
        "usable": True,
    }


def pair_parent_dimensions(before, after):
    """Compare measured parent tasks by identity; removed tasks cannot disappear."""
    if len(before) == 1 and before[0]['name'] == 'pytest':
        # Legacy aggregate baselines remain aggregate, including failed descendants.
        return [(float(before[0]['score']), min((float(d['score']) for d in after), default=0.0))]
    current = {item['name']: item['score'] for item in after}
    return [(float(item['score']), float(current.get(item['name'], 0.0))) for item in before]


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
    replay_valid = (isinstance(regression_replay, list) and bool(regression_replay)
                    and all(isinstance(item, dict) and type(item.get("before")) is bool
                            and type(item.get("after")) is bool for item in regression_replay))
    consistency_valid = (isinstance(internal_consistency, (list, tuple)) and bool(internal_consistency)
                         and all(isinstance(pair, (list, tuple)) and len(pair) == 2
                                 and all(type(value) in (int, float) and 0 <= value <= 1
                                         and math.isfinite(value) for value in pair)
                                 for pair in internal_consistency))
    available = bool(replay_valid and consistency_valid)
    return {
        "no_regression": available and c_tier_no_regression(regression_replay),
        "consistency_paired": list(internal_consistency) if consistency_valid else [],
        "coverage": 0.0, "available": available,
        "regression_evidence": "available" if replay_valid else "missing_or_invalid",
        "consistency_evidence": "available" if consistency_valid else "missing_or_invalid",
        "scenario_eval": "not_implemented",
    }


def inject_judge_scores(artifact_path: str, anchors_visible: list[dict],
                        holdout: list[dict]) -> dict:
    """Contract 外注入 judge 主观分（spec §8）——candidate 不能自报 judge 分.

    The harness invokes llmcall's default judge mode and computes agreement only
    when successful results identify distinct known actual provider families.
    Candidate-supplied judge fields are ignored.

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
    previous = codex.get("provider") if codex.get("available") else None
    kwargs = {"avoid": previous} if previous else {}
    claude = _judges.score(artifact_path, anchors_visible, "claude", **kwargs)

    from tools.sie.llm_adapter import independent
    sufficient = independent([codex, claude])
    alpha = _judges.pairwise_agreement(codex, claude) if sufficient else None

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
        "independence": "independent" if sufficient else "insufficient_independence",
    }
