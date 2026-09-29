"""Legacy Codex judge entrypoint using llmcall's current default judge policy."""
from tools.sie.llm_adapter import invoke_judge


def invoke_codex_judge(prompt: str, timeout_s: int = 600, *, avoid: str | None = None) -> dict:
    result = invoke_judge(prompt, avoid=avoid)
    return {**result, "available": result["ok"], "raw": result["result"],
            "requested_family": "codex"}
