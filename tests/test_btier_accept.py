"""B 档真打分 → ACCEPT 机制测试（注入 fetcher, 确定性, 不打网）。

锁住"错锚被修正 → base0/with1 → 正增益 → e-process → ACCEPT"这条链路
（build_btier_scores 把真 verify 结果接进 per-anchor 打分; 此前 base/with 是空占位）。
"""
from tools.sie import evaluate, anchors, acceptor
from tools.sie.state import RunState


def _mk(cik, metric, expected, i, host):
    a = {
        "claim": f"{cik} {metric} 2024-FY",
        "span": f"unique anchor span phrase number {i}",
        "source_url": f"https://{host}/doc{i}",
        "cik": cik, "metric": metric, "period": "2024-FY", "expected": expected,
    }
    a["anchor_id"] = anchors._anchor_id(a) if hasattr(anchors, "_anchor_id") \
        else f"{cik}|{metric}|{expected}|{i}"
    a["verified"] = False
    return a


def _build(n=24, fix=None):
    """构造 n 锚: baseline expected 全错(9x), candidate 改对; fix=None 表示全改对。
    返回 (base_anchors, cand_anchors, fetcher_truth)."""
    hosts = ["sec.gov", "macrotrends.net", "stockanalysis.com", "wsj.com",
             "bloomberg.com", "reuters.com"]
    ciks = ["320193", "789019", "1018724", "1045810", "1652044"]
    metrics = ["us-gaap:Revenues", "us-gaap:Assets", "us-gaap:NetIncomeLoss",
               "us-gaap:Liabilities", "us-gaap:CashAndCashEquivalents"]
    truth = {}
    base, cand = [], []
    k = 0
    for cik in ciks:
        for m in metrics:
            if k >= n:
                break
            tv = 1_000_000.0 * (k + 1)
            truth[(cik, m, "2024-FY")] = tv
            host = hosts[k % len(hosts)]
            base.append(_mk(cik, m, tv * 9, k, host))            # baseline 错
            corrected = tv if (fix is None or k < fix) else tv * 9  # fix 个改对, 其余仍错
            cand.append(_mk(cik, m, corrected, k, host))
            k += 1

    def fetcher(anchor):
        return truth.get((str(anchor.get("cik")), anchor.get("metric"),
                          anchor.get("period")))
    return base, cand, fetcher


def test_build_btier_scores_base0_with1_on_correction():
    base, cand, fetcher = _build(24)
    bsc = evaluate.build_btier_scores(base, cand, fetcher)
    assert len(bsc["anchors_visible"]) == 24
    assert sum(bsc["base_scores"].values()) == 0.0      # baseline 全错 → 全 unverified
    assert sum(bsc["with_scores"].values()) == 24.0     # candidate 全改对 → 全 verified


def test_btier_full_correction_accepts():
    """24 锚全改对 → visible_anchor_gain=1 → e-process 跨阈 → ACCEPT。"""
    base, cand, fetcher = _build(24)
    bsc = evaluate.build_btier_scores(base, cand, fetcher)
    ctx = {"tier": "B", "round": 1, "K": 5, "anchors_visible": bsc["anchors_visible"],
           "base_scores": bsc["base_scores"], "with_scores": bsc["with_scores"],
           "fetcher": fetcher, "intended_accept": None}
    ev = evaluate.evaluate(ctx)
    assert ev["visible_anchor_gain"] > 0.9
    vis = ev.get("anchors_visible_verified", bsc["anchors_visible"])
    assert anchors.effective_independent_count(vis) >= 12
    st = RunState(run_id="v", phase="ACCEPT", round=1, parent_vid=None, tier="B")
    dec = acceptor.decide(ev["b_paired"], "B", st,
                          {"alpha": 0.05, "n_min": 8, "anchors": vis, "continue_count_cap": 5})
    assert dec["decision"] == "ACCEPT", f"expected ACCEPT, got {dec}"


def test_btier_no_correction_no_gain():
    """候选 == baseline(都错) → 无增益 → 不 ACCEPT。"""
    base, cand, fetcher = _build(24, fix=0)   # fix=0: 一个都没改对
    bsc = evaluate.build_btier_scores(base, cand, fetcher)
    assert sum(bsc["with_scores"].values()) == 0.0
    ctx = {"tier": "B", "round": 1, "K": 5, "anchors_visible": bsc["anchors_visible"],
           "base_scores": bsc["base_scores"], "with_scores": bsc["with_scores"],
           "fetcher": fetcher, "intended_accept": None}
    ev = evaluate.evaluate(ctx)
    assert ev["visible_anchor_gain"] == 0.0
    st = RunState(run_id="v", phase="ACCEPT", round=1, parent_vid=None, tier="B")
    dec = acceptor.decide(ev["b_paired"], "B", st,
                          {"alpha": 0.05, "n_min": 8, "anchors": bsc["anchors_visible"],
                           "continue_count_cap": 5})
    assert dec["decision"] != "ACCEPT"


def test_build_btier_scores_empty_candidate_falls_back():
    """无候选锚 → 空 scores(态6 回退 baseline, 保持旧行为)。"""
    base, _, fetcher = _build(12)
    bsc = evaluate.build_btier_scores(base, [], fetcher)
    assert bsc["anchors_visible"] == []
    assert bsc["base_scores"] == {} and bsc["with_scores"] == {}


def test_btier_no_spurious_drift_when_positive_gain_no_judge():
    """回归: B 档真打分后 visible_anchor_gain>band 且无 judge_gain 时, 不应误报
    judge_anchor_divergence(此前 judge_gain 默认 0 → value=-gain → |value|>band 误触发,
    drift_circuit 误停正在改进的 B run)。修复: 缺 judge_gain → judge_gain=visible_gain → value=0。"""
    from tools.sie import statemachine
    from tools.sie.state import RunState
    base, cand, fetcher = _build(24)
    bsc = evaluate.build_btier_scores(base, cand, fetcher)
    ev = evaluate.evaluate({"tier": "B", "round": 1, "K": 5,
                            "anchors_visible": bsc["anchors_visible"],
                            "base_scores": bsc["base_scores"], "with_scores": bsc["with_scores"],
                            "fetcher": fetcher, "intended_accept": None})
    assert ev["visible_anchor_gain"] > 0.15   # 远超 band, 旧逻辑会误报
    # eval_out 不含 judge_gain (B 档无 judge)
    dec = statemachine.resolve_accept(
        RunState(run_id="v", phase="ACCEPT", round=1, parent_vid=None, tier="B"),
        eval_out={**ev, "tier": "B"},
        params={"alpha": 0.05, "n_min": 8, "continue_count_cap": 5,
                "anchors": ev.get("anchors_visible_verified", bsc["anchors_visible"])},
    )
    sd = dec.get("selfdeception", {})
    assert "judge_anchor_divergence" not in sd.get("alerts", []), \
        f"B 档无 judge 不应误报 judge_anchor_divergence; got alerts={sd.get('alerts')}"
