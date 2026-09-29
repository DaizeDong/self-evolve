"""Judge prompts, validated span evidence, actual-provider metadata, and calibration.

Scores are bounded to [0, 1]. Missing spans contribute zero to the aggregate;
malformed or empty evidence is unavailable. Requested aliases do not select a
provider or prove independent judgment.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from tools.sie import judge_codex, judge_claude
from tools.sie import llm_adapter


def build_judge_prompt(artifact_text: str, spans: list[str]) -> str:
    """Build the judge prompt.

    Iron rule 5 (immutable): prompt MUST NOT carry any ground-truth fields —
    specifically: claim, verified, marginal_gain, expected, source_url, or
    any numeric tolerance value.  Only the span text strings themselves are
    included.  Tested by test_prompt_carries_no_truth.
    """
    try:
        artifact_text = json.dumps(llm_adapter.strip_truth(json.loads(artifact_text), judge=True),
                                   ensure_ascii=False)
    except (ValueError, TypeError):
        if artifact_text.lstrip().startswith(("{", "[")):
            raise ValueError("malformed structured artifact; truth exclusion cannot be established")
    span_block = "\n".join(f"- {s}" for s in spans)
    return (
        "You are an impartial judge. Score ONLY the assertions tied to the "
        "verifiable spans below. Assertions with NO verifiable span get zero or "
        "negative weight. Do not reward length. Return JSON: "
        '{"span_scores":[{"span":..., "score":0..1}]}.\n\n'
        f"ARTIFACT:\n{artifact_text}\n\nSPANS TO JUDGE:\n{span_block}\n"
    )


def _parse_span_scores(raw: str, spans: list[str]) -> dict:
    """Reject invalid evidence; omitted spans receive zero in the aggregate."""
    expected = set(spans)
    unavailable = {"available": False, "span_scores": [], "aggregate": 0.0,
                   "unspanned_penalized": len(expected), "error": "invalid or empty judge evidence"}
    obj = llm_adapter.parse_object(raw)
    entries = obj.get("span_scores") if obj is not None else None
    if not expected or not isinstance(entries, list) or not entries:
        return unavailable
    seen = set()
    valid = []
    for item in entries:
        if not isinstance(item, dict):
            return unavailable
        span, value = item.get("span"), item.get("score")
        if (not isinstance(span, str) or span not in expected or span in seen
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 <= value <= 1 or not math.isfinite(value)):
            return unavailable
        seen.add(span)
        valid.append({"span": span, "score": float(value)})
    return {"available": True, "span_scores": valid,
            "aggregate": sum(item["score"] for item in valid) / len(expected),
            "unspanned_penalized": len(expected - seen), "error": None}


def score(artifact_path: str, anchors_visible: list[dict], family: str, *,
          avoid: str | None = None) -> dict:
    """Score an artifact against visible spans using current llmcall judge policy.

    Args:
        artifact_path: Path to the artifact file (UTF-8 text).
        anchors_visible: List of anchor dicts; only ``span`` field is used.
        family: Legacy entrypoint alias. Returned family comes from actual provider metadata.
        avoid: Optional actual provider to avoid for an independent second opinion.

    Returns:
        Result dict with keys: family, available, span_scores, aggregate,
        unspanned_penalized.  When available=False, aggregate=0.0 and
        unspanned_penalized=len(spans).
    """
    if family not in ("codex", "codexg", "claude", "cc"):
        raise ValueError(f"unknown judge family: {family!r}")
    spans = list(dict.fromkeys(a["span"] for a in anchors_visible if isinstance(a, dict)
                 and isinstance(a.get("span"), str) and a["span"].strip()))
    unavailable = {"family": None, "requested_family": family, "provider": None,
                   "attempts": [], **_parse_span_scores("", spans)}
    try:
        artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {**unavailable, "error": f"artifact unavailable: {type(exc).__name__}"}
    if not artifact_text.strip() or not spans:
        return {**unavailable, "error": "empty artifact or scoring evidence"}
    try:
        prompt = build_judge_prompt(artifact_text, spans)
    except ValueError as exc:
        return {**unavailable, "error": str(exc)}
    invoke = (judge_codex.invoke_codex_judge if family in ("codex", "codexg")
              else judge_claude.invoke_claude_judge)
    kwargs = {"avoid": avoid} if avoid else {}
    res = invoke(prompt, timeout_s=600, **kwargs)
    metadata = {key: res.get(key) for key in ("provider", "family", "attempts")}
    metadata.update({key: res[key] for key in llm_adapter.POLICY_FIELDS if key in res})
    metadata["requested_family"] = family
    if not res.get("available"):
        return {**unavailable, **metadata, "error": res.get("error") or "judge unavailable"}
    return {**_parse_span_scores(res.get("raw", ""), spans), **metadata}


# ── M3.2: 位置/长度去偏 + 判官一致性度量 ──────────────────────────────────

def debias_order(scores: dict) -> dict:
    """位置/长度去偏：按 span 文本排序消除呈现顺序影响。

    返回 scores 的浅拷贝，其中 span_scores 按 span 文本升序排列。

    位置去偏：按 span 文本升序排列，消除呈现顺序对打分的影响。
    长度去偏：委托给 judge prompt（prompt 中写明 "Do not reward length"），
    本函数不做分值缩放，避免引入新的缩放偏差。
    """
    ss = sorted(scores.get("span_scores", []), key=lambda x: x["span"])
    out = dict(scores)
    out["span_scores"] = ss
    return out


def pairwise_agreement(scores_a: dict, scores_b: dict) -> Optional[float]:
    """两判官按 span 对齐的配对一致性。

    Returns α∈[0,1], or None if either judge unavailable.

    算法：
      1. 任一判官不可用 → 返回 None（调用方须先检查 None 再使用值，
         防止将不可用状态误作真实低一致性分）。
      2. 按 span 文本对齐两判官打分（各自先经 debias_order 排序）。
      3. 取两判官共同覆盖的 span 集合（inner join）；无共同 span → 0.0。
      4. α = 1 − MAD（平均绝对差），分值在 [0,1] 故 MAD∈[0,1]，α∈[0,1]。
         α=1 表示完全一致；α→0 表示高度不一致（异质合谋检测用）。

    注：缺失 span（一方有另一方无）不纳入计算，保守处理：
    共同覆盖少时 α 置信度低，后续调用方可结合覆盖率降权。
    """
    if not scores_a.get("available") or not scores_b.get("available"):
        return None
    a = {x["span"]: float(x["score"]) for x in debias_order(scores_a)["span_scores"]}
    b = {x["span"]: float(x["score"]) for x in debias_order(scores_b)["span_scores"]}
    common = set(a) & set(b)
    if not common:
        return 0.0
    mad = sum(abs(a[s] - b[s]) for s in common) / len(common)
    return max(0.0, 1.0 - mad)  # 分在 [0,1]，故 1-MAD 即配对一致性


# ── M3.3: judge↔锚校准（独立 holdout 标注集）─────────────────────────────────

from tools.sie import anchors as _anchors  # noqa: E402, placed after M3.2 block

_CALIB_MIN_INDEP = 4  # 有效独立 holdout 锚下限；低于此校准不可信


def calibrate_judge_anchor(judge_scores: dict, holdout_anchors: list[dict]) -> dict:
    """Judge↔锚 Pearson 相关校准（只接 holdout 锚，严禁混入 visible 锚）。

    铁律：holdout_anchors 必须是**不进 e-process 的独立 holdout / 人审标注集**。
    若将 visible（e-process 计分用）锚传入，judge 与计分锚同源，
    相关性虚高，合谋检测失效——调用方有责任隔离。

    算法：
      1. 按 span 对齐 judge_scores 与 holdout_anchors（inner join）。
      2. 对配对后的 holdout 子集调用 effective_independent_count 做同源去相关，
         得到有效独立锚数 indep。
      3. 若 paired < 2 或 indep < _CALIB_MIN_INDEP → degenerate=True（校准不可信）。
      4. 计算 Pearson 相关（judge score vs holdout verified 0/1）；
         任一方差为 0 → degenerate=True。
      5. 返回 {"corr": float, "n_used": int, "degenerate": bool}。

    Args:
        judge_scores: score() 返回的 dict，含 "span_scores" 列表。
        holdout_anchors: 独立 holdout 锚列表，每项含 "span"/"verified"/"source_url"
                         字段（与 anchors.py 同结构）。

    Returns:
        {"corr": float, "n_used": int, "degenerate": bool}
    """
    # 1. 按 span 对齐（inner join）
    by_span = {x["span"]: float(x["score"])
               for x in judge_scores.get("span_scores", [])}
    paired_anchors = [a for a in holdout_anchors if a.get("span") in by_span]
    paired = [(by_span[a["span"]], 1.0 if a.get("verified") else 0.0)
              for a in paired_anchors]
    n = len(paired)

    # 2. 同源去相关：只对配对后的子集计算有效独立锚数
    indep = _anchors.effective_independent_count(paired_anchors)

    # 3. 可信性闸：配对数或有效独立锚不足 → degenerate
    if n < 2 or indep < _CALIB_MIN_INDEP:
        return {"corr": 0.0, "n_used": n, "degenerate": True}

    # 4. Pearson 相关
    xs = [p[0] for p in paired]
    ys = [p[1] for p in paired]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in paired)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return {"corr": 0.0, "n_used": n, "degenerate": True}
    corr = cov / (vx ** 0.5 * vy ** 0.5)
    return {"corr": float(corr), "n_used": n, "degenerate": False}
