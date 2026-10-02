"""Generated mutation-grader regressions; all source payloads are synthetic."""
from pathlib import Path
import subprocess

import pytest

from tools.make_fixtures import (
    byte_preservation_inputs, mutation_grader_failure_test_source,
)
from tools.sie.verifiable import mutation_validity_gate


CASES = byte_preservation_inputs()
MUTABLE_CASES = [case for case in CASES if case["mutants"]]


def source_file(tmp_path, case):
    source = tmp_path / "module.py"
    source.write_bytes(case["source"])
    return source


def grader_error(kind):
    if kind == "runtime":
        return RuntimeError("Synthetic mutant grader failure")
    return subprocess.TimeoutExpired("synthetic-grader", 1)


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("kind", ["runtime", "timeout"])
@pytest.mark.parametrize("minimum", [0.0, 1.0])
@pytest.mark.parametrize("completed", [(), (False,), (True,)],
                         ids=["first-mutant", "after-kill", "after-survivor"])
def test_mutant_grader_error_propagates_without_acceptance(tmp_path, case, kind, minimum, completed):
    source = source_file(tmp_path, case)
    error = grader_error(kind)
    calls = []

    def run(_root):
        payload = source.read_bytes()
        calls.append(payload)
        if len(calls) == 1:
            assert payload == case["source"]
            return True
        assert payload != case["source"]
        index = len(calls) - 2
        if index < len(completed):
            return completed[index]
        raise error

    with pytest.raises(type(error)) as raised:
        mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=minimum)
    assert raised.value is error
    assert len(calls) == 2 + len(completed)
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("outcome", ["false", "runtime", "timeout"])
def test_baseline_refusal_keeps_existing_invalid_result(tmp_path, case, outcome):
    source = source_file(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        if outcome == "false":
            return False
        raise grader_error(outcome)

    result = mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=0.0)
    assert result == {"valid": False, "killed": 0, "total": 0,
                      "kill_ratio": 0.0, "survivors": []}
    assert calls == [case["source"]]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("phase", ["baseline", "mutant"])
def test_baseexception_identity_and_restoration_are_preserved(tmp_path, case, error_type, phase):
    source = source_file(tmp_path, case)
    error = error_type("Synthetic grader interruption")
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        if phase == "mutant" and len(calls) == 1:
            return True
        raise error

    with pytest.raises(error_type) as raised:
        mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=0.0)
    assert raised.value is error
    assert len(calls) == (1 if phase == "baseline" else 2)
    assert calls[0] == case["source"]
    assert source.read_bytes() == case["source"]


@pytest.mark.parametrize("case", MUTABLE_CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("verdict", [False, True])
@pytest.mark.parametrize("minimum", [0.0, 1.0])
def test_returned_boolean_verdicts_keep_existing_counts(tmp_path, case, verdict, minimum):
    source = source_file(tmp_path, case)
    calls = []

    def run(_root):
        calls.append(source.read_bytes())
        return True if len(calls) == 1 else verdict

    result = mutation_validity_gate(str(tmp_path), [source.name], run, min_kill_ratio=minimum)
    killed = 0 if verdict else case["mutants"]
    ratio = killed / case["mutants"]
    assert result == {
        "valid": ratio >= minimum,
        "killed": killed,
        "total": case["mutants"],
        "kill_ratio": ratio,
        "survivors": [f"{source.name}:mut_{index}" for index in range(case["mutants"])]
                     if verdict else [],
    }
    assert len(calls) == 1 + case["mutants"]
    assert source.read_bytes() == case["source"]


def test_generated_mutation_grader_source_is_reproducible():
    assert mutation_grader_failure_test_source() == Path(__file__).read_text(encoding="utf-8")
