"""Offline public-wrapper regressions; no live providers are invoked."""
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

from tools.make_fixtures import llm_samples
from tools.sie import agents, evaluate, judge_claude, judge_codex, judges, reflect
from tools.sie.backends import llm


@pytest.fixture(autouse=True)
def block_processes(monkeypatch):
    def blocked(*args, **kwargs):
        raise OSError("Processes are disabled in this offline test")
    monkeypatch.setattr(subprocess, "run", blocked)


@pytest.fixture
def sample():
    return llm_samples()


@pytest.fixture
def service(monkeypatch, sample):
    calls = []
    responses = []

    def call(prompt, **kwargs):
        calls.append((prompt, kwargs))
        value = responses.pop(0) if responses else sample["text"]
        if isinstance(value, Exception):
            raise value
        if not isinstance(value, str):
            return value
        return SimpleNamespace(text=value, provider="cc", error=None,
                               attempts=sample["attempts"])

    monkeypatch.setitem(sys.modules, "llmcall", SimpleNamespace(call=call))
    return calls, responses


@pytest.mark.parametrize("wrapper", [judge_codex.invoke_codex_judge,
                                     judge_claude.invoke_claude_judge])
def test_judge_uses_shared_defaults(wrapper, sample, service):
    calls, _ = service
    out = wrapper(sample["prompt"], timeout_s=1)
    assert out["available"]
    assert calls == [(sample["prompt"], {})]
    assert out["provider"] == "cc"
    assert out["family"] == "claude"
    assert out["attempts"] == sample["attempts"]


@pytest.mark.parametrize("kind", ["empty", "malformed", "pending", "exception"])
def test_bad_service_response_is_unavailable(kind, service, sample):
    _, responses = service
    if kind == "empty":
        responses.append(" ")
    elif kind == "malformed":
        responses.append({"text": sample["text"]})
    elif kind == "pending":
        responses.append(SimpleNamespace(text=sample["text"], provider="cc",
                         attempts=sample["attempts"], error=None, status="running"))
    else:
        responses.append(RuntimeError("synthetic service failure"))
    out = judge_codex.invoke_codex_judge(sample["prompt"])
    assert not out["available"]
    assert out.get("error")
    assert "attempts" in out


@pytest.mark.parametrize("providers, independent", [(("cc", "claude"), False),
    (("codexg", "codex"), False), (("cc", "unrecognized-provider"), False),
    (("cc", "codexg"), True)])
def test_verdict_independence_uses_actual_provider(providers, independent, service, sample):
    calls, responses = service
    responses.extend(SimpleNamespace(text=json.dumps(sample["verdicts"][0]),
                     provider=provider, attempts=[], error=None) for provider in providers)
    out = agents.cross_check_verdicts(sample["prompt"])
    assert out["agree"] is (True if independent else None)
    assert all("mode" not in kwargs for _, kwargs in calls)
    assert calls[1][1] == {"avoid": providers[0]}
    if not independent:
        assert "insufficient_independence" in str(out)


@pytest.mark.parametrize("bad_score", llm_samples()["bad_scores"])
def test_invalid_judge_scores_cannot_earn_credit(bad_score, sample):
    raw = json.dumps({"span_scores": [{"span": sample["spans"][0], "score": bad_score}]})
    out = judges._parse_span_scores(raw, sample["spans"])
    assert not out["available"]
    assert out["aggregate"] == 0


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "schema", "empty"])
def test_invalid_scoring_evidence_is_unavailable(kind, sample):
    entry = sample["scores"]["span_scores"][0]
    values = {"duplicate": [entry, entry], "unknown": [{"span": "unknown", "score": 1}],
              "schema": {}, "empty": []}
    out = judges._parse_span_scores(json.dumps({"span_scores": values[kind]}), sample["spans"])
    assert not out["available"]
    assert out["aggregate"] == 0


def test_partial_scores_penalize_missing_spans(sample):
    out = judges._parse_span_scores(json.dumps({"span_scores": sample["scores"]["span_scores"][:1]}),
                                    sample["spans"])
    assert out["available"]
    assert out["aggregate"] == 0.4
    assert out["unspanned_penalized"] == 1


@pytest.mark.parametrize("missing", ["replay", "consistency"])
def test_c_tier_requires_both_evidence_sources(missing, sample):
    replay = [] if missing == "replay" else sample["replay"]
    consistency = [] if missing == "consistency" else sample["consistency"]
    out = evaluate.evaluate_c_tier(sample["artifact_path"], replay, consistency)
    assert not out["no_regression"]
    assert out["coverage"] == 0
    assert "missing" in str(out)


def test_agent_child_cwd_and_cleanup(monkeypatch, tmp_path, sample):
    from tools.sie import runtime_data
    seen = []
    caller_cwd = Path.cwd()

    @contextlib.contextmanager
    def scratch():
        with tempfile.TemporaryDirectory(dir=tmp_path) as value:
            yield Path(value)

    def run(command, **kwargs):
        seen.append(Path(kwargs["cwd"]))
        assert Path.cwd() == caller_cwd
        assert command[0] == sys.executable
        assert Path(command[-1]).is_absolute()
        assert kwargs.get("shell") is False
        assert json.loads(kwargs["input"])["prompt"] == sample["prompt"]
        result = {"text": sample["text"], "provider": "codexg", "error": None,
                  "attempts": sample["attempts"]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(runtime_data, "agent_scratch", scratch)
    monkeypatch.setattr(subprocess, "run", run)
    out = agents.invoke(sample["prompt"], model="ignored", effort="ignored", timeout_s=1)
    assert out["ok"]
    assert out["provider"] == "codexg" and out["family"] == "codex"
    assert seen and all(not path.exists() for path in seen)
    assert Path.cwd() == caller_cwd


def test_reflection_malformed_response_is_inspectable(monkeypatch, sample, tmp_path):
    monkeypatch.setattr(agents, "invoke", lambda *args, **kwargs: {
        "ok": True, "result": "{}", "provider": "cc", "family": "claude", "attempts": []})
    out = reflect.run_reflections_parallel(str(tmp_path), sample["history"], 2)
    assert len(out) == 2
    assert all(not item["ok"] and item["error"] for item in out)


def test_proposer_missing_input_reports_failure(sample, tmp_path, capsys):
    assert llm.generate_artifact(str(tmp_path), [], sample["artifact_path"]) == []
    assert capsys.readouterr().err


def test_judge_json_artifact_does_not_expose_truth(sample):
    prompt = judges.build_judge_prompt(json.dumps(sample["document"]), sample["spans"])
    for secret in ("7654321", "7654322", "0.314159"):
        assert secret not in prompt


def test_malformed_structured_artifact_never_reaches_judge(sample, service, tmp_path):
    calls, _ = service
    artifact = tmp_path / sample["artifact_path"]
    artifact.write_text(sample["malformed_artifact"], encoding="utf-8")
    out = judges.score(str(artifact), [{"span": span} for span in sample["spans"]], "claude")
    assert not out["available"] and out["error"]
    assert calls == []
