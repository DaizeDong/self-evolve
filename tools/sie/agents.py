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

VALID_FAMILIES = ("claude", "cc", "codex")


def invoke(prompt: str, family: str = "claude", *, model: str | None = None,
           tools: str | None = None, effort: str | None = None,
           role: str | None = None, timeout_s: int = 600) -> dict:
    """在任一阶段调用任一家族的 agent。

    family: "claude"|"cc"(走 cc→claude) | "codex". role 仅信息性。
    Returns {"ok": bool, "result": str, "family": str}. 失败 → ok=False（不抛）。
    """
    if family not in VALID_FAMILIES:
        return {"ok": False, "result": "", "family": family}
    cmd = ["node", "workflows/agent.js", "--family", family]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--tools", tools]
    if effort:
        cmd += ["--effort", effort]
    if role:
        cmd += ["--role", role]
    try:
        proc = subprocess.run(
            cmd, input=prompt or "", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"ok": False, "result": "", "family": family}
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return {"ok": False, "result": "", "family": family}
    return {"ok": True, "result": proc.stdout, "family": family}


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
        per[fam] = {"ok": r["ok"], "result": r["result"]}
    ok_fams = [f for f, v in per.items() if v["ok"]]
    return {
        "per": per,
        "n_ok": len(ok_fams),
        "results_ok": [per[f]["result"] for f in ok_fams],
        "heterogeneous": len({f for f in ok_fams}) >= 2,
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
