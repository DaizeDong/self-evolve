import json, os
from tools.sie.state import RunState, save_state, load_state

def test_roundtrip(tmp_path):
    rs = RunState(run_id="r1", phase="PROFILE", round=2, parent_vid=None, tier="A",
                  no_progress=1, static_reject=0, forced_review=3, continue_count=2, drift_count=1)
    save_state(rs, str(tmp_path))
    back = load_state(str(tmp_path))
    assert back == rs

def test_atomic_no_tmp_left(tmp_path):
    rs = RunState(run_id="r1", phase="INIT", round=0, parent_vid="base", tier="C")
    save_state(rs, str(tmp_path))
    # 落盘后不应残留 tmp 文件
    leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert leftovers == []
    assert os.path.exists(os.path.join(tmp_path, "state.json"))

def test_stale_tmp_does_not_affect_load(tmp_path):
    """Verify that load_state only reads state.json and ignores stale .tmp files.

    Note: True mid-write atomicity is ensured by os.replace() semantics, not by this test.
    """
    rs1 = RunState(run_id="r1", phase="INIT", round=0, parent_vid=None, tier="A")
    save_state(rs1, str(tmp_path))
    # 写一个损坏的 tmp 不应影响已有 state.json
    with open(os.path.join(tmp_path, "state.json.tmp"), "w") as fh:
        fh.write("{ broken")
    back = load_state(str(tmp_path))
    assert back == rs1
