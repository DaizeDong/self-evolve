"""Claude judge 适配桩 — Task M3.2 充实。
judge 走独立联网进程；prompt 无真值；出站纳入审查（proxy）。
不可用时 → {"available": False, "raw": ""}，绝不抛。
"""
from __future__ import annotations


def invoke_claude_judge(prompt: str, timeout_s: int = 600) -> dict:
    """Invoke Claude as a judge (M3.2 implementation pending).

    Stub: raises NotImplementedError to make family="claude" routing explicit.
    M3.2 will replace this with a real subprocess/API call that:
      - Runs in a separate process (physical isolation from candidate)
      - Sends only prompt with no ground-truth values (iron rule 5)
      - Routes through proxy outbound screening
      - Returns {"available": False, "raw": ""} on any failure
    """
    raise NotImplementedError("judge_claude: M3.2 not yet implemented")
