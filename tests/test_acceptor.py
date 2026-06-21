"""Test acceptor.py — no-regression 硬门兜底 (M1a)."""
from tools.sie.state import RunState
from tools.sie.acceptor import decide

P = {"alpha": 0.05}


def _st():
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="A")


def test_no_regression_all_improve_accept():
    """无退化, 有提升 -> ACCEPT."""
    paired = [(0.0, 1.0), (1.0, 1.0), (0.0, 1.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "ACCEPT", r


def test_any_regression_hard_reject():
    """第二个 pass->fail 退化 -> 硬 REJECT."""
    paired = [(1.0, 1.0), (1.0, 0.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "REJECT"
    assert "regress" in r["reason"].lower()


def test_no_change_no_regression_accept():
    """无退化(0->0 非退化) -> ACCEPT."""
    paired = [(1.0, 1.0), (0.0, 0.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "ACCEPT"


def test_A_tier_never_continue():
    """A 档禁 CONTINUE (二态)."""
    paired = [(0.0, 1.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] in ("ACCEPT", "REJECT"), f"got {r['decision']}"


def test_empty_paired_reject():
    """无证据不采纳."""
    r = decide([], "A", _st(), P)
    assert r["decision"] == "REJECT"
