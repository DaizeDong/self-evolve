"""Codex judge 适配：走 codex skill 最强模型；禁 browser/playwright，只用 web_search。
judge 与 candidate 物理隔离；prompt 无真值；出站纳入审查。
不可用（限速/故障/超时/退出码非 0）→ {"available": False, "raw": ""}，绝不抛。
"""
from __future__ import annotations
import subprocess

# 2026-06 当下最强 codex 模型；跑一轮后按 §12 校准
_CODEX_MODEL = "gpt-5.6-sol"   # align with the fleet default (~/.codex/config.toml); was a stale gpt-5.5
_CODEX_EFFORT = "max"          # house rule: always strongest; was a stale xhigh


def invoke_codex_judge(prompt: str, timeout_s: int = 600) -> dict:
    """Run codex as a judge subprocess.

    Uses the project codex-judge.js wrapper that internally calls mcp__codex__codex
    with browser/playwright disabled and only web_search enabled.

    Returns {"available": True, "raw": stdout} on success.
    Returns {"available": False, "raw": ""} on any failure (timeout, non-zero
    exit, missing binary, empty output) — never raises.
    """
    cmd = [
        "node", "workflows/codex-judge.js",
        "--model", _CODEX_MODEL,
        "--effort", _CODEX_EFFORT,
        "--no-browser",
        "--no-playwright",
        "--tools", "web_search",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 勿用 locale(GBK)解码 UTF-8 输出
            errors="replace",
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"available": False, "raw": ""}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"available": False, "raw": ""}
    return {"available": True, "raw": proc.stdout}
