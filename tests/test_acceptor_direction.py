"""Improvement evidence must not grow by betting on worse candidate scores."""
import sys
from types import ModuleType

import pytest

from tools.make_fixtures import betting_direction_samples
from tools.sie import acceptor, anchors, evaluate, statemachine
from tools.sie.state import RunState


@pytest.mark.parametrize("name,should_accept", [
    ("regressions_then_gains", False),
    ("interleaved", False),
    ("positive_control", True),
])
def test_native_btier_admission_requires_improvement_evidence(name, should_accept):
    samples = betting_direction_samples()
    evaluation = evaluate.evaluate(samples["contexts"][name])
    assert evaluation["visible_anchor_gain"] > 0.0
    assert evaluation["coverage"] > 0.5
    assert not evaluation["coverage_floor_violation"]
    assert anchors.effective_independent_count(evaluation["anchors_visible_verified"]) >= 12
    state = RunState(run_id=samples["run_id"], phase="ACCEPT", round=1,
                     parent_vid=None, tier="B")
    decision = statemachine.resolve_accept(state, evaluation, {"alpha": 0.05})
    assert not decision["selfdeception"]["alerts"]
    assert (decision["acceptor_decision"] == "ACCEPT") is should_accept


def test_ons_regressions_cannot_accumulate_improvement_evidence():
    diffs = betting_direction_samples()["negative_diffs"]
    peak, path = acceptor._ons_betting_wealth(diffs, 0.05)
    assert peak <= 1.0
    assert all(value <= 1.0 for value in path)


def test_confseq_adapter_selects_improvement_direction(monkeypatch):
    """The optional dependency's theta selects which score direction earns evidence."""
    np = pytest.importorskip("numpy", reason="optional confseq adapter requires NumPy")
    betting = ModuleType("confseq.betting")

    def no_fallback(*args, **kwargs):
        raise AssertionError("Confseq adapter test must execute the selected backend")

    def directional_process(x, m, alpha, theta=0.5):
        payoff = x - m
        return np.cumprod(1.0 + (payoff if theta == 1.0 else -payoff))

    betting.betting_mart = directional_process
    monkeypatch.setattr(acceptor, "_ons_betting_wealth", no_fallback)
    monkeypatch.setitem(sys.modules, "confseq", ModuleType("confseq"))
    monkeypatch.setitem(sys.modules, "confseq.betting", betting)
    peak, path = acceptor._wealth_betting(betting_direction_samples()["negative_diffs"], 0.05)
    assert peak <= 1.0
    assert all(value <= 1.0 for value in path)


def test_installed_confseq_does_not_use_regressions_as_evidence(monkeypatch):
    pytest.importorskip("confseq.betting", reason="optional confseq package is not installed")

    def no_fallback(*args, **kwargs):
        raise AssertionError("Installed confseq branch must execute without ONS fallback")

    monkeypatch.setattr(acceptor, "_ons_betting_wealth", no_fallback)
    peak, path = acceptor._wealth_betting(betting_direction_samples()["negative_diffs"], 0.05)
    assert peak <= 1.0
    assert all(value <= 1.0 for value in path)
