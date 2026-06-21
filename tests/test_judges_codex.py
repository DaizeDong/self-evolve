# tests/test_judges_codex.py
"""TDD tests for M3.1: judges, judge_codex, judge_claude adapters.
All tests mock subprocess/invoke — no real codex/claude calls."""
import json
import subprocess

from tools.sie import judges, judge_codex


def test_codex_unavailable_returns_flag(monkeypatch, tmp_path):
    # codex 子进程退出码非 0（限速/故障）→ available=False, 不抛异常
    def fake_invoke(prompt, timeout_s):
        return {"available": False, "raw": ""}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "art.md"
    art.write_text("# report\nRevenue grew 12% in FY2024.\n", encoding="utf-8")
    out = judges.score(str(art), anchors_visible=[{"span": "Revenue grew 12%"}], family="codex")
    assert out["available"] is False
    assert out["family"] == "codex"
    assert out["aggregate"] == 0.0


def test_prompt_carries_no_truth():
    # 铁律5：全字段断言——claim/source_url/expected/verified/marginal_gain/0.31 均不可出现
    anchors = [{"span": "Revenue grew 12%", "claim": "rev +12%",
                "verified": True, "marginal_gain": 0.31, "source_url": "http://x",
                "expected": 0.12}]
    p = judges.build_judge_prompt("body text", [a["span"] for a in anchors])
    assert "verified" not in p.lower()
    assert "marginal_gain" not in p
    assert "0.31" not in p
    assert "claim" not in p.lower()
    assert "source_url" not in p
    assert "expected" not in p.lower()
    assert "Revenue grew 12%" in p  # span 文本本身允许


def test_unspanned_penalized(monkeypatch, tmp_path):
    # judge 只回了 1 个 span 的分，但有 3 个待判 span → unspanned_penalized=2
    def fake_invoke(prompt, timeout_s):
        return {"available": True,
                "raw": '{"span_scores":[{"span":"s1","score":1.0}]}'}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("long body " * 500, encoding="utf-8")
    out = judges.score(str(art),
                       [{"span": "s1"}, {"span": "s2"}, {"span": "s3"}], "codex")
    assert out["unspanned_penalized"] == 2
    assert out["aggregate"] == 1.0  # 只对有 span 的计分，篇幅不加分


def test_codex_parse_valid_json(monkeypatch, tmp_path):
    """Normal available=True path: parse span_scores, compute aggregate."""
    def fake_invoke(prompt, timeout_s):
        raw = json.dumps({"span_scores": [
            {"span": "Revenue grew 12%", "score": 0.8},
            {"span": "EPS hit $2.30", "score": 0.6},
        ]})
        return {"available": True, "raw": raw}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("Revenue grew 12%. EPS hit $2.30.", encoding="utf-8")
    out = judges.score(str(art),
                       [{"span": "Revenue grew 12%"}, {"span": "EPS hit $2.30"}],
                       "codex")
    assert out["available"] is True
    assert out["family"] == "codex"
    assert abs(out["aggregate"] - 0.7) < 1e-9
    assert out["unspanned_penalized"] == 0
    assert len(out["span_scores"]) == 2


def test_codex_malformed_json_graceful(monkeypatch, tmp_path):
    """Malformed raw → available=True but aggregate=0.0, unspanned_penalized=N."""
    def fake_invoke(prompt, timeout_s):
        return {"available": True, "raw": "not json at all"}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("body", encoding="utf-8")
    out = judges.score(str(art), [{"span": "s1"}, {"span": "s2"}], "codex")
    assert out["available"] is True
    assert out["aggregate"] == 0.0
    assert out["unspanned_penalized"] == 2


def test_unknown_family_raises():
    """score() with unknown family must raise ValueError."""
    import pytest
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("body")
        name = f.name
    try:
        with pytest.raises(ValueError, match="unknown judge family"):
            judges.score(name, [], family="llama")
    finally:
        os.unlink(name)


def test_invoke_codex_judge_timeout(monkeypatch):
    """subprocess.TimeoutExpired → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_file_not_found(monkeypatch):
    """FileNotFoundError (node missing) → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("node not found")
    # Use object form (monkeypatch.setattr(module, attr, value)) to stay correct
    # even if judge_codex switches to `from subprocess import run`.
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_nonzero_exit(monkeypatch):
    """Non-zero returncode → available=False, no raise."""
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "rate limit"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_empty_stdout(monkeypatch):
    """returncode=0 but empty stdout → available=False."""
    class FakeProc:
        returncode = 0
        stdout = "   "
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_success(monkeypatch):
    """returncode=0 with stdout → available=True, raw=stdout."""
    raw = '{"span_scores":[]}'
    class FakeProc:
        returncode = 0
        stdout = raw
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": True, "raw": raw}


# ── I1: command argv 断言（锁住 Python 侧 flag 装配） ─────────────────────
def test_invoke_codex_judge_argv_flags(monkeypatch):
    """invoke_codex_judge 必须拼入 --no-browser/--no-playwright/最强模型/web_search。
    monkeypatch subprocess.run（对象形式，防 from-import 重构静默失效）。"""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeProc:
            returncode = 0
            stdout = '{"span_scores":[]}'
            stderr = ""
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    judge_codex.invoke_codex_judge("test prompt", timeout_s=10)

    cmd = captured["cmd"]
    assert "--no-browser" in cmd, f"--no-browser missing in {cmd}"
    assert "--no-playwright" in cmd, f"--no-playwright missing in {cmd}"
    assert "--tools" in cmd, f"--tools missing in {cmd}"
    tools_idx = cmd.index("--tools")
    assert cmd[tools_idx + 1] == "web_search", f"expected web_search, got {cmd[tools_idx+1]}"
    assert "--model" in cmd, f"--model missing in {cmd}"
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gpt-5.5", f"expected gpt-5.5, got {cmd[model_idx+1]}"


# ── I2: claude 不可用时 score() 返回契约 sentinel（显式 mock，脱离环境依赖）─
def test_score_claude_unavailable_returns_sentinel(monkeypatch, tmp_path):
    """family='claude' 且 invoke_claude_judge 返回 available=False 时，
    score() 须返回完整契约 sentinel：available=False + 全部必要键。
    使用显式 monkeypatch，不依赖 node 是否安装等环境条件。"""
    from tools.sie import judge_claude

    def fake_invoke(prompt, timeout_s):
        return {"available": False, "raw": ""}

    monkeypatch.setattr(judge_claude, "invoke_claude_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("body text", encoding="utf-8")
    out = judges.score(str(art), anchors_visible=[{"span": "body"}], family="claude")
    assert out["available"] is False
    assert out["family"] == "claude"
    assert out["aggregate"] == 0.0
    assert out["span_scores"] == []
    assert "unspanned_penalized" in out


# ── Minor: _parse_span_scores float 容错（非数值 score 被跳过） ────────────
def test_parse_span_scores_nonnumeric_skipped(monkeypatch, tmp_path):
    """span score 为字符串 'N/A' 时不崩溃，该 span 被跳过。"""
    def fake_invoke(prompt, timeout_s):
        raw = json.dumps({"span_scores": [
            {"span": "good span", "score": 0.9},
            {"span": "bad span", "score": "N/A"},
        ]})
        return {"available": True, "raw": raw}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "a.md"
    art.write_text("body", encoding="utf-8")
    out = judges.score(str(art), [{"span": "good span"}, {"span": "bad span"}], "codex")
    # "N/A" span skipped: only good span counted, unspanned_penalized=1
    assert out["available"] is True
    assert abs(out["aggregate"] - 0.9) < 1e-9
    assert out["unspanned_penalized"] == 1
    assert len(out["span_scores"]) == 1
