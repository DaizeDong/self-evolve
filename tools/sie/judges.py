"""Judge orchestration: prompt construction + span scoring + family routing.

Exports:
  build_judge_prompt(artifact_text, spans) -> str
      Iron rule 5: prompt carries ONLY span text — never claim/verified/
      marginal_gain/expected values.  Tested by test_prompt_carries_no_truth.

  score(artifact_path, anchors_visible, family) -> dict
      Routes to judge_codex or judge_claude; aggregates span_scores;
      degrades gracefully when judge is unavailable.

Return schema:
  {
    "family": str,
    "available": bool,
    "span_scores": [{"span": str, "score": float}, ...],
    "aggregate": float,       # mean over returned span_scores (0.0 if none)
    "unspanned_penalized": int,  # #spans not scored by judge (no padding)
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from tools.sie import judge_codex, judge_claude


def build_judge_prompt(artifact_text: str, spans: list[str]) -> str:
    """Build the judge prompt.

    Iron rule 5 (immutable): prompt MUST NOT carry any ground-truth fields —
    specifically: claim, verified, marginal_gain, expected, source_url, or
    any numeric tolerance value.  Only the span text strings themselves are
    included.  Tested by test_prompt_carries_no_truth.
    """
    span_block = "\n".join(f"- {s}" for s in spans)
    return (
        "You are an impartial judge. Score ONLY the assertions tied to the "
        "verifiable spans below. Assertions with NO verifiable span get zero or "
        "negative weight. Do not reward length. Return JSON: "
        '{"span_scores":[{"span":..., "score":0..1}]}.\n\n'
        f"ARTIFACT:\n{artifact_text}\n\nSPANS TO JUDGE:\n{span_block}\n"
    )


def _parse_span_scores(raw: str, spans: list[str]) -> dict:
    """Extract span_scores from judge raw output; degrade gracefully on parse error.

    If raw is not parseable JSON or lacks span_scores, returns empty list with
    aggregate=0.0 and unspanned_penalized=len(spans).  No exception is raised.
    """
    try:
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        ss = obj.get("span_scores", [])
    except (ValueError, json.JSONDecodeError):
        ss = []
    valid = [
        x for x in ss
        if isinstance(x, dict) and "span" in x and "score" in x
        and isinstance(x["score"], (int, float))
    ]
    agg = sum(float(x["score"]) for x in valid) / len(valid) if valid else 0.0
    # Unspanned penalty: spans the judge did not score get no credit.
    # len(spans) - len(valid) reflects spans missing from judge output.
    return {
        "span_scores": valid,
        "aggregate": agg,
        "unspanned_penalized": max(0, len(spans) - len(valid)),
    }


def score(artifact_path: str, anchors_visible: list[dict], family: str) -> dict:
    """Score an artifact against visible anchors using the specified judge family.

    Args:
        artifact_path: Path to the artifact file (UTF-8 text).
        anchors_visible: List of anchor dicts; only ``span`` field is used.
        family: Judge family, one of {"codex", "claude"}.

    Returns:
        Result dict with keys: family, available, span_scores, aggregate,
        unspanned_penalized.  When available=False, aggregate=0.0 and
        unspanned_penalized=len(spans).
    """
    artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    spans = [a.get("span", "") for a in anchors_visible if a.get("span")]
    prompt = build_judge_prompt(artifact_text, spans)

    if family == "codex":
        res = judge_codex.invoke_codex_judge(prompt, timeout_s=600)
    elif family == "claude":
        res = judge_claude.invoke_claude_judge(prompt, timeout_s=600)
    else:
        raise ValueError(f"unknown judge family: {family!r}")

    if not res.get("available"):
        return {
            "family": family,
            "available": False,
            "span_scores": [],
            "aggregate": 0.0,
            "unspanned_penalized": len(spans),
        }

    parsed = _parse_span_scores(res["raw"], spans)
    parsed.update({"family": family, "available": True})
    return parsed


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
