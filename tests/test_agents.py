"""Agent wrappers and actual-provider independence using synthetic llmcall results."""
import json
import pytest
import sys
from types import SimpleNamespace

from tools.make_fixtures import llm_samples
from tools.sie import agents, llm_adapter


def _agent_responses(monkeypatch, providers):
    sample = llm_samples()
    values = iter(providers)
    def invoke(prompt, **kwargs):
        provider = next(values)
        if provider is None:
            return llm_adapter.failure("synthetic unavailable")
        return llm_adapter.normalize_result(SimpleNamespace(text=sample["text"],
            provider=provider, attempts=sample["attempts"], error=None))
    monkeypatch.setattr(llm_adapter, "invoke_agent", invoke)


def _verdict_responses(monkeypatch, providers, verdict_indices):
    sample = llm_samples()
    values = iter(zip(providers, verdict_indices))
    def call(prompt, **kwargs):
        provider, index = next(values)
        return SimpleNamespace(text=json.dumps(sample["verdicts"][index]),
            provider=provider, attempts=[], error=None)
    monkeypatch.setitem(sys.modules, "llmcall", SimpleNamespace(call=call))


def test_invoke_ok(monkeypatch):
    _agent_responses(monkeypatch, ["codexg"])
    out = agents.invoke(llm_samples()["prompt"], family="claude")
    assert out["ok"] and out["family"] == "codex" and out["provider"] == "codexg"
    assert out["requested_family"] == "claude"


def test_invoke_invalid_family():
    assert not agents.invoke(llm_samples()["prompt"], family="bogus")["ok"]


def test_invoke_nonzero_or_empty(monkeypatch):
    _agent_responses(monkeypatch, [None])
    assert not agents.invoke(llm_samples()["prompt"])["ok"]


def test_invoke_timeout(monkeypatch):
    _agent_responses(monkeypatch, [None])
    assert agents.invoke(llm_samples()["prompt"])["error"]


def test_cross_check_heterogeneous(monkeypatch):
    _agent_responses(monkeypatch, ["cc", "codexg"])
    out = agents.cross_check(llm_samples()["prompt"])
    assert out["n_ok"] == 2 and out["heterogeneous"]
    assert all(result["provider"] for result in out["per"].values())


def test_cross_check_one_unavailable(monkeypatch):
    _agent_responses(monkeypatch, ["cc", None])
    out = agents.cross_check(llm_samples()["prompt"])
    assert out["n_ok"] == 1 and not out["heterogeneous"]
    assert out["status"] == "insufficient_independence"


def test_cross_check_verdicts_agree(monkeypatch):
    _verdict_responses(monkeypatch, ["cc", "codexg"], [0, 0])
    out = agents.cross_check_verdicts(llm_samples()["prompt"])
    assert out["agree"] is True and out["n_ok"] == 2


def test_cross_check_verdicts_disagree(monkeypatch):
    _verdict_responses(monkeypatch, ["cc", "codexg"], [0, 1])
    assert agents.cross_check_verdicts(llm_samples()["prompt"])["agree"] is False


def test_cross_check_verdicts_single_valid_is_none(monkeypatch):
    _verdict_responses(monkeypatch, ["cc", None], [0, 0])
    out = agents.cross_check_verdicts(llm_samples()["prompt"])
    assert out["agree"] is None and out["n_ok"] == 1


def test_preflight_dual_codex_available(monkeypatch):
    monkeypatch.setattr(agents, "codex_available", lambda timeout_s=20: True)
    assert agents.preflight_dual(True) == (True, None)


def test_preflight_dual_codex_missing_degrades(monkeypatch):
    monkeypatch.setattr(agents, "codex_available", lambda timeout_s=20: False)
    enabled, warning = agents.preflight_dual(True)
    assert not enabled and warning


def test_preflight_dual_not_requested(monkeypatch):
    monkeypatch.setattr(agents, "codex_available", lambda **kwargs: pytest.fail("unexpected probe"))
    assert agents.preflight_dual(False) == (False, None)
