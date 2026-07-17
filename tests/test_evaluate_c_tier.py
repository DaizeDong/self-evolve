"""TDD tests for evaluate.py C-tier orchestration + judge score injection (M3.7).

Tests:
  1. evaluate_c_tier shape: no_regression/consistency_paired/coverage=0
  2. evaluate_c_tier regression: before=True & after=False -> no_regression=False
  3. inject_judge_scores: both judges mocked -> codex/claude/alpha/calibration/judge_gain
  4. inject_judge_scores alpha=None when judges unavailable
  5. judge scores come from inject, not candidate artifact (contract-external guarantee)
"""
from tools.sie import evaluate, judges


# ---------------------------------------------------------------------------
# Test 1: evaluate_c_tier shape
# ---------------------------------------------------------------------------

def test_evaluate_c_tier_shape(tmp_path):
    art = tmp_path / "a.md"; art.write_text("# c artifact\n", encoding="utf-8")
    replay = [{"task": "t1", "before": True, "after": True}]
    consistency = [(0.9, 0.92), (0.8, 0.81)]
    out = evaluate.evaluate_c_tier(str(art), replay, consistency)
    assert out["no_regression"] is True
    assert out["coverage"] == 0.0
    assert out["consistency_paired"] == consistency


# ---------------------------------------------------------------------------
# Test 2: regression replay -> no_regression=False
# ---------------------------------------------------------------------------

def test_evaluate_c_tier_regression(tmp_path):
    art = tmp_path / "b.md"; art.write_text("# artifact\n", encoding="utf-8")
    # before=True, after=False means a previously passing task now fails
    replay = [
        {"task": "t1", "before": True, "after": True},
        {"task": "t2", "before": True, "after": False},   # regression!
    ]
    consistency = [(0.8, 0.75)]
    out = evaluate.evaluate_c_tier(str(art), replay, consistency)
    assert out["no_regression"] is False
    assert out["coverage"] == 0.0
    assert out["consistency_paired"] == consistency


# ---------------------------------------------------------------------------
# Test 3: inject_judge_scores, both judges available, alpha computed by harness
# ---------------------------------------------------------------------------

def test_inject_judge_scores_independent(monkeypatch, tmp_path):
    art = tmp_path / "a.md"; art.write_text("body\n", encoding="utf-8")
    # Two judges give identical scores -> alpha=1.0; harness computes, not candidate
    def fake_score(p, av, family):
        return {"family": family, "available": True,
                "span_scores": [{"span": "s1", "score": 0.7}], "aggregate": 0.7,
                "unspanned_penalized": 0}
    monkeypatch.setattr(judges, "score", fake_score)
    monkeypatch.setattr(judges, "calibrate_judge_anchor",
                        lambda js, ho: {"corr": 0.5, "n_used": 2, "degenerate": False})
    out = evaluate.inject_judge_scores(
        str(art), anchors_visible=[{"span": "s1"}],
        holdout=[{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}])
    assert out["alpha"] == 1.0
    assert out["codex"]["available"] and out["claude"]["available"]
    assert "judge_gain" in out
    # judge_gain comes from codex (primary) aggregate
    assert out["judge_gain"] == 0.7
    assert "calibration" in out
    assert out["calibration"]["corr"] == 0.5


# ---------------------------------------------------------------------------
# Test 4: inject_judge_scores alpha=None when judges unavailable
# ---------------------------------------------------------------------------

def test_inject_judge_scores_alpha_none(monkeypatch, tmp_path):
    art = tmp_path / "c.md"; art.write_text("text\n", encoding="utf-8")
    # Both judges unavailable -> pairwise_agreement returns None
    def fake_score_unavailable(p, av, family):
        return {"family": family, "available": False,
                "span_scores": [], "aggregate": 0.0, "unspanned_penalized": 1}
    monkeypatch.setattr(judges, "score", fake_score_unavailable)
    out = evaluate.inject_judge_scores(
        str(art), anchors_visible=[{"span": "s1"}], holdout=[])
    # pairwise_agreement returns None when either judge is unavailable
    assert out["alpha"] is None
    assert out["judge_gain"] == 0.0
    assert out["calibration"]["degenerate"] is True


# ---------------------------------------------------------------------------
# Test 5: codex unavailable -> falls back to claude for judge_gain + calibration
# ---------------------------------------------------------------------------

def test_inject_judge_scores_codex_unavailable_falls_back_to_claude(monkeypatch, tmp_path):
    art = tmp_path / "d.md"; art.write_text("text\n", encoding="utf-8")
    def fake_score(p, av, family):
        if family == "codex":
            return {"family": "codex", "available": False,
                    "span_scores": [], "aggregate": 0.0, "unspanned_penalized": 1}
        # claude available
        return {"family": "claude", "available": True,
                "span_scores": [{"span": "s1", "score": 0.6}], "aggregate": 0.6,
                "unspanned_penalized": 0}
    calib_calls = []
    def fake_calibrate(js, ho):
        calib_calls.append(js["family"])
        return {"corr": 0.3, "n_used": 1, "degenerate": True}
    monkeypatch.setattr(judges, "score", fake_score)
    monkeypatch.setattr(judges, "calibrate_judge_anchor", fake_calibrate)
    out = evaluate.inject_judge_scores(
        str(art), anchors_visible=[{"span": "s1"}],
        holdout=[{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}])
    # alpha=None because codex unavailable
    assert out["alpha"] is None
    # judge_gain falls back to claude
    assert out["judge_gain"] == 0.6
    # calibration done on claude
    assert calib_calls == ["claude"]


# ---------------------------------------------------------------------------
# Test 6: inject_judge_scores calls judges.score twice (once per family)
# ---------------------------------------------------------------------------

def test_inject_judge_scores_calls_both_families(monkeypatch, tmp_path):
    art = tmp_path / "e.md"; art.write_text("text\n", encoding="utf-8")
    called_families = []
    def fake_score(p, av, family):
        called_families.append(family)
        return {"family": family, "available": True,
                "span_scores": [{"span": "s1", "score": 0.5}], "aggregate": 0.5,
                "unspanned_penalized": 0}
    monkeypatch.setattr(judges, "score", fake_score)
    monkeypatch.setattr(judges, "calibrate_judge_anchor",
                        lambda js, ho: {"corr": 0.0, "n_used": 0, "degenerate": True})
    evaluate.inject_judge_scores(str(art), anchors_visible=[{"span": "s1"}], holdout=[])
    assert sorted(called_families) == ["claude", "codex"]
