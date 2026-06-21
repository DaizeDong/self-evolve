"""B 档锚: 抽取/核查/EVE 边际增益/visible-holdout/去相关 (IMMUTABLE 裁决码)."""
from __future__ import annotations
import json
import hashlib
import math
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import edgar_cache

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
    total = sum(len(a.get("span") or "") for a in anchors)
    done = sum(len(a.get("span") or "") for a in anchors if a.get("verified"))
    return done / total if total else 0.0


def _source_cluster_key(a: dict) -> tuple:
    """生成同源聚类键：(host, cik, period)。

    host 从 source_url 提取，去掉 www. 前缀后小写。
    """
    host = ""
    try:
        host = (urlparse(a.get("source_url") or "").hostname or "").lower()
    except Exception:
        host = ""
    # host 主域 (去 www.) + cik + period 同 => 同源簇
    if host.startswith("www."):
        host = host[4:]
    return (host, str(a.get("cik") or ""), str(a.get("period") or ""))


def effective_independent_count(anchors: list[dict]) -> int:
    """按同源聚类计算有效独立锚数。

    聚类维度：source_url host(去www) + cik + period
    折算规则：每簇 floor(1 + log2(簇内规模))，各簇求和向下取整。

    例如：8 个同源锚 -> 1 + log2(8) = 1 + 3 = 4，防相关锚虚高 e-value。
    仅计数 verified=True 的锚。
    """
    clusters: dict[tuple, int] = {}
    for a in anchors:
        if not a.get("verified"):
            continue
        k = _source_cluster_key(a)
        clusters[k] = clusters.get(k, 0) + 1
    eff = 0
    for size in clusters.values():
        # 同源簇内信息次线性: 1 + log2(size), 向下取整
        eff += int(math.floor(1.0 + math.log2(size)))
    return eff


def split_visible_holdout(anchors: list[dict], frac: float, seed: str = "") -> tuple[list, list]:
    """Deterministic holdout split for anchor sets.

    Splits anchors into visible and holdout sets. Holdout size is round(frac*N).
    Split is deterministic and reproducible: same anchor list + same seed always
    produces identical holdout. Prevents "luck" in holdout retries when
    checking for cumulative drift.

    Args:
        anchors: List of anchor dicts with "anchor_id" field.
        frac: Holdout fraction in [0, 1]; clamped if outside range.
        seed: String seed for reproducible hashing (default "").

    Returns:
        (visible, holdout): Two lists partitioning anchors (disjoint, union=all).
    """
    if not anchors:
        return [], []
    frac = max(0.0, min(1.0, float(frac)))
    n_hold = int(round(frac * len(anchors)))

    def _rank(a: dict) -> str:
        """Hash-based rank for deterministic ordering."""
        return hashlib.sha256((seed + "|" + str(a.get("anchor_id", ""))).encode("utf-8")).hexdigest()

    ordered = sorted(anchors, key=_rank)
    holdout = ordered[:n_hold]
    hold_ids = {a["anchor_id"] for a in holdout}
    visible = [a for a in anchors if a["anchor_id"] not in hold_ids]
    return visible, holdout


# ---------------------------------------------------------------------------
# M2.4: verify_anchor — EDGAR-backed factual verification
# ---------------------------------------------------------------------------

_REL_TOL = 0.01   # 1% relative tolerance
_ABS_TOL = 0.01   # absolute tolerance for near-zero anchors (|expected| < 1)


def _default_fetcher(anchor: dict) -> float | None:
    """Production path: use edgartools to fetch anchor.metric @ cik/period.

    Lazily imports edgar (inside fetcher=None branch) so the default test
    suite never imports or loads edgar, keeping tests network-free.
    WinError 145 is pre-empted by prepare_cache before any edgar call.
    """
    edgar_cache.prepare_cache(None)
    from edgar import Company  # lazy: ImportError -> unverified via caller's except
    comp = Company(str(anchor["cik"]))
    facts = comp.get_facts()
    return float(facts.get_fact(anchor["metric"], period=anchor.get("period")))


def _within_tol(observed: float, expected: float) -> bool:
    """Return True if observed is within tolerance of expected.

    Uses relative tolerance when |expected| >= 1, otherwise falls back to
    absolute tolerance (handles cash=0 / near-zero anchors).
    """
    denom = abs(expected)
    if denom < 1.0:
        return abs(observed - expected) <= _ABS_TOL
    return abs(observed - expected) / denom <= _REL_TOL


def verify_anchor(anchor: dict, fetcher=None) -> dict:
    """Verify one anchor's factual claim against an external truth source.

    Returns a *copy* of the anchor dict with four additional keys:
      - verified (bool): True iff fetched value is within tolerance
      - fetched_at (str): ISO-8601 UTC timestamp of this verification attempt
      - observed (float | None): value returned by fetcher, or None on failure
      - verify_reason (str): human-readable outcome description

    Args:
        anchor: Anchor dict with at least ``expected``, ``cik``, ``period``,
                ``metric`` keys for numeric verification.
        fetcher: Optional callable(anchor) -> float | None.  If None, uses the
                 real edgartools path (lazy import; requires network).
                 Inject a fake fetcher in tests to avoid all network calls.
    """
    out = dict(anchor)
    out["fetched_at"] = datetime.now(timezone.utc).isoformat()

    f = fetcher if fetcher is not None else _default_fetcher
    try:
        observed = f(anchor)
    except Exception as exc:
        # Fetch failure -> unverified. Never treat unavailable data as truthy.
        out["verified"] = False
        out["observed"] = None
        out["verify_reason"] = f"fetch error: {exc!r}"
        return out

    out["observed"] = observed

    exp = anchor.get("expected")
    if observed is None or exp is None:
        out["verified"] = False
        out["verify_reason"] = "missing observed/expected"
        return out

    ok = _within_tol(float(observed), float(exp))
    out["verified"] = bool(ok)
    out["verify_reason"] = "within tol" if ok else "outside tol"
    return out
