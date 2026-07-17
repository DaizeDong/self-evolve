"""TDD tests for proxy.py cross-request sequence anomaly detection (M2.9)."""
from tools.sie import proxy


def test_monotone_param_sequence_flagged(tmp_path):
    d = str(tmp_path)
    # 连续单调字典序 ticker = 疑似逐字符编码信道
    for t in ["AAA", "AAB", "AAC", "AAD", "AAE", "AAF", "AAG", "AAH"]:
        proxy.record_outbound(d, "quote", {"ticker": t})
    out = proxy.sequence_anomaly(d)
    assert out["anomalous"] is True
    assert any("monoton" in r or "sequence" in r for r in out["reasons"])


def test_normal_diverse_sequence_ok(tmp_path):
    d = str(tmp_path)
    for t in ["MSFT", "AAPL", "JNJ", "XOM", "KO"]:
        proxy.record_outbound(d, "quote", {"ticker": t})
    out = proxy.sequence_anomaly(d)
    assert out["anomalous"] is False


def test_frequency_spike_flagged(tmp_path):
    d = str(tmp_path)
    for i in range(200):
        proxy.record_outbound(d, "quote", {"ticker": "AAPL"})
    out = proxy.sequence_anomaly(d)
    assert out["anomalous"] is True
    assert any("frequency" in r or "spike" in r for r in out["reasons"])


def test_empty_run_dir_not_anomalous(tmp_path):
    d = str(tmp_path)
    out = proxy.sequence_anomaly(d)
    assert out["anomalous"] is False
    assert out["score"] == 0.0
    assert out["reasons"] == []


def test_insufficient_window_not_anomalous(tmp_path):
    d = str(tmp_path)
    # Only 3 records, below _MONOTONE_RUN_MIN=6
    for t in ["AAA", "AAB", "AAC"]:
        proxy.record_outbound(d, "quote", {"ticker": t})
    out = proxy.sequence_anomaly(d)
    assert out["anomalous"] is False


def test_record_outbound_creates_jsonl(tmp_path):
    d = str(tmp_path)
    proxy.record_outbound(d, "quote", {"ticker": "AAPL"})
    import os, json
    path = os.path.join(d, "outbound_seq.jsonl")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["kind"] == "quote"
    assert rec["params"]["ticker"] == "AAPL"
