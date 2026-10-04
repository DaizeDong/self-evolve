"""Generated synthetic cases for lossless candidate and failure evidence storage."""
import copy
import json

import pytest

from tools.make_fixtures import stage_record_samples
from tools.sie.stage_records import compact_record


@pytest.fixture
def sample():
    return stage_record_samples()


def test_actual_writer_compacts_success_and_preserves_failure(sample, tmp_path):
    from tools.sie import runtime_data
    from tools.sie.statemachine import _record_model_stage

    run = runtime_data.run_directory(tmp_path, 'synthetic-stage-records')
    run.mkdir(parents=True, exist_ok=True)
    failed = sample['proposal_rejected']['failure']
    original = copy.deepcopy(sample['proposal'])
    _record_model_stage(run, 'proposals.jsonl', sample['proposal'])
    _record_model_stage(run, 'proposals.jsonl', failed)
    rows = [json.loads(line) for line in (run / 'proposals.jsonl').read_text(
        encoding='utf-8').splitlines()]
    assert rows == [compact_record('proposals.jsonl', original), failed]
    assert rows[0]['proposals'][0]['new_content'] == sample['content']
    assert sample['proposal'] == original


def test_successful_proposal_keeps_exact_content_and_all_backend_metadata(sample):
    projected = compact_record("proposals.jsonl", sample["proposal"])
    stored = json.loads(json.dumps(projected, ensure_ascii=False))
    proposal = stored["proposals"][0]
    assert proposal["new_content"].encode("utf-8") == sample["content"].encode("utf-8")
    assert proposal["file_rel"] == sample["proposal"]["proposals"][0]["file_rel"]
    assert proposal["fixes"] == sample["proposal"]["proposals"][0]["fixes"]
    for outcome in (proposal["backend"], stored["backend_outcomes"][0]):
        assert outcome == {**sample["metadata"], "result_storage": "parsed"}
    assert stored["diagnostics"] == sample["proposal"]["diagnostics"]


@pytest.mark.parametrize("filename", ["reflections.jsonl", "reflector-outcomes.jsonl"])
@pytest.mark.parametrize("empty", [False, True])
def test_successful_reflection_keeps_parsed_findings_and_metadata(sample, filename, empty):
    record = sample["reflection"]
    outcome = record["backend_outcomes"][0]
    if empty:
        outcome["findings"] = []
        outcome["result"] = json.dumps({"findings": []})
    projected = compact_record(filename, record)
    assert projected["backend_outcomes"][0] == {
        **sample["metadata"], "reflector": outcome["reflector"],
        "findings": outcome["findings"], "result_storage": "parsed",
    }
    assert projected["reflections"] == record["reflections"]


@pytest.mark.parametrize("name", [
    "failure", "error_with_success", "malformed", "extra_keys", "different_content",
    "empty_content", "unmatched_fallback",
])
def test_rejected_or_unmatched_proposal_keeps_raw_evidence(sample, name):
    record = sample["proposal_rejected"][name]
    assert compact_record("proposals.jsonl", record) == record


@pytest.mark.parametrize("name", [
    "failure", "error_with_success", "malformed", "extra_keys", "different_findings", "invalid_findings",
])
def test_unvalidated_reflection_keeps_raw_evidence(sample, name):
    record = sample["reflection_rejected"][name]
    assert compact_record("reflections.jsonl", record) == record


@pytest.mark.parametrize("kind,filename", [
    ("proposal", "proposals.jsonl"), ("reflection", "reflections.jsonl"),
])
@pytest.mark.parametrize("envelope", ["whitespace", "json_fence"])
def test_complete_json_envelope_can_be_compacted(sample, kind, filename, envelope):
    record = sample["envelopes"][kind][envelope]
    projected = compact_record(filename, record)
    assert projected["backend_outcomes"][0]["result_storage"] == "parsed"
    assert "result" not in projected["backend_outcomes"][0]
    if kind == "proposal":
        assert projected["proposals"][0]["new_content"] == sample["content"]
        assert "result" not in projected["proposals"][0]["backend"]


@pytest.mark.parametrize("kind,filename", [
    ("proposal", "proposals.jsonl"), ("reflection", "reflections.jsonl"),
])
@pytest.mark.parametrize("envelope", [
    "prefix_prose", "suffix_prose", "fence_prose", "multiple_fences", "duplicate_keys",
])
def test_explanatory_prose_or_duplicate_keys_keep_complete_raw_result(sample, kind, filename, envelope):
    record = sample["envelopes"][kind][envelope]
    assert compact_record(filename, record) == record


def test_unassociated_backend_outcome_is_not_compacted(sample):
    record = sample["proposal"]
    unrelated = copy.deepcopy(record["backend_outcomes"][0])
    unrelated["attempts"] = []
    record["backend_outcomes"].append(unrelated)
    projected = compact_record("proposals.jsonl", record)
    assert "result" not in projected["backend_outcomes"][0]
    assert projected["backend_outcomes"][1] == unrelated


@pytest.mark.parametrize("kind,filename", [
    ("proposal", "proposals.jsonl"), ("reflection", "reflections.jsonl"),
])
def test_projection_does_not_mutate_or_share_nested_input(sample, kind, filename):
    record = sample[kind]
    before = copy.deepcopy(record)
    projected = compact_record(filename, record)
    assert record == before
    projected["backend_outcomes"][0]["attempts"].clear()
    assert record == before


def test_shared_backend_objects_are_compacted_without_losing_attempts(sample):
    record = sample["proposal"]
    record["backend_outcomes"][0] = record["proposals"][0]["backend"]
    before = copy.deepcopy(record)
    projected = compact_record("proposals.jsonl", record)
    expected = {**sample["metadata"], "result_storage": "parsed"}
    assert projected["proposals"][0]["backend"] == expected
    assert projected["backend_outcomes"][0] == expected
    assert record == before


def test_other_stage_records_keep_raw_results_and_return_independent_copy(sample):
    record = sample["proposal"]
    projected = compact_record("events.jsonl", record)
    assert projected == record
    projected["backend_outcomes"][0]["attempts"].clear()
    assert record["backend_outcomes"][0]["attempts"]
