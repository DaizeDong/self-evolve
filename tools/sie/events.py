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
    # ACCEPT 语义: 清零 no_progress 和 forced_review(单一来源)
    if ev.get("type") == "ACCEPT":
        patch["no_progress"] = 0
        patch["forced_review"] = 0
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
            rs = _apply(rs, json.loads(line))
    return rs
