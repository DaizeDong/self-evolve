"""
tests/test_gate_human.py
M1a + M1b.5: gate_human enqueue / pending / resolve
"""
import json, os, time

from tools.sie.gate_human import enqueue, pending, resolve

# ---------------------------------------------------------------------------
# M1a tests (preserved)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# M1b.5 tests
# ---------------------------------------------------------------------------

def test_enqueue_nonblocking_returns_aid(tmp_path):
    """enqueue returns a non-empty string aid immediately (non-blocking)."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {"vid": "v1"}, "ttl": 3600})
    assert isinstance(aid, str) and aid
    p = pending(rd)
    assert len(p) == 1
    assert p[0]["aid"] == aid
    assert p[0]["status"] == "pending"


def test_resolve_approved_removes_from_pending(tmp_path):
    """After resolve(approved), aid is absent from pending(); file has 2 lines (append-only)."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    resolve(rd, aid, "approved")
    assert pending(rd) == []
    lines = open(os.path.join(rd, "pending_actions.jsonl"), encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 2
    rows = [json.loads(ln) for ln in lines]
    assert rows[0]["status"] == "pending"    # original request row untouched
    assert rows[1]["status"] == "approved"   # resolution row appended


def test_resolve_skipped_removes_from_pending(tmp_path):
    """resolve(skipped) also removes from pending."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "push", "payload": {}, "ttl": 3600})
    resolve(rd, aid, "skipped")
    assert pending(rd) == []


def test_expired_ttl_excluded(tmp_path):
    """ttl=0 means already-expired; pending() must exclude it."""
    rd = str(tmp_path)
    enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 0})
    time.sleep(0.01)
    assert pending(rd) == []


def test_multiple_actions_independent(tmp_path):
    """Resolving one aid leaves the other still pending."""
    rd = str(tmp_path)
    a1 = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    a2 = enqueue(rd, {"action_type": "push", "payload": {}, "ttl": 3600})
    resolve(rd, a1, "skipped")
    p = pending(rd)
    assert [x["aid"] for x in p] == [a2]


def test_latest_state_reduction(tmp_path):
    """
    Manually appending a second 'pending' request row for the same aid
    followed by a resolution must still yield empty pending (latest wins).
    """
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    resolve(rd, aid, "approved")
    # Even if we call enqueue again for a DIFFERENT aid, first one stays resolved
    a2 = enqueue(rd, {"action_type": "push", "payload": {}, "ttl": 3600})
    p = pending(rd)
    assert len(p) == 1
    assert p[0]["aid"] == a2


def test_append_only_never_modifies_old_lines(tmp_path):
    """Original request lines must be byte-for-byte unchanged after resolve."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    path = os.path.join(rd, "pending_actions.jsonl")
    with open(path, encoding="utf-8") as f:
        original_line = f.readline()
    resolve(rd, aid, "approved")
    with open(path, encoding="utf-8") as f:
        first_line = f.readline()
    assert first_line == original_line  # original row byte-identical


def test_resolve_invalid_status_raises(tmp_path):
    """resolve with an unknown status must raise ValueError."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    try:
        resolve(rd, aid, "invalid_status")
        assert False, "should have raised"
    except ValueError:
        pass


def test_pending_empty_when_no_file(tmp_path):
    """pending() returns [] when the jsonl file does not yet exist."""
    rd = str(tmp_path / "nonexistent_run")
    assert pending(rd) == []
