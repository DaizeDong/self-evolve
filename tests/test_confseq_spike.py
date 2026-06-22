"""Task M1a.0: confseq spike 测试 — 验证 e-process 对纯噪声高拒绝率, 对真实增益高检出率.

Run with:
    conda run -n confseq_test python -m pytest tests/test_confseq_spike.py -v
"""
import pytest
pytest.importorskip("confseq", reason="confseq optional; only in conda env confseq_test")

import numpy as np
from spikes.confseq_spike import run_noise_spike


def test_noise_rejection_rate_high():
    """纯噪声配对差(均值0)在 alpha=0.05 下应几乎不被误判"有增益".
    误报率(把纯噪声当增益)必须 <= 0.10.
    """
    res = run_noise_spike(n_trials=200, n_steps=300, alpha=0.05, seed=7)
    assert "false_reject_rate" in res, f"missing false_reject_rate in {res}"
    assert res["false_reject_rate"] <= 0.10, (
        f"false_reject_rate={res['false_reject_rate']:.3f} > 0.10 — "
        f"e-process 对纯噪声误报过高: {res}"
    )
    assert res["e_interface"], "e_interface must be non-empty"


def test_true_gain_detected():
    """注入真实正向漂移(均值+0.3)应被高概率检出(>=0.80)."""
    res = run_noise_spike(n_trials=100, n_steps=300, alpha=0.05, seed=11, drift=0.3)
    assert "detect_rate" in res, f"missing detect_rate in {res}"
    assert res["detect_rate"] >= 0.80, (
        f"detect_rate={res['detect_rate']:.3f} < 0.80 — "
        f"e-process 对真实增益检出率不足: {res}"
    )
