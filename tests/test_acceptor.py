"""Test acceptor.py — M1b.3 e-process semantics (supersedes M1a no-regression-only).

M1a 版假设"无退化即 ACCEPT"(兜底门); M1b.3 升级为 PACE A 档 e-process:
  - 无退化但证据不足 (e-value < 1/α) → REJECT (M1a 旧行为被 supersede)
  - 有退化 → 硬 REJECT (仍成立)
  - A 档禁 CONTINUE (仍成立)
  - 空配对 → REJECT (仍成立)

已更新的用例 (M1a → M1b.3 超越):
  - test_no_regression_all_improve_accept: 3 对样本量不足以使 e-value 达 1/α=20,
    故应 REJECT 而非 M1a 的 ACCEPT。
  - test_no_change_no_regression_accept:   纯持平(d=0)无信号, e-value=1.0 < 20,
    故应 REJECT 而非 M1a 的 ACCEPT。

这是预期的语义升级 (反自欺命门), 不是 regression。
"""
from tools.sie.state import RunState
from tools.sie.acceptor import decide

P = {"alpha": 0.05}


def _st():
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="A")


def test_no_regression_small_sample_rejects():
    """[M1b.3 supersede] 无退化 + 有提升但样本量少 (n=3) → e-value 达不到 1/α → REJECT.

    M1a 此用例期望 ACCEPT (无退化即过);
    M1b.3 e-process 要求统计显著才 ACCEPT, n=3 远不够 → REJECT.
    """
    paired = [(0.0, 1.0), (1.0, 1.0), (0.0, 1.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "REJECT", (
        f"小样本无法达到 e-process 阈值 1/α=20, 应 REJECT; got {r}")
    assert r["evalue"] < 20.0, f"e-value 应 < 20, got {r['evalue']}"


def test_any_regression_hard_reject():
    """第二个 pass->fail 退化 -> 硬 REJECT (覆盖 e-process)."""
    paired = [(1.0, 1.0), (1.0, 0.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "REJECT"
    assert "regress" in r["reason"].lower()


def test_no_change_no_evidence_rejects():
    """[M1b.3 supersede] 无退化(0→0 非退化)但无改进信号 → e-value=1.0 < 1/α → REJECT.

    M1a 此用例期望 ACCEPT (无退化即过);
    M1b.3 e-process 中 d=0 → payoff=0 → wealth 不增, 始终 1.0 → REJECT.
    """
    paired = [(1.0, 1.0), (0.0, 0.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] == "REJECT", (
        f"纯持平无统计信号, 应 REJECT; got {r}")


def test_A_tier_never_continue():
    """A 档禁 CONTINUE (二态)."""
    paired = [(0.0, 1.0)]
    r = decide(paired, "A", _st(), P)
    assert r["decision"] in ("ACCEPT", "REJECT"), f"got {r['decision']}"


def test_empty_paired_reject():
    """无证据不采纳."""
    r = decide([], "A", _st(), P)
    assert r["decision"] == "REJECT"
