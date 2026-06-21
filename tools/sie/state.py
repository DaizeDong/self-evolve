from __future__ import annotations
import json, os
from dataclasses import dataclass, asdict, fields

STATE_FILE = "state.json"


@dataclass
class RunState:
    run_id: str
    phase: str
    round: int
    parent_vid: str | None
    tier: str  # "A"|"B"|"C"|叠加如"A+B"
    no_progress: int = 0
    static_reject: int = 0
    forced_review: int = 0
    continue_count: int = 0
    drift_count: int = 0


def save_state(rs: RunState, run_dir: str) -> None:
    os.makedirs(run_dir, exist_ok=True)
    final = os.path.join(run_dir, STATE_FILE)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(asdict(rs), fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)  # 原子 rename(Win/Posix 均原子)


def load_state(run_dir: str) -> RunState:
    with open(os.path.join(run_dir, STATE_FILE), "r", encoding="utf-8") as fh:
        data = json.load(fh)
    allowed = {f.name for f in fields(RunState)}
    return RunState(**{k: v for k, v in data.items() if k in allowed})
