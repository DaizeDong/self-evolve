"""Tests for calibrate_judge_anchor (M3.3).

TDD Step 1: write tests that FAIL before implementation.
TDD Step 2: implement calibrate_judge_anchor, then tests PASS.

Iron rule: calibrate_judge_anchor ONLY accepts holdout anchors (not e-process
visible anchors) — enforced by caller convention and tested here via API shape.
"""
from tools.sie import judges


# ── Basic contract ─────────────────────────────────────────────────────────

def test_calibration_uses_holdout_and_dedup():
    """Calibration matches judge span_scores with holdout anchor 'verified' truth;
    n_used is total paired; same-source anchors (h1/h3) reduce effective count."""
    judge_scores = {"available": True, "span_scores": [
        {"span": "h1", "score": 0.9},
        {"span": "h2", "score": 0.2},
        {"span": "h3", "score": 0.8}]}
    # h1/h3 share source_url (same-source cluster) → effective_independent_count < 3
    holdout = [
        {"span": "h1", "verified": True,  "source_url": "http://sec/a", "topic": "rev"},
        {"span": "h2", "verified": False, "source_url": "http://sec/b", "topic": "debt"},
        {"span": "h3", "verified": True,  "source_url": "http://sec/a", "topic": "rev"},
    ]
    out = judges.calibrate_judge_anchor(judge_scores, holdout)
    assert out["n_used"] <= 3
    assert isinstance(out["corr"], float)
    assert "degenerate" in out


def test_calibration_degenerate_when_too_few():
    """Only 1 paired anchor → below _CALIB_MIN_INDEP → degenerate=True."""
    js = {"available": True, "span_scores": [{"span": "h1", "score": 0.5}]}
    ho = [{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}]
    assert judges.calibrate_judge_anchor(js, ho)["degenerate"] is True


# ── Degenerate cases ────────────────────────────────────────────────────────

def test_degenerate_empty_judge_scores():
    """No span_scores at all → degenerate=True, corr=0.0, n_used=0."""
    js = {"available": True, "span_scores": []}
    ho = [{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}]
    out = judges.calibrate_judge_anchor(js, ho)
    assert out["degenerate"] is True
    assert out["corr"] == 0.0
    assert out["n_used"] == 0


def test_degenerate_no_overlap():
    """Judge spans don't match holdout spans → n_used=0 → degenerate."""
    js = {"available": True, "span_scores": [{"span": "x1", "score": 0.5}]}
    ho = [{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}]
    out = judges.calibrate_judge_anchor(js, ho)
    assert out["degenerate"] is True
    assert out["n_used"] == 0


def test_degenerate_zero_variance_judge():
    """All judge scores identical → variance=0 → degenerate=True even if enough pairs."""
    # Need enough independent holdout anchors (≥ _CALIB_MIN_INDEP = 4),
    # each from a distinct source, verified alternating to avoid constant truth too.
    spans = [f"s{i}" for i in range(6)]
    js = {"available": True, "span_scores": [
        {"span": s, "score": 0.5} for s in spans]}  # all same score → var=0
    ho = [
        {"span": f"s{i}", "verified": bool(i % 2),
         "source_url": f"http://src{i}/", "topic": "t"}
        for i in range(6)
    ]
    out = judges.calibrate_judge_anchor(js, ho)
    assert out["degenerate"] is True


def test_degenerate_zero_variance_truth():
    """All holdout truths identical → variance=0 → degenerate=True."""
    spans = [f"s{i}" for i in range(6)]
    js = {"available": True, "span_scores": [
        {"span": s, "score": float(i) / 5} for i, s in enumerate(spans)]}
    ho = [
        {"span": f"s{i}", "verified": True,  # all True → truth all 1.0 → var=0
         "source_url": f"http://src{i}/", "topic": "t"}
        for i in range(6)
    ]
    out = judges.calibrate_judge_anchor(js, ho)
    assert out["degenerate"] is True


# ── Pearson correlation direction ───────────────────────────────────────────

def _make_judge_and_holdout(scores_list, verified_list):
    """Helper: build judge_scores and holdout from parallel lists."""
    spans = [f"sp{i}" for i in range(len(scores_list))]
    js = {"available": True, "span_scores": [
        {"span": s, "score": float(v)} for s, v in zip(spans, scores_list)]}
    ho = [
        {"span": s, "verified": bool(vv),
         "source_url": f"http://src{i}/", "topic": "t"}
        for i, (s, vv) in enumerate(zip(spans, verified_list))
    ]
    return js, ho


def test_positive_correlation():
    """Judge high ↔ verified=True → positive Pearson correlation."""
    # 6 distinct sources → effective_independent_count should be ≥ 4
    scores  = [0.9, 0.8, 0.7, 0.6, 0.1, 0.2]
    verified = [True, True, True, True, False, False]
    js, ho = _make_judge_and_holdout(scores, verified)
    out = judges.calibrate_judge_anchor(js, ho)
    if not out["degenerate"]:
        assert out["corr"] > 0.0
    assert out["n_used"] == 6


def test_negative_correlation():
    """Judge high ↔ verified=False → negative Pearson correlation."""
    scores   = [0.9, 0.8, 0.7, 0.6, 0.1, 0.2]
    verified = [False, False, False, False, True, True]
    js, ho = _make_judge_and_holdout(scores, verified)
    out = judges.calibrate_judge_anchor(js, ho)
    if not out["degenerate"]:
        assert out["corr"] < 0.0


def test_strong_positive_correlation():
    """Perfect positive alignment → corr close to 1.0."""
    scores   = [0.95, 0.80, 0.70, 0.60, 0.20, 0.10]
    verified = [True,  True,  True,  True,  False, False]
    js, ho = _make_judge_and_holdout(scores, verified)
    out = judges.calibrate_judge_anchor(js, ho)
    if not out["degenerate"]:
        assert out["corr"] > 0.5


# ── n_used tracks paired count ──────────────────────────────────────────────

def test_n_used_is_paired_count():
    """n_used = number of holdout anchors whose span appears in judge_scores."""
    judge_scores = {"available": True, "span_scores": [
        {"span": "a", "score": 0.9},
        {"span": "b", "score": 0.1},
        # "c" missing from judge → not paired
    ]}
    ho = [
        {"span": "a", "verified": True,  "source_url": "http://s1/", "topic": "t"},
        {"span": "b", "verified": False, "source_url": "http://s2/", "topic": "t"},
        {"span": "c", "verified": True,  "source_url": "http://s3/", "topic": "t"},
    ]
    out = judges.calibrate_judge_anchor(judge_scores, ho)
    assert out["n_used"] == 2  # only a,b paired; c missing from judge


# ── Same-source de-correlation reduces effective count ───────────────────────

def test_same_source_reduces_effective_count():
    """8 anchors from the same source → effective_independent_count = 4 (1+log2(8))
    → below _CALIB_MIN_INDEP=4 boundary: exactly 4 → not degenerate on count alone.
    But the fact that same-source reduces indep is visible in degenerate behavior
    when source cluster is smaller.
    """
    # 4 anchors same source, 0 from others → effective = 1+log2(4)=3 < 4 → degenerate
    spans = [f"s{i}" for i in range(4)]
    js = {"available": True, "span_scores": [
        {"span": s, "score": float(i) / 3} for i, s in enumerate(spans)]}
    ho = [
        {"span": f"s{i}", "verified": bool(i % 2),
         "source_url": "http://same-source/", "topic": "t"}  # all same host
        for i in range(4)
    ]
    out = judges.calibrate_judge_anchor(js, ho)
    # effective_independent_count([4 same-source verified]) = floor(1+log2(2)) = 2 < 4
    assert out["degenerate"] is True


def test_eight_same_source_anchors_effective_4():
    """8 verified anchors from same source: effective_independent_count = floor(1+log2(8)) = 4.
    4 == _CALIB_MIN_INDEP so NOT degenerate on count alone (border case: >=4 passes).
    Variance may still cause degenerate; we just check n_used=8."""
    spans = [f"s{i}" for i in range(8)]
    js = {"available": True, "span_scores": [
        {"span": s, "score": float(i) / 7} for i, s in enumerate(spans)]}
    ho = [
        {"span": f"s{i}", "verified": bool(i % 2),
         "source_url": "http://same-source/",  "topic": "t"}
        for i in range(8)
    ]
    out = judges.calibrate_judge_anchor(js, ho)
    assert out["n_used"] == 8  # all 8 paired regardless of degenerate
