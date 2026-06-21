# tests/test_judges_codex.py
"""TDD tests for M3.1: judges, judge_codex, judge_claude adapters.
All tests mock subprocess/invoke — no real codex/claude calls."""
import json
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
    anchors = [{"span": "Revenue grew 12%", "claim": "rev +12%",
                "verified": True, "marginal_gain": 0.31, "source_url": "http://x"}]
    p = judges.build_judge_prompt("body text", [a["span"] for a in anchors])
    assert "verified" not in p.lower()
    assert "marginal_gain" not in p
    assert "0.31" not in p
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
    import pytest, tempfile, os
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
    import subprocess
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_file_not_found(monkeypatch):
    """FileNotFoundError (node missing) → available=False, no raise."""
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("node not found")
    monkeypatch.setattr("subprocess.run", fake_run)
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_nonzero_exit(monkeypatch):
    """Non-zero returncode → available=False, no raise."""
    import subprocess
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "rate limit"
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_empty_stdout(monkeypatch):
    """returncode=0 but empty stdout → available=False."""
    import subprocess
    class FakeProc:
        returncode = 0
        stdout = "   "
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": False, "raw": ""}


def test_invoke_codex_judge_success(monkeypatch):
    """returncode=0 with stdout → available=True, raw=stdout."""
    import subprocess
    raw = '{"span_scores":[]}'
    class FakeProc:
        returncode = 0
        stdout = raw
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())
    result = judge_codex.invoke_codex_judge("hello", timeout_s=1)
    assert result == {"available": True, "raw": raw}
