"""出站审查: harness 代发(参数白名单枚举+结果回填) + URL/header/body 熵/编码检测 (IMMUTABLE)。"""
from __future__ import annotations

import copy
import json
import math
import os
import re
from collections import Counter

# ── Thresholds ──────────────────────────────────────────────────────────────
_ENTROPY_QUERY_MAX = 3.5   # URL query-string segment: max Shannon entropy (bits/byte)
_ENTROPY_BODY_MAX = 4.5    # Response/request body: max Shannon entropy
_BODY_SIZE_MAX = 8192      # Outbound body size limit (bytes)
_ENCODED_MIN_LEN = 24      # Minimum suspicious segment length for encoding detection

# Base64 pattern: runs of ≥ _ENCODED_MIN_LEN chars in the B64 alphabet + optional padding
_B64_RE = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % _ENCODED_MIN_LEN)
# Hex pattern: runs of ≥ _ENCODED_MIN_LEN/2 hex byte-pairs (i.e., ≥ _ENCODED_MIN_LEN hex chars)
_HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}){%d,}" % (_ENCODED_MIN_LEN // 2))


# ── Primitives ───────────────────────────────────────────────────────────────

def shannon_entropy(data: bytes | str) -> float:
    """Return Shannon entropy in bits per byte/character."""
    if isinstance(data, str):
        data = data.encode("utf-8", "ignore")
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_encoded(s: str) -> bool:
    """Return True if *s* contains a long high-entropy base64 or hex segment."""
    for m in _B64_RE.finditer(s):
        seg = m.group(0)
        if shannon_entropy(seg) >= 3.5:   # long B64 segment with high entropy
            return True
    for m in _HEX_RE.finditer(s):
        if shannon_entropy(m.group(0)) >= 3.0:
            return True
    return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_text(body) -> str:
    if isinstance(body, (bytes, bytearray)):
        try:
            return bytes(body).decode("utf-8", "ignore")
        except Exception:
            return ""
    return body or ""


# ── screen_request ──────────────────────────────────────────────────────────

def screen_request(method: str, url: str, headers: dict, body) -> dict:
    """Audit an outbound request for covert-channel exfiltration signals.

    Checks:
      - URL query string: Shannon entropy and base64/hex encoding.
      - Body: size limit, entropy, and base64/hex encoding.
      - Headers: base64/hex encoding in values.

    Returns ``{"ok": bool, "violations": [str, ...]}``.
    """
    violations: list[str] = []

    # ── URL query string ──
    query = url.split("?", 1)[1] if "?" in url else ""
    if query:
        if shannon_entropy(query) > _ENTROPY_QUERY_MAX:
            violations.append("url query entropy too high")
        if looks_encoded(query):
            violations.append("url query looks encoded (base64/hex exfil)")

    # ── Body ──
    raw_body: bytes = (
        bytes(body) if isinstance(body, (bytes, bytearray))
        else _as_text(body).encode("utf-8", "ignore")
    )
    if len(raw_body) > _BODY_SIZE_MAX:
        violations.append("body size over limit")
    if raw_body and shannon_entropy(raw_body) > _ENTROPY_BODY_MAX:
        violations.append("body entropy too high")
    body_text = _as_text(body)
    if body_text and looks_encoded(body_text):
        violations.append("body looks encoded (base64/hex exfil)")

    # ── Headers ──
    for hk, hv in (headers or {}).items():
        if isinstance(hv, str):
            if looks_encoded(hv):
                violations.append(f"header {hk} looks encoded")
            if shannon_entropy(hv) > _ENTROPY_BODY_MAX:
                violations.append(f"header {hk} entropy too high")

    return {"ok": not violations, "violations": violations}


# ── dispatch ─────────────────────────────────────────────────────────────────

def dispatch(request_spec: dict, run_dir: str, allowlist: dict, fetcher=None) -> dict:
    """Harness-mediated dispatch: candidate supplies ``kind`` + structured params only.

    The harness:
      1. Validates ``kind`` against the allowlist.
      2. Regex-validates every declared parameter; rejects missing / extra params.
      3. *Builds* the URL itself from ``url_template`` — candidate never sees or
         controls the URL.
      4. Runs ``screen_request`` on the constructed URL as a double-check.
      5. Calls ``fetcher`` (injectable for tests; falls back to ``_real_fetch``).

    Returns ``{"ok": bool, "reason": str, "url"?: str, "result"?: dict}``.
    """
    # Defensive copy: prevent candidate code from mutating allowlist at runtime
    allowlist = copy.deepcopy(allowlist)

    kind = request_spec.get("kind")
    if kind not in allowlist:
        return {"ok": False, "reason": f"kind '{kind}' not in allowlist", "result": None}

    spec = allowlist[kind]
    params = request_spec.get("params") or {}

    # Validate every declared parameter against its regex whitelist
    for name, pattern in spec["params"].items():
        val = params.get(name)
        if val is None or not re.fullmatch(pattern, str(val)):
            return {
                "ok": False,
                "reason": f"param '{name}' missing/failed whitelist regex",
                "result": None,
            }

    # Reject any params not declared in the allowlist (prevent smuggling)
    extra = set(params) - set(spec["params"])
    if extra:
        return {
            "ok": False,
            "reason": f"unexpected params {sorted(extra)}",
            "result": None,
        }

    # Harness builds URL — candidate had no say in construction
    url = spec["url_template"].format(**{k: str(params[k]) for k in spec["params"]})

    # Double-check the constructed URL passes screen_request
    sc = screen_request("GET", url, {}, b"")
    if not sc["ok"]:
        return {"ok": False, "reason": f"screen failed: {sc['violations']}", "result": None}

    f = fetcher if fetcher is not None else _real_fetch
    result = f("GET", url, {}, b"")
    record_outbound(run_dir, kind, params)
    return {"ok": True, "reason": "dispatched", "url": url, "result": result}


def _real_fetch(method: str, url: str, headers: dict, body: bytes) -> dict:  # pragma: no cover
    """Live HTTP fetch — only reachable from harness, never from candidate code."""
    import urllib.request

    req = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return {"status": resp.status, "body": resp.read().decode("utf-8", "ignore")}


# ── Cross-request sequence anomaly detection (M2.9) ─────────────────────────

_SEQ_FILE = "outbound_seq.jsonl"
_FREQ_SPIKE_MAX = 100      # 单 run 单 kind 出站次数上限；超过视为频次突刺
_MONOTONE_RUN_MIN = 6      # 连续单调字典序长度阈；≥此值视为逐字符编码信道


def record_outbound(run_dir: str, kind: str, params: dict) -> None:
    """Append one outbound record to run_dir/outbound_seq.jsonl."""
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, _SEQ_FILE), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "params": params}, sort_keys=True) + "\n")


def _longest_monotone_run(values: list[str]) -> int:
    """Return the length of the longest strictly-increasing (lexicographic) run."""
    if not values:
        return 0
    best = cur = 1
    for i in range(1, len(values)):
        if values[i] > values[i - 1]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def sequence_anomaly(run_dir: str, params_seq_window: int = 32) -> dict:
    """Detect cross-request covert-channel signals in the outbound sequence log.

    Detection signals implemented (做实):
      ① Monotone lexicographic run on any single param across the window
         (consecutive strictly-increasing values = suspected char-by-char encoding).
      ③ Frequency spike: any kind appears more than _FREQ_SPIKE_MAX times in one run.

    Signal ② (param-choice correlation with holdout answer keys) is **not
    implemented** here: sequence_anomaly has no access to answer/label data.
    The interface reserves a "reasons" slot so a caller with answer data can
    inject the check externally. Residual timing/covert channels below the
    heuristic thresholds are acknowledged in the spec (§6 residual risk).

    Returns {"anomalous": bool, "score": float, "reasons": [str, ...]}.
    """
    path = os.path.join(run_dir, _SEQ_FILE)
    if not os.path.exists(path):
        return {"anomalous": False, "score": 0.0, "reasons": []}

    records: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Corrupted line: skip silently (don't crash the anomaly check)
                continue

    reasons: list[str] = []
    score = 0.0

    # ── Signal ③: frequency spike ────────────────────────────────────────────
    by_kind: dict[str, int] = {}
    for r in records:
        k = r.get("kind", "")
        by_kind[k] = by_kind.get(k, 0) + 1
    for k, c in by_kind.items():
        if c > _FREQ_SPIKE_MAX:
            reasons.append(f"frequency spike for kind '{k}': {c} requests (max {_FREQ_SPIKE_MAX})")
            score += 1.0

    # ── Signal ①: monotone lexicographic run on any param ───────────────────
    window = records[-params_seq_window:]
    param_names: set[str] = set()
    for r in window:
        param_names.update((r.get("params") or {}).keys())
    for name in param_names:
        vals = [
            str((r.get("params") or {}).get(name, ""))
            for r in window
            if name in (r.get("params") or {})
        ]
        if len(vals) >= _MONOTONE_RUN_MIN and _longest_monotone_run(vals) >= _MONOTONE_RUN_MIN:
            reasons.append(
                f"monotone lexicographic sequence on param '{name}' "
                f"(suspected encoding channel, run>={_MONOTONE_RUN_MIN})"
            )
            score += 1.0

    return {"anomalous": bool(reasons), "score": score, "reasons": reasons}
