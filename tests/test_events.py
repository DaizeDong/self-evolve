import os
import json
from tools.sie.state import RunState, save_state, load_state
from tools.sie.events import append_event, replay


def _drive(run_dir):
    # 模拟主循环逐态推进, 每态既 append_event 又 save_state
    seq = [
        {"type": "INIT", "run_id": "r1", "tier": "A", "parent_vid": "base", "round": 0, "phase": "INIT"},
        {"type": "PROFILE", "phase": "PROFILE", "tier": "A"},
        {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 1},
        {"type": "REJECT", "phase": "LOOP", "no_progress_delta": 1},
        {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 2},
        {"type": "ACCEPT", "phase": "ARCHIVE", "no_progress_reset": True, "parent_vid": "v1"},
    ]
    rs = RunState(run_id="r1", phase="INIT", round=0, parent_vid=None, tier="A")
    for ev in seq:
        append_event(run_dir, ev)
        rs = replay(run_dir)        # 真相源驱动
        save_state(rs, run_dir)     # 旁路落盘
    return rs


def test_replay_matches_saved_state(tmp_path):
    run_dir = str(tmp_path)
    final = _drive(run_dir)
    # 崩溃重放: 删掉 state.json, 仅从 events.jsonl 重建
    os.remove(os.path.join(run_dir, "state.json"))
    rebuilt = replay(run_dir)
    assert rebuilt == final


def test_counters_apply(tmp_path):
    run_dir = str(tmp_path)
    final = _drive(run_dir)
    assert final.round == 2
    assert final.no_progress == 0   # ACCEPT 重置
    assert final.forced_review == 0  # ACCEPT 清零 forced_review
    assert final.parent_vid == "v1"
    assert final.tier == "A"


def test_replay_skips_corrupted_half_line(tmp_path):
    """Replay must skip corrupted/half-written lines without crashing.

    Simulates crash-time append: events.jsonl末尾有半行/损坏行，
    replay should skip it and reconstruct state from valid events only.
    """
    run_dir = str(tmp_path)

    # Write valid sequence up to round 1
    seq = [
        {"type": "INIT", "run_id": "r1", "tier": "A", "parent_vid": "base", "round": 0, "phase": "INIT"},
        {"type": "PROFILE", "phase": "PROFILE", "tier": "A"},
        {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 1},
        {"type": "REJECT", "phase": "LOOP", "no_progress_delta": 1},
    ]

    events_file = os.path.join(run_dir, "events.jsonl")
    os.makedirs(run_dir, exist_ok=True)
    with open(events_file, "w", encoding="utf-8") as fh:
        for ev in seq:
            fh.write(json.dumps(ev) + "\n")

    # Append a corrupted half-line (simulating crash mid-write)
    with open(events_file, "a", encoding="utf-8") as fh:
        fh.write('{"type": "ROUND_BEGIN", "phase": "RE')  # intentionally incomplete

    # Replay must skip the corrupted line and reconstruct state from valid events
    rebuilt = replay(run_dir)

    # State should match what the valid events produce (up to round 1, no_progress=1)
    assert rebuilt.run_id == "r1"
    assert rebuilt.round == 1
    assert rebuilt.no_progress == 1  # one REJECT
    assert rebuilt.tier == "A"
    assert rebuilt.parent_vid == "base"

    # Verify that the corrupted line is indeed corrupted JSON
    with open(events_file, "r") as fh:
        lines = fh.readlines()
    assert not lines[-1].endswith("\n")  # half-line has no newline

    # Try parsing it explicitly to confirm it's invalid
    try:
        json.loads(lines[-1])
        assert False, "Corrupted line should not parse as valid JSON"
    except json.JSONDecodeError:
        pass  # Expected: line is indeed corrupted
