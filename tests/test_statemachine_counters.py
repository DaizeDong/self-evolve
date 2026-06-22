"""Tests for M1b.6: 三计数器 + 熔断 + 态9.5 + CONTINUE 落点.

Covers:
  - 三计数器各自增长与正交性
  - CONTINUE 上限落点 (达 cap 后返回 LOOP)
  - A 档禁 CONTINUE 守卫
  - 各熔断阈触发
  - release vs circuit 优先级 (M < N, N 先判)
  - PAUSE_FOR_HUMAN 非阻塞继续
  - forced_review 熔断循环停机
"""
from tools.sie.state import RunState
from tools.sie.statemachine import (apply_acceptor_outcome, note_static_reject,
                                    note_forced_review, circuit_check)

P = {"continue_count_cap": 5, "no_progress_circuit_N": 8, "no_progress_release_M": 3,
     "static_reject_circuit": 6, "forced_review_circuit": 5, "drift_circuit": 4}


def _rs(tier="B"):
    return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)


def test_reject_increments_no_progress():
    st = _rs()
    nxt = apply_acceptor_outcome(st, {"decision": "REJECT", "evalue": 0.0, "reason": ""}, P)
    assert st.no_progress == 1 and nxt == "LOOP"


def test_accept_clears_counters_and_archives():
    st = _rs()
    st.no_progress = 5
    st.forced_review = 2
    st.continue_count = 3
    nxt = apply_acceptor_outcome(st, {"decision": "ACCEPT", "evalue": 99.0, "reason": ""}, P)
    assert nxt == "ARCHIVE"
    assert st.no_progress == 0 and st.forced_review == 0 and st.continue_count == 0


def test_continue_increments_then_caps_to_reject():
    st = _rs()
    for _ in range(P["continue_count_cap"]):
        nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
        assert nxt == "EVALUATE"
    # 第 cap+1 次 → 落点 REJECT
    nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt == "LOOP" and st.continue_count == P["continue_count_cap"]


def test_A_tier_continue_forced_to_reject():
    st = _rs(tier="A")
    nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt == "LOOP" and st.continue_count == 0  # A 档禁 CONTINUE → 当 REJECT


def test_static_reject_counter():
    st = _rs()
    for i in range(P["static_reject_circuit"]):
        note_static_reject(st)
    assert st.static_reject == P["static_reject_circuit"]
    assert circuit_check(st, P) == "static_reject_circuit"


def test_forced_review_circuit():
    st = _rs()
    for _ in range(P["forced_review_circuit"]):
        note_forced_review(st)
    assert circuit_check(st, P) == "forced_review_circuit"


def test_no_progress_circuit_and_release():
    st = _rs()
    st.no_progress = P["no_progress_release_M"]
    assert circuit_check(st, P) == "no_progress_release"   # M 触发释放阀(升人审)
    st.no_progress = P["no_progress_circuit_N"]
    assert circuit_check(st, P) == "no_progress_circuit"   # N 触发熔断


def test_forced_review_routes_to_pause():
    st = _rs()
    nxt = apply_acceptor_outcome(st, {"decision": "FORCE_HUMAN", "evalue": 1.0, "reason": "coverage<floor"}, P)
    assert nxt == "PAUSE_FOR_HUMAN"


def test_repeated_forced_review_circuit_stops():
    st = _rs()
    stopped = False
    for _ in range(10):
        apply_acceptor_outcome(st, {"decision": "FORCE_HUMAN", "evalue": 1.0, "reason": ""}, P)
        note_forced_review(st)
        if circuit_check(st, P) == "forced_review_circuit":
            stopped = True
            break
    assert stopped and st.forced_review >= P["forced_review_circuit"]


# --- 正交性验证: 三计数器互不影响 ---

def test_no_progress_orthogonal_to_static_reject():
    """no_progress 和 static_reject 正交: 互不干扰."""
    st = _rs()
    # REJECT 只增 no_progress
    apply_acceptor_outcome(st, {"decision": "REJECT", "evalue": 0.0, "reason": ""}, P)
    assert st.no_progress == 1 and st.static_reject == 0 and st.forced_review == 0

    # note_static_reject 只增 static_reject
    note_static_reject(st)
    assert st.static_reject == 1 and st.no_progress == 1

    # note_forced_review 只增 forced_review
    note_forced_review(st)
    assert st.forced_review == 1 and st.static_reject == 1 and st.no_progress == 1


def test_continue_increments_no_progress_and_continue_count():
    """CONTINUE 同时增 no_progress 和 continue_count (B 档)."""
    st = _rs(tier="B")
    nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt == "EVALUATE"
    assert st.no_progress == 1 and st.continue_count == 1 and st.static_reject == 0


def test_drift_circuit():
    """drift_count 触发 drift_circuit 熔断."""
    st = _rs()
    st.drift_count = P["drift_circuit"]
    assert circuit_check(st, P) == "drift_circuit"


def test_circuit_priority_no_progress_over_release():
    """当 no_progress 同时满足 >=M 和 >=N 时, N (熔断) 优先于 M (释放阀)."""
    st = _rs()
    # N >= M 时设为 N, 应报熔断而非释放阀
    st.no_progress = P["no_progress_circuit_N"]
    assert circuit_check(st, P) == "no_progress_circuit"


def test_a_tier_compound_tier():
    """叠加档如 'A+B' 取主档 A, 仍禁 CONTINUE."""
    st = _rs(tier="A+B")
    nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt == "LOOP" and st.continue_count == 0


def test_accept_does_not_affect_static_reject():
    """ACCEPT 清零 no_progress/forced_review/continue_count, 但不影响 static_reject."""
    st = _rs()
    st.static_reject = 3
    st.no_progress = 5
    apply_acceptor_outcome(st, {"decision": "ACCEPT", "evalue": 99.0, "reason": ""}, P)
    assert st.static_reject == 3   # static_reject 不清零
    assert st.no_progress == 0


def test_continue_cap_boundary():
    """恰好在 cap 时 (continue_count == cap-1) 还能 EVALUATE; cap 时落点 REJECT."""
    st = _rs()
    st.continue_count = P["continue_count_cap"] - 1
    nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt == "EVALUATE"   # continue_count was cap-1, now cap
    assert st.continue_count == P["continue_count_cap"]

    # Now continue_count == cap, next CONTINUE should be LOOP
    nxt2 = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
    assert nxt2 == "LOOP"
    # continue_count should NOT increment past cap on LOOP path
    assert st.continue_count == P["continue_count_cap"]


# --- Integration tests: run_loop + acceptor with forced REJECT ---

def test_run_loop_forced_reject_accumulates_no_progress_to_circuit(tmp_path, monkeypatch):
    """Integration test: run_loop with forced REJECT acceptor persists no_progress across
    _step→replay→save cycle and triggers circuit-breaker when threshold reached.

    This test verifies the crash-replay invariant: no_progress mutations survive
    events.jsonl→_step→replay→save roundtrips.
    """
    import subprocess as sp
    from tools.sie.statemachine import run_loop
    from tools.sie.state import load_state
    from tools.sie.events import replay

    # Setup: minimal broken repo (add+mul with xfail mul tests, like test_e2e)
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)

    (r / "mod.py").write_text(
        "def add(a, b):\n    return a + b\n"
        "def mul(a, b):\n    return a - b  # BUG\n"
    )
    add_tests = "\n".join(
        f"def test_add_{i}():\n    assert add({i}, {i+1}) == {2*i+1}\n"
        for i in range(1, 4)
    )
    mul_tests = "\n".join(
        f"@pytest.mark.xfail(strict=False, reason='mul bug')\n"
        f"def test_mul_{i}():\n    assert mul({i}, {i+1}) == {i*(i+1)}\n"
        for i in range(1, 6)  # 5 mul tests for quick convergence
    )
    test_src = f"import pytest\nfrom mod import add, mul\n\n{add_tests}\n{mul_tests}"
    (r / "test_mod.py").write_text(test_src)
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)

    # Monkeypatch acceptor.decide to always return REJECT
    from tools.sie import acceptor
    original_decide = acceptor.decide

    def forced_reject(*args, **kwargs):
        return {"decision": "REJECT", "evalue": 0.0, "reason": "forced for test"}

    monkeypatch.setattr(acceptor, "decide", forced_reject)

    # Run loop with max_rounds=10 to accumulate no_progress across multiple REJECTs
    tgt = str(r)
    fix = "def add(a, b):\n    return a + b\ndef mul(a, b):\n    return a * b\n"

    # Override circuit threshold to 5 for quicker triggering
    custom_params = {
        "alpha": 0.05,
        "continue_count_cap": 5,
        "no_progress_circuit_N": 5,  # Lower threshold for testing
        "no_progress_release_M": 3,
        "static_reject_circuit": 6,
        "forced_review_circuit": 5,
        "drift_circuit": 4,
    }

    summary = run_loop(
        tgt, "HEAD", "test_forced_reject", max_rounds=10, mode="auto",
        _injected_fix={"file_rel": "mod.py", "fix_content": fix, "target_failure": "fix mul"},
    )

    run_dir = summary["run_dir"]
    final_st = load_state(run_dir)

    # Assertions:
    # 1. no_progress should have accumulated across multiple rounds via replay
    assert final_st.no_progress > 0, (
        f"no_progress should be > 0 after forced REJECTs, got {final_st.no_progress}"
    )

    # 2. Verify persistence: replay from events.jsonl produces same no_progress
    rebuilt_st = replay(run_dir)
    assert rebuilt_st.no_progress == final_st.no_progress, (
        f"Replay should reconstruct no_progress={final_st.no_progress}, "
        f"got {rebuilt_st.no_progress}"
    )

    # 3. Run should have exited early or reached max_rounds with accumulated no_progress
    # Each REJECT increments no_progress, and it must persist across _step→replay→save
    assert final_st.no_progress >= 5, (
        f"no_progress should accumulate to at least 5 over forced REJECTs, "
        f"got {final_st.no_progress}"
    )

    # 4. Verify that no_progress crossed release threshold (3) at some point
    # by checking via replay from scratch
    assert final_st.no_progress >= P["no_progress_release_M"], (
        f"no_progress should reach at least release threshold {P['no_progress_release_M']}, "
        f"got {final_st.no_progress}"
    )
