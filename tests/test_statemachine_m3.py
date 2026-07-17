"""Tests for M3.6: release_valve, drift_circuit, route_accept_with_gates.

TDD order follows brief Steps 1/3/5.
"""
from tools.sie import statemachine as sm
from tools.sie.state import RunState


def _rs(**kw):
    b = dict(run_id="r", phase="LOOP", round=1, parent_vid=None, tier="C")
    b.update(kw)
    return RunState(**b)


# ---------------------------------------------------------------------------
# Step 1: release_valve, 只升人审频率，不降阈，不自动采纳
# ---------------------------------------------------------------------------

def test_release_valve_only_raises_review_freq():
    p = {"no_progress_release_M": 3, "review_freq_base": 1, "review_freq_boost": 3}
    # 未达 M → 基础频率
    assert sm.release_valve(_rs(no_progress=2), p) == 1
    # 达 M → 升高（但不返回任何"降阈"信号）
    assert sm.release_valve(_rs(no_progress=3), p) == 3


def test_release_valve_does_not_change_thresholds():
    """release_valve 绝不改 acceptor 阈、绝不自动采纳 — 只改返回值(人审频率)."""
    p = {"no_progress_release_M": 3, "review_freq_base": 1, "review_freq_boost": 5}
    st = _rs(no_progress=10)
    freq = sm.release_valve(st, p)
    # 只有 int 频率返回, 计数器不变
    assert isinstance(freq, int)
    assert freq == 5
    assert st.no_progress == 10   # 不清零计数器
    assert st.forced_review == 0  # 不增 forced_review


def test_release_valve_below_M_returns_base():
    p = {"no_progress_release_M": 5, "review_freq_base": 2, "review_freq_boost": 10}
    for np in range(5):
        assert sm.release_valve(_rs(no_progress=np), p) == 2


# ---------------------------------------------------------------------------
# Step 3: drift_circuit, 连续 ACCEPT 但 holdout 不涨 → drift++ → ≥N 停机
# ---------------------------------------------------------------------------

def test_drift_circuit_trips():
    p = {"drift_circuit_N": 4}
    st = _rs(drift_count=0)
    tripped = False
    for _ in range(4):
        tripped = sm.drift_circuit(st, holdout_up=False, params=p)
    assert st.drift_count == 4
    assert tripped is True


def test_drift_circuit_resets_on_holdout_up():
    p = {"drift_circuit_N": 4}
    st = _rs(drift_count=3)
    assert sm.drift_circuit(st, holdout_up=True, params=p) is False
    assert st.drift_count == 0   # holdout 涨了 → 清零


def test_drift_circuit_not_tripped_below_N():
    p = {"drift_circuit_N": 4}
    st = _rs(drift_count=0)
    for _ in range(3):
        result = sm.drift_circuit(st, holdout_up=False, params=p)
    assert result is False
    assert st.drift_count == 3


def test_drift_circuit_persists_via_event(tmp_path):
    """drift_count 必须经 event delta 持久化——replay 后重建值与内存一致."""
    from tools.sie.events import append_event, replay

    run_dir = str(tmp_path / "run")
    import os
    os.makedirs(run_dir, exist_ok=True)

    # 写入初始化事件
    append_event(run_dir, {"type": "INIT", "run_id": "r", "phase": "LOOP",
                           "parent_vid": None, "tier": "C", "round": 1})
    # 模拟 3 次 drift_count += 1 via DRIFT_SIGNAL 事件（M2.13 B 档范式）
    for _ in range(3):
        append_event(run_dir, {"type": "DRIFT_SIGNAL", "phase": "EVALUATE",
                               "round": 1, "drift_count_delta": 1})

    rebuilt = replay(run_dir)
    assert rebuilt.drift_count == 3, (
        f"drift_count should be 3 after 3 DRIFT_SIGNAL events, got {rebuilt.drift_count}"
    )


# ---------------------------------------------------------------------------
# Step 5: route_accept_with_gates, 各闸组合 → 正确终态
# ---------------------------------------------------------------------------

def test_route_pure_c_auto_forces_human():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": True},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="C", coverage=0.0)
    assert out == "PAUSE_FOR_HUMAN"


def test_route_codex_unavailable_blocks_auto():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": True, "force_review": True},
        mode="auto", tier="B", coverage=0.5)
    assert out == "PAUSE_FOR_HUMAN"   # 禁单 Claude 自动 ACCEPT


def test_route_sd_block_rejects():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": True, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="B", coverage=0.5)
    assert out == "REJECT"   # visible 留存增益<ε 禁 ACCEPT


def test_route_clean_accept_archives():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="A", coverage=1.0)
    assert out == "ARCHIVE"


# ---------------------------------------------------------------------------
# 额外: 端到端验证, Codex 不可用 → 单 Claude 不能 auto ACCEPT
# ---------------------------------------------------------------------------

def test_route_codex_unavailable_single_claude_block_end_to_end():
    """端到端：judge_degrade(codex_available=False) → single_claude_block → PAUSE_FOR_HUMAN."""
    from tools.sie.acceptor import judge_degrade
    degrade = judge_degrade(codex_available=False, claude_available=True)
    assert degrade["single_claude_block"] is True
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade=degrade,
        mode="auto", tier="B", coverage=0.8)
    assert out == "PAUSE_FOR_HUMAN"


def test_route_codex_available_does_not_block():
    """Codex 可用 → degrade.single_claude_block=False → 正常路由."""
    from tools.sie.acceptor import judge_degrade
    degrade = judge_degrade(codex_available=True, claude_available=True)
    assert degrade["single_claude_block"] is False
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade=degrade,
        mode="auto", tier="A", coverage=1.0)
    assert out == "ARCHIVE"


def test_route_pure_c_no_coverage_gated_mode_ok():
    """纯 C + coverage=0 但 mode='gated' → 不触发 auto 强制人审 (mode 非 auto)."""
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="gated", tier="C", coverage=0.0)
    # gated 模式不走 auto 强制路径, 返回 ARCHIVE (已由人介入核准)
    assert out == "ARCHIVE"


def test_route_alpha_gate_force_review():
    """alpha_gate_out.force_review → PAUSE_FOR_HUMAN."""
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": True},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="A", coverage=1.0)
    assert out == "PAUSE_FOR_HUMAN"


def test_route_sd_force_review_human():
    """sd.force_review → PAUSE_FOR_HUMAN (不是 REJECT)."""
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": True},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="B", coverage=0.5)
    assert out == "PAUSE_FOR_HUMAN"


def test_route_non_accept_decision_rejects():
    """decision != ACCEPT → REJECT."""
    out = sm.route_accept_with_gates(
        decision={"decision": "REJECT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="A", coverage=1.0)
    assert out == "REJECT"


def test_route_priority_block_over_force_review():
    """sd.block_accept 优先于任意 force_review → 返回 REJECT 而非 PAUSE_FOR_HUMAN."""
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": True},
        sd={"block_accept": True, "force_review": True},
        alpha_gate_out={"force_review": True},
        degrade={"single_claude_block": True, "force_review": True},
        mode="auto", tier="C", coverage=0.0)
    assert out == "REJECT"
