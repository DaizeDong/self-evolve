"""Regression contracts for Source13 repairs, using generated synthetic input."""
import copy
import json
from pathlib import Path

import pytest

from tools.make_fixtures import source13_repair_inputs, synthetic_artifact
from tools.sie import calibrate, evaluate, events, patch, profile, runtime_data, statemachine
from tools.sie.probes import fact_probe


@pytest.mark.parametrize("case,source,allowed", source13_repair_inputs()["filesystem"])
def test_filesystem_capabilities_require_proven_paths(tmp_path, case, source, allowed):
    sandbox = tmp_path / "candidate"
    sandbox.mkdir()
    target = sandbox / "module.py"
    reasons = patch.scan_ast_dangerous(source, sandbox_root=str(sandbox), target_path=str(target))
    assert (not reasons) is allowed, (case, reasons)
    accepted, reason = patch.import_gate(
        source, set(patch.DEFAULT_IMPORT_ALLOW), sandbox_root=str(sandbox), file_rel="module.py")
    assert accepted is allowed, (case, reason)
    result = patch.apply_patch(str(sandbox), "module.py", source)
    assert (result["status"] == "APPLIED") is allowed, (case, result)
    assert target.exists() is allowed
    if allowed:
        assert target.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("variant", source13_repair_inputs()["invalid_grade_variants"])
def test_candidate_grade_failure_never_becomes_positive_pairs(tmp_path, monkeypatch, variant):
    case = source13_repair_inputs()
    grade = copy.deepcopy(case["grade"])
    parents = copy.deepcopy(grade["dimensions"])
    if variant == "failed_exit":
        grade["grader_exit_code"] = 1
    elif variant == "false_pass":
        grade["task_passed"] = False
    elif variant == "duplicate":
        grade["dimensions"].append(dict(grade["dimensions"][0]))
    elif variant == "missing_parent":
        grade["dimensions"].pop()
    elif variant == "not_a_result":
        grade = None
    elif variant == "unavailable":
        grade["available"] = False
    elif variant == "missing_exit":
        del grade["grader_exit_code"]
    elif variant == "empty_dimensions":
        grade["dimensions"] = []
    elif variant in case["invalid_score_values"]:
        grade["dimensions"][0]["score"] = case["invalid_score_values"][variant]
    else:
        grade["dimensions"][0]["score"] = True
    monkeypatch.setattr(evaluate, "_grade_pytest_per_task", lambda root: grade)
    result = evaluate.evaluate(str(tmp_path), base_result={"dimensions": parents})
    assert result["result"] is grade
    assert result["paired"] == []
    assert result["usable"] is False
    assert evaluate.candidate_grade_error(grade, parents) is not None


def test_successful_candidate_still_produces_parent_pairs(tmp_path, monkeypatch):
    grade = source13_repair_inputs()["grade"]
    parents = copy.deepcopy(grade["dimensions"])
    for item in parents:
        item["score"] = 0.0
    monkeypatch.setattr(evaluate, "_grade_pytest_per_task", lambda root: grade)
    result = evaluate.evaluate(str(tmp_path), base_result={"dimensions": parents})
    assert result["usable"] is True
    assert result["paired"] == [(0.0, 1.0)] * len(parents)


def test_fact_discovery_separates_tool_fixtures_from_runtime_artifacts(tmp_path):
    artifact = synthetic_artifact()
    fixture = tmp_path / "tests" / "fixtures" / "sample.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(json.dumps(artifact), encoding="utf-8")
    assert fact_probe.probe(str(tmp_path), "synthetic")["tier_signal"] is None
    output = tmp_path / "report.json"
    output.write_text(json.dumps(artifact), encoding="utf-8")
    result = fact_probe.probe(str(tmp_path), "synthetic")
    assert result["tier_signal"] == "B"
    assert result["anchor_count"] == 24
    assert str(fixture) not in result["evidence"]["scanned_files"]
    assert fact_probe.probe(str(fixture), "synthetic")["anchor_count"] == 24


def test_profile_keeps_reference_schema_and_separate_integrity(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
    monkeypatch.setattr(profile, "_exec_signal", lambda *args: pytest.fail("Artifact-only profile ran executable probe"))
    result = profile.run_profile(str(artifact), "synthetic", include_exec_probe=False)
    assert set(result["anchors_holdout_ref"]) == {"path", "count", "ref"}
    assert result["anchors_holdout_ref"]["count"] == 9
    assert len(result["anchors_holdout_sha256"]) == 64


def test_resume_uses_durable_rounds_and_reflection_history(tmp_path, monkeypatch):
    sandbox = tmp_path / "candidate"
    sandbox.mkdir()
    profile_data = source13_repair_inputs()["profile"]
    histories = []
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(sandbox))
    monkeypatch.setattr(statemachine, "run_profile", lambda *args: copy.deepcopy(profile_data))

    def reflect_empty(root, history, n=1):
        histories.append(copy.deepcopy(list(history)))
        return []

    monkeypatch.setattr(statemachine, "reflect", reflect_empty)
    options = {"max_rounds": 3, "_extra_params": {"static_reject_circuit": 100}}
    first = statemachine.run_loop(str(sandbox), "synthetic", "resume-contract", **options)
    second = statemachine.run_loop(str(sandbox), "synthetic", "resume-contract", **options)
    run_dir = first["run_dir"]
    assert second["run_dir"] == run_dir
    assert events.replay(run_dir).round == 6
    assert [len(history) for history in histories] == list(range(6))
    restored, last_holdout = statemachine._resume_records(run_dir)
    assert [record["round"] for record in restored] == [1, 2, 3, 4, 5, 6]
    assert last_holdout == 0
    records = [json.loads(line) for line in (Path(run_dir) / "events.jsonl").read_text().splitlines()]
    assert sum(record["type"] == "INIT" for record in records) == 1


def test_calibration_remeasures_imported_configuration_changes(tmp_path, monkeypatch):
    case = source13_repair_inputs()["calibration"]
    run = tmp_path / "calibration"
    archive = run / "archive"
    archive.mkdir(parents=True)
    (archive / "lineage.json").write_text(json.dumps(case["versions"]), encoding="utf-8")
    for entry, setting in zip(case["versions"], case["settings"]):
        snapshot = archive / "versions" / entry["vid"] / "snapshot"
        snapshot.mkdir(parents=True)
        (snapshot / "reader.py").write_text(case["source"], encoding="utf-8")
        (snapshot / "settings.json").write_text(json.dumps(setting), encoding="utf-8")
    monkeypatch.setattr(runtime_data, "run_directory", lambda *args: run)
    measured = []

    def settings_oracle(snapshot, oracle):
        measured.append(Path(snapshot).parent.name)
        setting = json.loads((Path(snapshot) / "settings.json").read_text(encoding="utf-8"))
        return (0 if setting["enabled"] else 1), "synthetic configuration result"

    monkeypatch.setattr(calibrate, "run_oracle", settings_oracle)
    result = calibrate.attribute_decisions(str(tmp_path), "synthetic", [case["defect"]])
    assert measured == ["v1", "v2"]
    assert result["versions"][1]["labels"] == ["REGRESSION"]
    assert result["versions"][1]["regressed"] == [case["defect"]["id"]]


def test_short_resumes_preserve_holdout_measurement_schedule(tmp_path, monkeypatch):
    sandbox = tmp_path / "factual-candidate"
    sandbox.mkdir()
    (sandbox / "artifact.json").write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
    change = source13_repair_inputs()["loop_change"]
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(sandbox))
    monkeypatch.setattr(statemachine, "run_profile", lambda target, ref:
                        profile.run_profile(target, ref, include_exec_probe=False))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(change)])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(change)])
    measured_rounds = []
    real_context = statemachine._btier_round_context

    def measure(*args, **kwargs):
        result = real_context(*args, **kwargs)
        if result["holdout_base"] is not None:
            measured_rounds.append(result["round"])
        return result

    monkeypatch.setattr(statemachine, "_btier_round_context", measure)
    options = {"max_rounds": 3, "fetcher": lambda anchor: anchor["expected"],
               "_extra_params": {"forced_review_circuit": 100, "no_progress_circuit_N": 100}}
    statemachine.run_loop(str(sandbox), "synthetic", "holdout-resume", **options)
    summary = statemachine.run_loop(str(sandbox), "synthetic", "holdout-resume", **options)
    assert measured_rounds == [5]
    assert statemachine._resume_records(summary["run_dir"])[1] == 5
    assert events.replay(summary["run_dir"]).round == 6


@pytest.mark.parametrize("self_mode", [False, True])
def test_both_a_callers_refuse_a_failed_candidate_grade(tmp_path, monkeypatch, self_mode):
    sandbox = tmp_path / "scored-candidate"
    sandbox.mkdir()
    case = source13_repair_inputs()
    grade = copy.deepcopy(case["grade"])
    grade["task_passed"] = False
    grade["grader_exit_code"] = 1
    decisions = []
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(sandbox))
    monkeypatch.setattr(statemachine, "run_profile", lambda *args: copy.deepcopy(case["profile"]))
    monkeypatch.setattr(statemachine, "_parent_baseline", lambda *args: copy.deepcopy(case["grade"]))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(case["loop_change"])])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(case["loop_change"])])

    def accepting_decider(*args):
        decisions.append(args)
        return {"decision": "ACCEPT", "reason": "synthetic acceptance", "evalue": 100.0}

    monkeypatch.setattr(statemachine, "decide", accepting_decider)
    monkeypatch.setattr(statemachine, "evaluate", lambda *args, **kwargs:
                        {"result": grade, "paired": [(0.0, 1.0)] * 4, "coverage": 1.0, "usable": True})

    class FrozenSupervisor:
        def grade(self, *args, **kwargs):
            return copy.deepcopy(grade)

        def decide(self, *args):
            return accepting_decider(*args)

    options = {"supervisor": FrozenSupervisor(), "candidate_worktree": str(sandbox)} if self_mode else {}
    result = statemachine.run_loop(str(sandbox), "synthetic", "candidate-failed", max_rounds=1, **options)
    assert decisions == []
    assert result["accepted_versions"] == []
    assert not (sandbox / case["loop_change"]["file_rel"]).exists()
