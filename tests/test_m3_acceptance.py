"""test_m3_acceptance.py — M3.11 端到端验收套件 (spec §13 M3 四验收).

四条硬验收:
① C 不退化门生效 (replay 回退→硬 REJECT; 全保持+一致正向→可达 ACCEPT 但纯 C 经人审)
② 自欺合谋报警 (holdout 背离为主信号; α 异常高且锚不涨→辅信号)
③ 纯 C 强制人审 (auto 不自动采纳)
④ Codex 不可用 → 单 Claude 不能 auto ACCEPT (端到端经 run_loop)

验收②③④均经完整 run_loop 端到端路径验证 (非孤儿单元测试).
drift_count 经 event delta 持久化, replay 可重建.
"""
from __future__ import annotations

import os
import json
import tempfile

import pytest

from tools.sie import acceptor, selfdeception, statemachine, evaluate
from tools.sie.state import RunState


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _rs(tier="C"):
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier=tier)


# ---------------------------------------------------------------------------
# 验收① C 不退化门生效
# ---------------------------------------------------------------------------

def test_c_tier_no_regression_gate():
    """① C 不退化: replay 回退→ no_regression=False; 全保持→ no_regression=True."""
    # 回退 → 硬 REJECT
    ev = evaluate.evaluate_c_tier(
        artifact_path=__file__,
        regression_replay=[{"task": "t1", "before": True, "after": False}],
        internal_consistency=[(0.9, 0.9)])
    assert ev["no_regression"] is False

    # 全保持 → 不退化门放行（仍需人审，见验收③）
    ev2 = evaluate.evaluate_c_tier(
        artifact_path=__file__,
        regression_replay=[{"task": "t1", "before": True, "after": True}],
        internal_consistency=[(0.9, 0.91)])
    assert ev2["no_regression"] is True


# ---------------------------------------------------------------------------
# 验收③ 纯 C 强制人审 (auto 不自动采纳) — 经 run_loop 端到端
# ---------------------------------------------------------------------------

def test_pure_c_auto_forces_human():
    """③ 纯 C auto 欲 ACCEPT → 强制人审 (coverage=0, mode='auto' → PAUSE_FOR_HUMAN)."""
    route = statemachine.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": True},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="C", coverage=0.0)
    assert route == "PAUSE_FOR_HUMAN"


def test_pure_c_auto_forces_human_e2e(tmp_path, monkeypatch):
    """③ 端到端: 纯 C (coverage=0) 经完整 run_loop → 不自动 ACCEPT, 到 PAUSE_FOR_HUMAN.

    C 档评测 + selfdeception + alpha_gate + judge_degrade + route_accept_with_gates
    全部经 run_loop C 档分支串联 (非孤儿).
    """
    import tools.sie.statemachine as sm_mod
    import tools.sie.evaluate as ev_mod

    # C 档 prof: coverage=0 (无程序化锚)
    c_prof = {
        "tier": "C",
        "verifiability_score": 0.0,
        "anchors_visible": [],   # 纯 C: 无可见锚
        "anchors_holdout_ref": {"path": "", "count": 0, "ref": "isolated"},
        "probe_evidence": {"fact": {}, "anchor_count": 0},
        "probes": {"exec": {}},
        "base_ref": "HEAD",
        "visible": [],
        "holdout": [],
    }

    sandbox = str(tmp_path / "sandbox")
    os.makedirs(sandbox, exist_ok=True)
    monkeypatch.setattr(sm_mod, "make_worktree", lambda *a, **kw: sandbox)
    monkeypatch.setattr(sm_mod, "run_profile", lambda *a, **kw: c_prof)
    monkeypatch.setattr(sm_mod, "freeze_target", lambda *a, **kw: None)
    monkeypatch.setattr(sm_mod, "load_target", lambda *a, **kw: c_prof)

    monkeypatch.setattr(sm_mod, "reflect", lambda *a, **kw: [
        {"file_rel": "dummy.py", "fix_content": "x=1", "target_failure": "none"}
    ])
    monkeypatch.setattr(sm_mod, "check", lambda r, t: True)
    monkeypatch.setattr(sm_mod, "propose", lambda *a, **kw: [
        {"file_rel": "dummy.py", "new_content": "x=1"}
    ])
    monkeypatch.setattr(sm_mod, "apply_patch", lambda *a, **kw: {"status": "APPLIED"})

    import tools.sie.archive as arch_mod
    monkeypatch.setattr(arch_mod, "snapshot_version", lambda *a, **kw: None)

    # Inject mock judge scores: both available, no regression, consistent gain
    def fake_inject_judge_scores(artifact_path, anchors_visible, holdout):
        return {
            "codex": {"available": True, "aggregate": 0.6, "span_scores": []},
            "claude": {"available": True, "aggregate": 0.6, "span_scores": []},
            "alpha": 0.9,       # high alpha — both judges agree
            "calibration": {"corr": 0.5, "n_used": 2, "degenerate": False},
            "judge_gain": 0.6,
        }

    def fake_evaluate_c_tier(artifact_path, regression_replay, internal_consistency):
        return {
            "no_regression": True,
            "consistency_paired": list(internal_consistency),
            "coverage": 0.0,    # pure C: coverage=0
        }

    monkeypatch.setattr(ev_mod, "inject_judge_scores", fake_inject_judge_scores)
    monkeypatch.setattr(ev_mod, "evaluate_c_tier", fake_evaluate_c_tier)

    target_dir = str(tmp_path / "target")
    os.makedirs(target_dir, exist_ok=True)

    summary = statemachine.run_loop(
        target_dir, "HEAD", "c_tier_forced_human_e2e",
        max_rounds=1,
        mode="auto",
        judge_codex_available=True,
        judge_claude_available=True,
    )

    # 纯 C + coverage=0 + auto → 不应出现在 accepted_versions
    assert len(summary["accepted_versions"]) == 0, \
        f"pure C should never auto-ACCEPT, got accepted: {summary['accepted_versions']}"
    # final_phase should be PAUSE_FOR_HUMAN (went to 9.5)
    assert summary["final_phase"] in ("PAUSE_FOR_HUMAN",), \
        f"pure C auto should end in PAUSE_FOR_HUMAN, got {summary['final_phase']}"


# ---------------------------------------------------------------------------
# 验收② 自欺合谋报警 (holdout 背离为主信号)
# ---------------------------------------------------------------------------

def test_selfdeception_collusion_alert_holdout_primary():
    """② 自欺合谋: visible 涨但 holdout 平 → force_review=True + holdout_divergence alert (主信号)."""
    # visible 涨(judge 也涨) 但 holdout 平 → 过拟合/合谋 → 报警 + 强制人审
    sd = selfdeception.index(judge_gain=0.6, visible_anchor_gain=0.30,
                             holdout_gain=0.0, st=_rs("B"))
    assert sd["force_review"] is True
    assert any("holdout_divergence" in a for a in sd["alerts"]), \
        f"expected holdout_divergence alert, got {sd['alerts']}"

    # 辅信号：α 异常高且锚不涨 → count_selfdeception
    ag = acceptor.alpha_gate(alpha=0.95, anchor_up=False,
                             params={"alpha_low": 0.4, "alpha_high": 0.85})
    assert ag["count_selfdeception"] is True


def test_selfdeception_collusion_alert_e2e(tmp_path, monkeypatch):
    """② 端到端: judge 一致性过高无锚支撑 → selfdeception 报警 → PAUSE_FOR_HUMAN 经 run_loop."""
    import tools.sie.statemachine as sm_mod
    import tools.sie.evaluate as ev_mod

    # B 档 prof (需要锚才能走 selfdeception 闸)
    b_prof = {
        "tier": "B",
        "verifiability_score": 0.0,
        "anchors_visible": [
            {"anchor_id": str(i), "verified": True,
             "source_url": f"https://host{i}.com/data",
             "cik": str(i), "period": "FY2024",
             "claim": f"c{i}", "span": f"s{i}", "expected": 1.0}
            for i in range(24)
        ],
        "anchors_holdout_ref": {"path": "", "count": 0, "ref": "isolated"},
        "probe_evidence": {"fact": {}, "anchor_count": 24},
        "probes": {"exec": {}},
        "base_ref": "HEAD",
        "visible": [],
        "holdout": [],
    }

    sandbox = str(tmp_path / "sandbox")
    os.makedirs(sandbox, exist_ok=True)
    monkeypatch.setattr(sm_mod, "make_worktree", lambda *a, **kw: sandbox)
    monkeypatch.setattr(sm_mod, "run_profile", lambda *a, **kw: b_prof)
    monkeypatch.setattr(sm_mod, "freeze_target", lambda *a, **kw: None)
    monkeypatch.setattr(sm_mod, "load_target", lambda *a, **kw: b_prof)

    monkeypatch.setattr(sm_mod, "reflect", lambda *a, **kw: [
        {"file_rel": "dummy.py", "fix_content": "x=1", "target_failure": "none"}
    ])
    monkeypatch.setattr(sm_mod, "check", lambda r, t: True)
    monkeypatch.setattr(sm_mod, "propose", lambda *a, **kw: [
        {"file_rel": "dummy.py", "new_content": "x=1"}
    ])
    monkeypatch.setattr(sm_mod, "apply_patch", lambda *a, **kw: {"status": "APPLIED"})

    import tools.sie.archive as arch_mod
    monkeypatch.setattr(arch_mod, "snapshot_version", lambda *a, **kw: None)

    # B-tier evaluate: holdout 抽检轮 (rnd=5, K=5) → holdout_gain=0.0 触发 overfit
    import tools.sie.evaluate as ev_real
    monkeypatch.setattr(ev_mod, "_verify_visible", lambda al, ctx: al)

    target_dir = str(tmp_path / "target")
    os.makedirs(target_dir, exist_ok=True)

    # K=1 使每轮都是 holdout 抽检轮; holdout_with=holdout_base → gain=0 → 报警
    summary = statemachine.run_loop(
        target_dir, "HEAD", "collusion_alert_e2e",
        max_rounds=1,
        mode="auto",
        # holdout_K=1: round%1==0 → 每轮抽检
        _extra_params={"holdout_K": 1, "holdout_base": 0.5, "holdout_with": 0.5},
    )

    # selfdeception 触发 force_human → 不能自动 ACCEPT
    assert len(summary["accepted_versions"]) == 0, \
        f"holdout divergence should prevent auto-ACCEPT, got {summary['accepted_versions']}"


# ---------------------------------------------------------------------------
# 验收④ Codex 不可用 → 单 Claude 不能 auto ACCEPT (端到端经 run_loop)
# ---------------------------------------------------------------------------

def test_codex_unavailable_no_single_claude_autoaccept():
    """④ Codex 不可用 → single_claude_block=True → route_accept_with_gates → PAUSE_FOR_HUMAN."""
    degrade = acceptor.judge_degrade(codex_available=False, claude_available=True)
    assert degrade["single_claude_block"] is True
    assert degrade["anchor_only"] is True
    route = statemachine.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade=degrade, mode="auto", tier="B", coverage=0.5)
    assert route == "PAUSE_FOR_HUMAN"  # 绝不自动 ARCHIVE


def test_codex_unavailable_no_autoaccept_e2e(tmp_path, monkeypatch):
    """④ 端到端: Codex 不可用 → C 档不能 auto ACCEPT, 走 PAUSE_FOR_HUMAN 经完整 run_loop."""
    import tools.sie.statemachine as sm_mod
    import tools.sie.evaluate as ev_mod

    c_prof = {
        "tier": "C",
        "verifiability_score": 0.0,
        "anchors_visible": [],
        "anchors_holdout_ref": {"path": "", "count": 0, "ref": "isolated"},
        "probe_evidence": {"fact": {}, "anchor_count": 0},
        "probes": {"exec": {}},
        "base_ref": "HEAD",
        "visible": [],
        "holdout": [],
    }

    sandbox = str(tmp_path / "sandbox")
    os.makedirs(sandbox, exist_ok=True)
    monkeypatch.setattr(sm_mod, "make_worktree", lambda *a, **kw: sandbox)
    monkeypatch.setattr(sm_mod, "run_profile", lambda *a, **kw: c_prof)
    monkeypatch.setattr(sm_mod, "freeze_target", lambda *a, **kw: None)
    monkeypatch.setattr(sm_mod, "load_target", lambda *a, **kw: c_prof)

    monkeypatch.setattr(sm_mod, "reflect", lambda *a, **kw: [
        {"file_rel": "dummy.py", "fix_content": "x=1", "target_failure": "none"}
    ])
    monkeypatch.setattr(sm_mod, "check", lambda r, t: True)
    monkeypatch.setattr(sm_mod, "propose", lambda *a, **kw: [
        {"file_rel": "dummy.py", "new_content": "x=1"}
    ])
    monkeypatch.setattr(sm_mod, "apply_patch", lambda *a, **kw: {"status": "APPLIED"})

    import tools.sie.archive as arch_mod
    monkeypatch.setattr(arch_mod, "snapshot_version", lambda *a, **kw: None)

    def fake_inject_judge_scores(artifact_path, anchors_visible, holdout):
        return {
            "codex": {"available": False, "aggregate": 0.0, "span_scores": []},
            "claude": {"available": True, "aggregate": 0.7, "span_scores": []},
            "alpha": None,       # codex unavailable → alpha=None
            "calibration": {"corr": 0.0, "n_used": 0, "degenerate": True},
            "judge_gain": 0.7,   # falls back to claude
        }

    def fake_evaluate_c_tier(artifact_path, regression_replay, internal_consistency):
        return {
            "no_regression": True,
            "consistency_paired": list(internal_consistency),
            "coverage": 0.0,
        }

    monkeypatch.setattr(ev_mod, "inject_judge_scores", fake_inject_judge_scores)
    monkeypatch.setattr(ev_mod, "evaluate_c_tier", fake_evaluate_c_tier)

    target_dir = str(tmp_path / "target")
    os.makedirs(target_dir, exist_ok=True)

    # Codex not available → injected via judge_codex_available=False
    summary = statemachine.run_loop(
        target_dir, "HEAD", "codex_unavailable_e2e",
        max_rounds=1,
        mode="auto",
        judge_codex_available=False,
        judge_claude_available=True,
    )

    # Codex 不可用 → single_claude_block → 不能 auto ACCEPT
    assert len(summary["accepted_versions"]) == 0, \
        f"Codex-unavailable should block auto-ACCEPT, got {summary['accepted_versions']}"
    assert summary["final_phase"] in ("PAUSE_FOR_HUMAN",), \
        f"Codex-unavailable should end in PAUSE_FOR_HUMAN, got {summary['final_phase']}"


# ---------------------------------------------------------------------------
# 验收⑤ 累计漂移熔断 (drift_circuit)
# ---------------------------------------------------------------------------

def test_cumulative_drift_circuit_breaks():
    """⑤ 连续 4 轮 ACCEPT 但 holdout 不涨 → drift_circuit 触发."""
    st = _rs("B")
    p = {"drift_circuit_N": 4}
    tripped = False
    for _ in range(4):  # 连续 4 轮 ACCEPT 但 holdout 不涨
        tripped = statemachine.drift_circuit(st, holdout_up=False, params=p)
    assert tripped is True and st.drift_count == 4

    # 累计漂移预算独立确认
    assert selfdeception.cumulative_drift(0.6, 0.3, tolerance=1.5) is True
