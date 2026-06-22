from __future__ import annotations
import json, os, time, uuid

PENDING = "pending_actions.jsonl"

_TERMINAL_STATUSES = {"approved", "skipped", "expired"}


def enqueue(run_dir: str, action: dict) -> str:
    """Append a pending-action record and return its aid. Non-blocking."""
    os.makedirs(run_dir, exist_ok=True)
    aid = uuid.uuid4().hex[:12]
    rec = {
        "aid": aid,
        "kind": "request",
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


def _read_all(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, PENDING)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Corrupted/half-written line: skip silently (don't break pending action lookup)
                continue
    return out


def pending(run_dir: str) -> list[dict]:
    """Return request records whose latest known status is still 'pending' and ttl not exceeded."""
    now = time.time()
    # Collect the original request record and the latest-seen status for each aid
    requests: dict[str, dict] = {}   # aid -> original request record
    latest_status: dict[str, str] = {}  # aid -> most-recent status string

    for rec in _read_all(run_dir):
        aid = rec.get("aid", "")
        if rec.get("kind") == "request":
            requests[aid] = rec
        # Both "request" and "resolution" rows carry a status field
        if "status" in rec:
            latest_status[aid] = rec["status"]

    out = []
    for aid, req in requests.items():
        if latest_status.get(aid) != "pending":
            continue
        created_at = req.get("created_at", now)
        ttl = req.get("ttl", 86400)
        if ttl <= 0 or (now - created_at) >= ttl:
            continue  # expired
        out.append(req)
    return out


def resolve(run_dir: str, aid: str, status: str) -> None:
    """Append a resolution row (approved/skipped/expired). Append-only; never rewrites history."""
    if status not in _TERMINAL_STATUSES:
        raise ValueError(f"resolve status must be one of {_TERMINAL_STATUSES}, got {status!r}")
    rec = {
        "aid": aid,
        "kind": "resolution",
        "status": status,
        "resolved_at": time.time(),
    }
    with open(os.path.join(run_dir, PENDING), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")  # append-only
