"""Claude judge 适配 — Task M3.2 实现。
judge 走独立联网子进程；prompt 无真值；出站纳入审查（proxy）。
不可用时 → {"available": False, "raw": ""}，绝不抛。
镜像 invoke_codex_judge 范式：超时/FileNotFoundError/OSError/非0退出/空输出均 graceful 降级。
"""
from __future__ import annotations
import subprocess


def invoke_claude_judge(prompt: str, timeout_s: int = 600) -> dict:
    """Invoke Claude as a judge subprocess.

    Mirrors invoke_codex_judge pattern: runs claude-judge.js in a separate
    process (physical isolation from candidate), sends only prompt with no
    ground-truth values (iron rule 5), routes through proxy outbound screening.

    Returns {"available": True, "raw": stdout} on success.
    Returns {"available": False, "raw": ""} on any failure (timeout, non-zero
    exit, missing binary, empty output) — never raises.
    """
    cmd = ["node", "workflows/claude-judge.js", "--tools", "web_search"]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"available": False, "raw": ""}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"available": False, "raw": ""}
    return {"available": True, "raw": proc.stdout}
