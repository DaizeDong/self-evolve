"""M1b.4: acceptor 对抗/锚相关单测 — 反自欺加固.

对抗用例覆盖:
  1. 小相关锚集 (8 同源锚微涨) 经去相关降权后 e-value 不过阈 → REJECT
  2. n_min 门: B 档锚数不足 n_min → REJECT
  3. 主观正漂移序列: B 档主观稳步漂移被拒
  4. 降权正确性: 同源簇按 1/size 降权; 全独立锚不降权

spec §9 对抗闸门: 小相关锚集(如 8 个同源锚每轮 +微涨)
  须靠"同源去相关降权 + B 档 n_min 有效独立锚下限"被拒.
"""
from tools.sie.state import RunState
from tools.sie.acceptor import decide, _decorrelate_downweight

PARAMS = {
    "α": 0.05,
    "n_min": 8,
    "continue_count_cap": 5,
    "evalue_max_step": 4.0,
    "effective_independent_anchor_min": 12,
}


def _rs(tier="B"):
    return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)


# ---------------------------------------------------------------------------
# 对抗: 小相关锚集被拒
# ---------------------------------------------------------------------------

def test_small_correlated_anchor_set_rejected():
    """8 个同源锚每轮统一 +0.01 微涨; 同源去相关降权后信号极弱 → 不采纳.

    8 个 diff=0.01 均来自 src#1 → 降权后 diff=0.01/8=0.00125 × 8 个.
    微弱信号无法使 e-value 达 1/α=20 → REJECT (或 CONTINUE, 不得 ACCEPT).
    """
    diffs = [0.01] * 8
    clusters = ["src#1"] * 8
    dw = _decorrelate_downweight(diffs, clusters)
    d = decide([(0.5, 0.5 + x) for x in dw], "B", _rs(), PARAMS)
    assert d["decision"] != "ACCEPT", (
        f"相关锚虚高应被降权拦截, 不得 ACCEPT; got {d}")


def test_b_tier_below_n_min_rejected():
    """B 档 n=4 < n_min=8 → REJECT, reason 含 'n_min'."""
    d = decide([(0.5, 0.6)] * 4, "B", _rs(), PARAMS)
    assert d["decision"] == "REJECT", f"n < n_min 应 REJECT; got {d}"
    assert "n_min" in d["reason"], f"reason 应含 'n_min'; got {d['reason']}"


# ---------------------------------------------------------------------------
# 对抗: 主观正漂移被拒
# ---------------------------------------------------------------------------

def test_subjective_positive_drift_rejected():
    """B 档主观稳步漂移序列: 每锚 +0.02, n=8, 经方差缩放后信号微弱 → 不 ACCEPT.

    _scale_subjective 用历史方差归一化; 小且均匀的漂移 pstdev 极小,
    但 evalue_max_step=4.0 截断使缩放后值 ≤ 1.0/cap → e-value 仍不过阈.
    预期 REJECT (或 CONTINUE), 不得 ACCEPT.
    """
    # 主观微漂: all diffs = 0.02, n=8 满足 n_min
    diffs_raw = [0.02] * 8
    paired = [(0.5, 0.5 + d) for d in diffs_raw]
    d = decide(paired, "B", _rs(), PARAMS)
    # pstdev([0.02]*8) = 0 → sd fallback=1.0 → scaled = 0.02/4.0 = 0.005 × 8
    # 极弱信号不应 ACCEPT
    assert d["decision"] != "ACCEPT", (
        f"均匀主观漂移信号不足, 不得 ACCEPT; got {d}")


# ---------------------------------------------------------------------------
# 正确性: 降权单元
# ---------------------------------------------------------------------------

def test_decorrelate_independent_anchors_kept():
    """全独立锚 (每个 cluster_id 唯一) → 权重=1, 差不变."""
    diffs = [0.5] * 6
    clusters = [f"src#{i}" for i in range(6)]
    dw = _decorrelate_downweight(diffs, clusters)
    assert dw == diffs, f"独立锚不应降权; got {dw}"


def test_decorrelate_correlated_cluster_downweighted():
    """同源簇 (size=4) 内每个锚降权到 1/4."""
    diffs = [1.0] * 4
    clusters = ["clA"] * 4
    dw = _decorrelate_downweight(diffs, clusters)
    assert dw == [0.25, 0.25, 0.25, 0.25], f"size=4 簇应降权到 0.25; got {dw}"


def test_decorrelate_mixed_clusters():
    """混合: 2 个独立锚 + 1 个 size=2 簇, 各自降权正确."""
    diffs   = [1.0, 1.0, 1.0, 1.0]
    clusters = ["indA", "indB", "grp", "grp"]
    dw = _decorrelate_downweight(diffs, clusters)
    # indA, indB: size=1 → 1/1=1.0; grp: size=2 → 1/2=0.5
    assert dw == [1.0, 1.0, 0.5, 0.5], f"混合降权不正确; got {dw}"
