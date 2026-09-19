"""Read-only claude judge. Family is explicit; model and effort inherit llmcall."""
from .agents import invoke


def invoke_claude_judge(prompt: str, timeout_s: int = 600) -> dict:
    result = invoke(prompt, family="claude", tools="web_search", timeout_s=timeout_s)
    return {**result, "available": result["ok"], "raw": result["result"]}
