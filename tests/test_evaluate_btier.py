"""TDD tests for evaluate.py B-tier orchestration (M2.12).

Tests:
  1. visible anchor -> b_paired + visible_anchor_gain; holdout_gain=None for non-K rounds
  2. holdout sampled on K round -> holdout_gain computed
  3. coverage_floor_violation flag when coverage < floor
  4. A-tier callers unaffected (backward-compat guard)
"""
from tools.sie import evaluate


def _anchor(aid, host, verified=True):
    return {
        "anchor_id": aid,
        "verified": verified,
        "source_url": f"https://{host}/x",
        "cik": aid,
        "period": "FY",
        "claim": "c",
        "span": "s",
        "expected": 1.0,
    }


def test_btier_paired_and_gain(monkeypatch):
    vis = [_anchor(str(i), f"h{i}") for i in range(16)]
    # base 增益 0, with 增益 0.3 (真增益)
    ctx = {
        "tier": "B",
        "round": 3,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert len(out["b_paired"]) == 16
    assert out["visible_anchor_gain"] > 0.0
    assert out["holdout_gain"] is None  # round 3 不是 K 倍数


def test_holdout_sampled_on_k_round(monkeypatch):
    vis = [_anchor(str(i), f"h{i}") for i in range(16)]
    ctx = {
        "tier": "B",
        "round": 5,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "holdout_path": None,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
        "holdout_base": 0.2,
        "holdout_with": 0.2,  # holdout 平: 背离
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["holdout_gain"] == 0.0  # round 5 = K 抽检, holdout 不涨


def test_coverage_floor_violation_flag(monkeypatch):
    vis = [_anchor(str(i), f"h{i}", verified=(i < 4)) for i in range(16)]  # 仅 4/16 verified
    ctx = {
        "tier": "B",
        "round": 1,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["coverage"] < 0.5
    assert out["coverage_floor_violation"] is True


def test_btier_zero_mean_paired_structure(monkeypatch):
    """Zero-mean normalization: b_paired = list of (bg, wg) tuples.

    bg = marginal_gain(anchor, base_score=0, with_score=base_scores[aid])
    wg = marginal_gain(anchor, base_score=0, with_score=with_scores[aid])
    visible_anchor_gain = mean(wg - bg) across verified anchors.
    """
    vis = [_anchor("a1", "h1"), _anchor("a2", "h2")]
    ctx = {
        "tier": "B",
        "round": 1,
        "K": 5,
        "coverage_floor": 0.0,
        "anchors_visible": vis,
        "base_scores": {"a1": 0.1, "a2": 0.2},
        "with_scores": {"a1": 0.5, "a2": 0.6},
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    # b_paired must be list of 2-tuples
    assert len(out["b_paired"]) == 2
    for pair in out["b_paired"]:
        assert len(pair) == 2
    # visible_anchor_gain > 0 (with > base for verified anchors)
    assert out["visible_anchor_gain"] > 0.0


def test_holdout_gain_clamped_to_zero(monkeypatch):
    """holdout_gain = max(0, holdout_with - holdout_base) — negative clamped."""
    vis = [_anchor("x", "hx")]
    ctx = {
        "tier": "B",
        "round": 10,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {"x": 0.0},
        "with_scores": {"x": 0.3},
        "holdout_base": 0.5,
        "holdout_with": 0.2,  # holdout 下降 -> clamped to 0
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["holdout_gain"] == 0.0  # negative delta clamped


def test_atier_backward_compat(tmp_path):
    """A-tier callers with positional (sandbox_root, tier) unaffected."""
    r = tmp_path / "repo"
    r.mkdir()
    (r / "test_x.py").write_text("def test_ok():\n    assert True\n")
    ev = evaluate.evaluate(str(r), "A")
    assert "result" in ev
    assert "paired" in ev
    assert "coverage" in ev


def test_coverage_floor_violation_with_intent_false(monkeypatch):
    """intended_accept=False + low coverage → coverage_floor_violation False (spec gating)."""
    vis = [_anchor(str(i), f"h{i}", verified=(i < 4)) for i in range(16)]  # 4/16 verified → cov=0.25
    ctx = {
        "tier": "B",
        "round": 1,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
        "intended_accept": False,  # explicit rejection
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["coverage"] < 0.5
    assert out["coverage_floor_violation"] is False  # gated: cov_low AND intent → False


def test_coverage_floor_violation_with_intent_true(monkeypatch):
    """intended_accept=True + low coverage → coverage_floor_violation True (spec gating)."""
    vis = [_anchor(str(i), f"h{i}", verified=(i < 4)) for i in range(16)]  # 4/16 verified → cov=0.25
    ctx = {
        "tier": "B",
        "round": 1,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
        "intended_accept": True,  # explicit acceptance
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["coverage"] < 0.5
    assert out["coverage_floor_violation"] is True  # gated: cov_low AND intent → True


def test_coverage_floor_violation_without_intent(monkeypatch):
    """No intended_accept + low coverage → coverage_floor_violation True (raw signal fallback)."""
    vis = [_anchor(str(i), f"h{i}", verified=(i < 4)) for i in range(16)]  # 4/16 verified → cov=0.25
    ctx = {
        "tier": "B",
        "round": 1,
        "K": 5,
        "coverage_floor": 0.5,
        "anchors_visible": vis,
        "base_scores": {a["anchor_id"]: 0.0 for a in vis},
        "with_scores": {a["anchor_id"]: 0.3 for a in vis},
        # No intended_accept, intent is None
    }
    monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
    out = evaluate.evaluate(ctx)
    assert out["coverage"] < 0.5
    assert out["coverage_floor_violation"] is True  # raw signal: cov < floor → True
