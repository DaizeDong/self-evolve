from __future__ import annotations
import json, os
from dataclasses import replace
from tools.sie.state import RunState

EVENTS_FILE = "events.jsonl"


def append_event(run_dir: str, event: dict) -> None:
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, EVENTS_FILE), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# 直接覆盖的标量字段
_DIRECT = ("run_id", "phase", "round", "parent_vid", "tier")


def _apply(rs: RunState, ev: dict) -> RunState:
    patch: dict = {}
    for k in _DIRECT:
        if k in ev:
            patch[k] = ev[k]
    # 计数器只能通过 _delta/_reset 后缀或 ACCEPT 语义修改，事件里直接写计数器字段会被忽略
    for cnt in ("no_progress", "static_reject", "forced_review",
                "continue_count", "drift_count"):
        d = ev.get(f"{cnt}_delta")
        if d is not None:  # 允许 delta=0 的合法增量
            patch[cnt] = getattr(rs, cnt) + d
        # 非 ACCEPT 事件的显式 reset 机制
        if ev.get(f"{cnt}_reset") and ev.get("type") != "ACCEPT":
            patch[cnt] = 0
    # ACCEPT 语义: 清零 no_progress / forced_review / continue_count (spec §4 态8)
    if ev.get("type") == "ACCEPT":
        patch["no_progress"] = 0
        patch["forced_review"] = 0
        patch["continue_count"] = 0
    # Reaching the acceptor at all clears static_reject, whichever way it then decided.
    #
    # THIS IS THE ONLY PLACE THE RESET CAN LIVE. It was first written into
    # statemachine.apply_acceptor_outcome, as a mutation of the in-memory RunState, and it did
    # nothing at all: _step appends the event and then REPLAYS the whole log to rebuild the state,
    # so the reducer is the authority and the in-memory object is discarded a line later. 650 tests
    # passed and a live 13 round run still blew the fuse with static_reject=6 after two accepts that
    # should each have zeroed it. The test that was supposed to guard the change called
    # apply_acceptor_outcome directly, so it verified the layer that does not decide anything.
    #
    # The fuse asks one question: is the proposer producing NOTHING? A round that got a proposal
    # through the patch gate and into evaluation has answered no, even when the evidence then
    # rejected the change. Counting only upward made its budget of 6 a ceiling on total barren
    # rounds for the LIFETIME of a run, whatever --max-rounds said.
    if ev.get("type") in ("ACCEPT", "REJECT"):
        patch["static_reject"] = 0
    return replace(rs, **patch)


def replay(run_dir: str) -> RunState:
    rs = RunState(run_id="", phase="INIT", round=0, parent_vid=None, tier="")
    path = os.path.join(run_dir, EVENTS_FILE)
    if not os.path.exists(path):
        return rs
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rs = _apply(rs, json.loads(line))
            except json.JSONDecodeError:
                # Corrupted/half-written line (crashed mid-append): skip silently
                # (crash-replay invariant: events.jsonl is source of truth, incomplete
                # events are never fully committed and should not affect state reconstruction)
                continue
    return rs
