"""统一 agent 调用层 + 异质交叉校验原语。

把"调一个 agent"与"用另一家族交叉校验"抽象成可在**任何阶段**复用的函数，使 codex 成为
全流程可选的异质 agent，而非 C 档判官专属组件。任何模块（reflect/propose/patch-review/
evaluate）都可：
  - invoke(prompt, family="codex", ...)            # 在该阶段调一个指定家族的 agent
  - cross_check(prompt, families=("claude","codex"))# 同一任务跑多家族 → 比对一致性/分歧

铁律1 不变: 这些是"搜索/反思/评审"用途的 agent 调用; 采纳/拒绝仍由确定性 acceptor 裁决,
绝不让 agent 裁决自己的产出。所有调用失败均 graceful（ok=False / None），绝不抛。
"""
from __future__ import annotations
import json
import subprocess
from .model_boundary import load_runtime, metadata

VALID_FAMILIES = ("claude", "cc", "codex")


def codex_available(timeout_s: int = 20) -> bool:
    """跑前预检: codex CLI 是否可调（`codex --version` exit 0）。

    dual 默认开启需要 codex；缺失则上层提醒 + 自动降级单跑。轻量探针（不发真请求）。
    """
    try:
        proc = subprocess.run(
            ["codex", "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", shell=True, timeout=timeout_s,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def preflight_dual(dual_requested: bool) -> tuple[bool, str | None]:
    """据 codex 可用性决定有效 dual 模式 + 提醒文案。

    Returns (effective_dual, warning):
      - dual 请求 + codex 可用 → (True, None)
      - dual 请求 + codex 不可用 → (False, 提醒)  # 自动降级单跑, 不硬失败
      - 未请求 dual → (False, None)
    """
    if not dual_requested:
        return False, None
    if codex_available():
        return True, None
    return False, ("⚠ codex 不可用（`codex --version` 失败）→ 已自动降级为单家族（claude）。"
                   "每阶段 codex&claude 双重校验已关闭。修复 codex 或显式用 --single 静默单跑。")


def invoke(prompt: str, family: str | None = None, *, model: str | None = None,
           tools: str | None = None, effort: str | None = None,
           role: str | None = None, timeout_s: float = 600, chain=None,
           avoid=None, cwd=None, env=None) -> dict:
    """One read-only llmcall request; family filters the inherited route order.

    The returned model family must confirm an explicit family request. Omitted
    family/model/effort inherit controller policy. No output repair or business retry.
    """
    failure = {"ok": False, "result": "", "family": family, "model_family": None,
               "outcome": "invalid_request", "effects": "none", "execution_started": False,
               "review_state": "not_requested", "call_id": None}
    if family is not None and family not in VALID_FAMILIES:
        return dict(failure, error="unsupported family")
    if tools not in (None, "web_search"):
        return dict(failure, error="unsupported tool constraint")
    kwargs = {}
    for key, value in (("chain", chain), ("avoid", avoid), ("cwd", cwd), ("env", env)):
        if value is not None:
            kwargs[key] = value
    if effort is not None:
        kwargs["effort"] = effort
    try:
        runtime = load_runtime()
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        return dict(failure, outcome="dependency_unavailable", effects="none",
                    execution_started=False, review_state="not_requested", call_id=None,
                    error="Model use requires llmcall with ModelSelection.family and execution contracts: "
                          + type(exc).__name__)
    expected = "claude" if family == "cc" else family
    try:
        result = runtime.call(
            prompt, mode="agent", timeout=timeout_s,
            selection=runtime.ModelSelection("exact" if model else "inherit", model, family=expected),
            requirements=runtime.ExecutionRequirements(
                workspace=cwd,
                access="read_only", tool_network="required" if tools else "forbidden",
                required_tools=("WebSearch",) if tools else (),
                tool_allowlist=("WebSearch",) if tools else (), replay="never_after_start"),
            **kwargs)
    except Exception as exc:
        return dict(failure, error="llmcall failed: " + type(exc).__name__,
                    outcome="execution_uncertain", effects="possible", execution_started=None,
                    review_state="unavailable", call_id=None)
    if not isinstance(result, runtime.Result) or not isinstance(result.text, str):
        return dict(failure, error="llmcall returned an invalid Result; no retry",
                    outcome="execution_uncertain", effects="possible", execution_started=None)
    details = metadata(result)
    if (not result or result.error or not result.text.strip()
            or result.outcome not in (None, "success")):
        return dict(failure, **{**details, "error": result.error or "empty or unsuccessful output"})
    actual = result.model_family
    if family and (actual != expected
                   or result.model_source != "provider_reported"):
        return {**failure, **details, "error": "requested model family unverified",
                "outcome": "model_unverified"}
    return {**details, "ok": True, "result": result.text, "family": family or actual}


def _extract_json(text: str):
    """从 agent 文本里抽第一个 JSON 对象（agent 常包裹散文）。失败 → None。"""
    try:
        i, j = text.index("{"), text.rindex("}")
        return json.loads(text[i:j + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def cross_check(prompt: str, families=("claude", "codex"), *,
                tools: str | None = None, timeout_s: int = 600) -> dict:
    """同一任务交给多个**异质**家族独立做 → 收集各自结果 + 比对。

    这是贯穿全流程的异质交叉校验原语: 任何阶段都能"再叫一个不同家族复核一遍"。
    Returns:
      {
        "per": {family: {"ok","result"}},   # 各家族原始结果
        "n_ok": int,                          # 成功家族数
        "results_ok": [str, ...],             # 成功家族的文本
        "heterogeneous": bool,                # 是否 ≥2 个不同家族都成功（真交叉校验成立）
      }
    判断"是否一致/分歧"由调用方按角色解释（如 judges.pairwise_agreement 比对分数；
    review 比对 verdict）。本原语只负责"异质地各跑一遍并收齐"。
    """
    per: dict[str, dict] = {}
    for fam in families:
        r = invoke(prompt, family=fam, tools=tools, timeout_s=timeout_s)
        per[fam] = r
    ok_fams = [f for f, v in per.items() if v["ok"]]
    return {
        "per": per,
        "n_ok": len(ok_fams),
        "results_ok": [per[f]["result"] for f in ok_fams],
        "heterogeneous": len({per[f]["model_family"] for f in ok_fams if per[f]["model_family"]}) >= 2,
    }


def cross_check_verdicts(prompt: str, families=("claude", "codex"),
                         timeout_s: int = 600) -> dict:
    """cross_check 的"评审"特化: 期望各家族返回 JSON {verdict, notes}。

    Returns {"verdicts": {family: "accept"|"reject"|"abstain"|None},
             "agree": bool|None,   # 所有成功家族 verdict 是否一致（<2 成功 → None）
             "n_ok": int, "raw": <cross_check 原始>}。
    仅为参考信号; 最终裁决仍归确定性 acceptor（铁律1）。
    """
    cc = cross_check(prompt, families, timeout_s=timeout_s)
    verdicts: dict[str, str | None] = {}
    for fam, v in cc["per"].items():
        if not v["ok"]:
            verdicts[fam] = None
            continue
        obj = _extract_json(v["result"]) or {}
        ver = obj.get("verdict")
        verdicts[fam] = ver if ver in ("accept", "reject", "abstain") else None
    got = [x for x in verdicts.values() if x is not None]
    agree = (len(set(got)) == 1) if len(got) >= 2 else None
    return {"verdicts": verdicts, "agree": agree, "n_ok": cc["n_ok"], "raw": cc}
