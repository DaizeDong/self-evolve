"""Packaged transport helper. Its caller owns the disposable private working directory."""
from contextlib import redirect_stdout
import json
import sys

from llm_adapter import failure, normalize_result


def main() -> int:
    try:
        request = json.load(sys.stdin)
        prompt = request["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("empty agent prompt")
        with redirect_stdout(sys.stderr):
            import llmcall
            kwargs = {"mode": "agent"}
            if request.get("avoid"):
                kwargs["avoid"] = request["avoid"]
            result = normalize_result(llmcall.call(prompt, **kwargs))
    except Exception as exc:
        result = failure(f"llmcall child unavailable: {type(exc).__name__}: {exc}")
    result["text"] = result.pop("result")
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
