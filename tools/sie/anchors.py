"""B 档锚: 抽取/核查/EVE 边际增益/visible-holdout/去相关 (IMMUTABLE 裁决码)."""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timezone

_REQUIRED_ANCHOR_KEYS = ("claim", "span", "source_url")


def _anchor_id(raw: dict) -> str:
    key = f"{raw.get('claim','')}|{raw.get('span','')}|{raw.get('source_url','')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def extract_anchors(artifact_path: str) -> list[dict]:
    with open(artifact_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    out: list[dict] = []
    seen: set[str] = set()
    for section in doc.get("sections", []):
        for raw in section.get("anchors", []):
            if not all(k in raw and raw[k] for k in _REQUIRED_ANCHOR_KEYS):
                continue  # 字段不全的不算锚 (代码判定, 不信任 prose)
            aid = _anchor_id(raw)
            if aid in seen:
                continue
            seen.add(aid)
            out.append({
                "anchor_id": aid,
                "claim": raw["claim"],
                "span": raw["span"],
                "source_url": raw["source_url"],
                "metric": raw.get("metric"),
                "expected": raw.get("expected"),
                "cik": raw.get("cik"),
                "period": raw.get("period"),
                "fetched_at": None,
                "verified": False,
                "marginal_gain": 0.0,
            })
    return out


def coverage(anchors: list[dict]) -> float:
    if not anchors:
        return 0.0
    total = sum(max(len(a.get("span") or ""), 1) for a in anchors)
    done = sum(max(len(a.get("span") or ""), 1) for a in anchors if a.get("verified"))
    return done / total if total else 0.0
