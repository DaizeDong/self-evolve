"""Test suite for anchors.marginal_gain (M2.5: EVE 边际增益)."""
from tools.sie import anchors


def test_marginal_gain_positive_when_verified_and_improves():
    a = {"verified": True}
    assert abs(anchors.marginal_gain(a, base_score=0.5, with_score=0.62) - 0.12) < 1e-9


def test_marginal_gain_zero_when_unverified():
    a = {"verified": False}
    assert anchors.marginal_gain(a, base_score=0.5, with_score=0.9) == 0.0


def test_marginal_gain_negative_clamped_to_zero():
    a = {"verified": True}
    assert anchors.marginal_gain(a, base_score=0.7, with_score=0.6) == 0.0


def test_marginal_gain_zero_when_no_change():
    a = {"verified": True}
    assert anchors.marginal_gain(a, base_score=0.5, with_score=0.5) == 0.0
