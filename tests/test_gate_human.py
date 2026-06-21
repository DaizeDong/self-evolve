from tools.sie.gate_human import enqueue, pending


def test_enqueue_returns_aid_and_nonblocking(tmp_path):
    rd = str(tmp_path / "run")
    aid = enqueue(rd, {"run_id": "r1", "round": 2, "action_type": "land",
                       "payload": {"vid": "v3"}})
    assert isinstance(aid, str) and aid
    q = pending(rd)
    assert len(q) == 1
    assert q[0]["aid"] == aid
    assert q[0]["status"] == "pending"
    assert q[0]["action_type"] == "land"


def test_multiple_enqueue(tmp_path):
    rd = str(tmp_path / "run")
    a1 = enqueue(rd, {"action_type": "approve"})
    a2 = enqueue(rd, {"action_type": "land"})
    assert a1 != a2
    assert len(pending(rd)) == 2
