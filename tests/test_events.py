import os
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
