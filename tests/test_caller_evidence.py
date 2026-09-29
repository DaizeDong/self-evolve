"""Caller-level regressions for absent C measurements and artifact contracts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.make_fixtures import artifact_schema_samples, c_evidence_samples
from tools.sie import anchors, archive, evaluate, gate_human, statemachine
from tools.sie.backends import llm


def _proposal(tmp_path, monkeypatch, source, proposed):
    sample = artifact_schema_samples()
    path = tmp_path / sample["path"]
    original = json.dumps(source)
    path.write_text(original, encoding="utf-8")
    content = json.dumps(proposed, indent=2)
    prompts = []

    def invoke(prompt):
        prompts.append(prompt)
        return {"ok": True, "result": json.dumps({"file_rel": sample["path"],
                                                   "new_content": content}),
                "provider": "cc", "family": "claude", "attempts": [], "error": None}

    monkeypatch.setattr(llm.llm_adapter, "invoke_agent", invoke)
    result = llm.generate_artifact(str(tmp_path), [], sample["path"])
    assert path.read_text(encoding="utf-8") == original
    return result, content, prompts


@pytest.mark.parametrize("case", list(artifact_schema_samples()["invalid"]))
def test_malformed_anchor_schema_is_not_admitted(tmp_path, monkeypatch, case):
    sample = artifact_schema_samples()
    result, _, _ = _proposal(tmp_path, monkeypatch, sample["source"], sample["invalid"][case])
    assert result == [], case


@pytest.mark.parametrize("value", artifact_schema_samples()["finite_values"])
def test_finite_numbers_are_preserved_without_truth_substitution(tmp_path, monkeypatch, value):
    sample = artifact_schema_samples()
    proposal = deepcopy(sample["source"])
    proposal["sections"][0]["anchors"][0]["expected"] = value
    result, content, _ = _proposal(tmp_path, monkeypatch, sample["source"], proposal)
    assert len(result) == 1
    assert result[0]["new_content"] == content


def test_nonnumeric_artifact_remains_admissible(tmp_path, monkeypatch):
    sample = artifact_schema_samples()
    result, content, _ = _proposal(tmp_path, monkeypatch, sample["nonnumeric"], sample["nonnumeric"])
    assert len(result) == 1
    assert result[0]["new_content"] == content


def test_artifact_content_must_be_standalone_json(tmp_path, monkeypatch):
    sample = artifact_schema_samples()
    (tmp_path / sample["path"]).write_text(json.dumps(sample["source"]), encoding="utf-8")
    monkeypatch.setattr(llm.llm_adapter, "invoke_agent", lambda prompt: {
        "ok": True, "result": json.dumps({"file_rel": sample["path"],
                                          "new_content": sample["fenced_content"]}),
        "provider": "cc", "family": "claude", "attempts": [], "error": None})
    assert llm.generate_artifact(str(tmp_path), [], sample["path"]) == []


def test_artifact_prompt_explains_withheld_numeric_schema(tmp_path, monkeypatch):
    sample = artifact_schema_samples()
    _, _, prompts = _proposal(tmp_path, monkeypatch, sample["source"], sample["source"])
    prompt = prompts[0]
    instructions, payload = prompt.split("\n\n", 1)
    for key in ("claim", "span", "source_url", "metric", "cik", "period", "expected"):
        assert key in instructions
    assert "finite" in instructions
    anchor = sample["source"]["sections"][0]["anchors"][0]
    for key in ("expected", "observed", "marginal_gain"):
        assert str(anchor[key]) not in prompt
        assert key not in json.loads(payload)["artifact"]["sections"][0]["anchors"][0]


@pytest.mark.parametrize("source_available", [True, False])
def test_finite_wrong_proposal_is_rejected_by_independent_verification(tmp_path, monkeypatch, source_available):
    sample = artifact_schema_samples()
    proposal = deepcopy(sample["source"])
    proposal["sections"][0]["anchors"][0]["expected"] = sample["wrong_value"]
    result, content, _ = _proposal(tmp_path, monkeypatch, sample["source"], proposal)
    assert len(result) == 1
    assert result[0]["new_content"] == content
    proposed_anchor = json.loads(content)["sections"][0]["anchors"][0]
    verdict = anchors.verify_anchor(proposed_anchor, fetcher=lambda _: (
        sample["source_value"] if source_available else None))
    assert verdict["verified"] is False


def test_c_caller_without_measurements_pauses_with_honest_diagnostics(tmp_path, monkeypatch):
    sample = c_evidence_samples()
    target, sandbox = tmp_path / "target", tmp_path / "sandbox"
    target.mkdir()
    sandbox.mkdir()
    monkeypatch.setattr(statemachine, "make_worktree", lambda *a, **k: str(sandbox))
    monkeypatch.setattr(statemachine, "run_profile", lambda *a, **k: sample["profile"])
    monkeypatch.setattr(statemachine, "freeze_target", lambda *a, **k: None)
    monkeypatch.setattr(statemachine, "reflect", lambda *a, **k: sample["reflection"])
    monkeypatch.setattr(statemachine, "propose", lambda *a, **k: sample["proposals"])
    monkeypatch.setattr(statemachine, "apply_patch", lambda *a, **k: {"status": "APPLIED"})
    monkeypatch.setattr(archive, "snapshot_version", lambda *a, **k: None)
    actual_evaluate = evaluate.evaluate_c_tier
    observations = []

    def observe(**kwargs):
        result = actual_evaluate(**kwargs)
        observations.append((kwargs, result))
        return result

    monkeypatch.setattr(evaluate, "evaluate_c_tier", observe)
    summary = statemachine.run_loop(str(target), "HEAD", sample["run_id"], max_rounds=4, mode="auto")
    assert observations
    for supplied, measured in observations:
        assert supplied["regression_replay"] == []
        assert supplied["internal_consistency"] == []
        assert measured["available"] is False
        assert measured["no_regression"] is False
        assert measured["consistency_paired"] == []
    assert summary["accepted_versions"] == []
    assert summary["final_phase"] == "PAUSE_FOR_HUMAN"
    pending = gate_human.pending(summary["run_dir"])
    assert pending
    evidence = pending[0]["payload"]["evaluation"]
    assert evidence["available"] is False
    assert evidence["regression_evidence"] == "missing_or_invalid"
    assert evidence["consistency_evidence"] == "missing_or_invalid"
    assert evidence["scenario_eval"] == "not_implemented"
    events = [json.loads(line) for line in (Path(summary["run_dir"]) / "events.jsonl").read_text().splitlines()]
    assert not any(event["type"] == "ACCEPT" for event in events)
