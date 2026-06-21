from __future__ import annotations
import json, os, time, uuid

PENDING = "pending_actions.jsonl"


def enqueue(run_dir: str, action: dict) -> str:
    os.makedirs(run_dir, exist_ok=True)
    aid = uuid.uuid4().hex[:12]
    rec = {
        "aid": aid,
        "run_id": action.get("run_id", ""),
        "round": action.get("round", 0),
        "action_type": action.get("action_type", "unknown"),
        "payload": action.get("payload", {}),
        "created_at": time.time(),
        "status": "pending",
        "ttl": action.get("ttl", 86400),
    }
    with open(os.path.join(run_dir, PENDING), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return aid  # 非阻塞: 立即返回, 不等人


def pending(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, PENDING)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("status") == "pending":
                    out.append(rec)
    return out
