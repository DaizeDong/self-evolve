"""Generated resume, holdout, counter and bounded-grading contracts."""
import copy
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time

import pytest

from tools.make_fixtures import immutable_samples, source13_repair_inputs, synthetic_artifact
from tools.sie import anchors, evaluate, events, gate_human, immutable, profile, runtime_data
from tools.sie import selfboot, statemachine, verifiable
from tools.sie.state import RunState


def verified_anchors():
    samples = synthetic_artifact(24)["sections"][0]["anchors"]
    return [{**item, "anchor_id": str(index), "verified": True,
             "verification_complete": True, "observed": item["expected"]}
            for index, item in enumerate(samples)]


@pytest.mark.parametrize("round_number", [5, 6, 9, 11])
def test_due_holdout_blocks_acceptance_even_off_cadence(tmp_path, monkeypatch, round_number):
    visible = verified_anchors()
    context = {"tier": "B", "round": round_number, "K": 5, "_holdout_due": True,
               "anchors_visible": visible,
               "base_scores": {item["anchor_id"]: 0.0 for item in visible},
               "with_scores": {item["anchor_id"]: 1.0 for item in visible},
               "holdout_base": 1.0, "holdout_with": 0.0}
    result = evaluate.evaluate(context)
    monkeypatch.setattr(gate_human, "enqueue", lambda *args: "synthetic-review")
    state = RunState(run_id="synthetic-review", phase="ACCEPT", round=round_number,
                     parent_vid="base", tier="B")
    route = statemachine.resolve_accept(state, result, {}, run_dir=str(tmp_path))
    assert result["holdout_gain"] == 0.0 and result["holdout_missing"] is False
    assert route["next_state"] == "9.5"


@pytest.mark.parametrize("due", [False, True])
def test_explicit_schedule_controls_missing_holdout(due):
    result = evaluate.evaluate({"tier": "B", "round": 10, "K": 5,
                                "_holdout_due": due, "anchors_visible": []})
    assert result["holdout_missing"] is due
    assert result["holdout_gain"] is None


@pytest.mark.parametrize("round_number,due", [(6, True), (10, False)])
def test_real_context_carries_durable_holdout_schedule(tmp_path, round_number, due):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "artifact.json").write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
    prof = profile.run_profile(str(candidate), "synthetic", include_exec_probe=False)
    context = statemachine._btier_round_context(
        prof, str(candidate), str(candidate), round_number,
        {"holdout_K": 5, "_holdout_due": due}, lambda anchor: anchor["expected"], "base")
    result = evaluate.evaluate(context)
    assert context["_holdout_due"] is due
    assert result["holdout_missing"] is False
    assert result["holdout_gain"] == (0.0 if due else None)


def test_resume_after_rejected_due_round_consumes_next_measurement(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "artifact.json").write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
    change = source13_repair_inputs()["loop_change"]
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(candidate))
    monkeypatch.setattr(statemachine, "run_profile", lambda target, ref:
                        profile.run_profile(target, ref, include_exec_probe=False))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(change)])
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(change)])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)
    options = {"fetcher": lambda anchor: anchor["expected"],
               "_extra_params": {"static_reject_circuit": 100, "forced_review_circuit": 100,
                                  "no_progress_circuit_N": 100}}
    initial = statemachine.run_loop(str(candidate), "synthetic", "overdue-resume", max_rounds=0, **options)
    for number in range(1, 6):
        events.append_event(initial["run_dir"], {"type": "ROUND_BEGIN", "round": number})
        events.append_event(initial["run_dir"], {"type": "STATIC_REJECT", "static_reject_delta": 1})
    observed = []
    original = statemachine.evaluate

    def capture(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        observed.append((context["round"], result["holdout_gain"], result["holdout_missing"]))
        return result

    monkeypatch.setattr(statemachine, "evaluate", capture)
    resumed = statemachine.run_loop(str(candidate), "synthetic", "overdue-resume", max_rounds=1, **options)
    assert observed == [(6, 0.0, False)]
    assert statemachine._resume_records(resumed["run_dir"])[1] == 6



@pytest.fixture
def isolated_holdout_loop(tmp_path, monkeypatch):
    private = tmp_path / "generated-private"
    data = private / "data"
    data.mkdir(parents=True)
    (private / ".git").mkdir()
    monkeypatch.setenv("SELF_EVOLVE_DATA_DIR", str(data))

    def prove(value, expected_repo=None):
        path = runtime_data._safe_path(value)
        assert path.is_relative_to(private)
        assert expected_repo is None or expected_repo == private
        return path, private

    monkeypatch.setattr(runtime_data, "verify_directory", prove)
    monkeypatch.setattr(gate_human, "enqueue", lambda *args: "synthetic-holdout-review")
    candidate = data / "grader-work" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "artifact.json").write_text(json.dumps(synthetic_artifact(30)), encoding="utf-8")
    change = source13_repair_inputs()["loop_change"]
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(candidate))
    monkeypatch.setattr(statemachine, "run_profile", lambda target, ref:
                        profile.run_profile(target, ref, include_exec_probe=False))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(change)])
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(change)])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)
    options = {"fetcher": lambda anchor: anchor["expected"],
               "_extra_params": {"static_reject_circuit": 100, "forced_review_circuit": 100,
                                  "no_progress_circuit_N": 100}}
    run_id = "interrupted-holdout"
    initial = statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=0, **options)
    for number in range(1, 6):
        events.append_event(initial["run_dir"], {"type": "ROUND_BEGIN", "round": number})
        events.append_event(initial["run_dir"], {"type": "STATIC_REJECT", "static_reject_delta": 1})
    return candidate, run_id, options, initial


@pytest.mark.parametrize("interruption", ["evaluate", "resolve", "before_decision", "after_decision"])
def test_interrupted_holdout_requires_durable_decision(isolated_holdout_loop, monkeypatch, interruption):
    candidate, run_id, options, initial = isolated_holdout_loop
    original_evaluate = statemachine.evaluate
    original_resolve = statemachine.resolve_accept
    original_step = statemachine._step

    class InterruptedRound(Exception):
        pass

    def interrupt(*args, **kwargs):
        raise InterruptedRound(interruption)

    def interrupt_decision(run_dir, event):
        if event["type"] in {"ACCEPT", "REJECT", "CONTINUE", "PAUSE_FOR_HUMAN"}:
            if interruption == "after_decision":
                original_step(run_dir, event)
            raise InterruptedRound(interruption)
        return original_step(run_dir, event)

    if interruption == "evaluate":
        monkeypatch.setattr(statemachine, "evaluate", interrupt)
    elif interruption == "resolve":
        monkeypatch.setattr(statemachine, "resolve_accept", interrupt)
    else:
        monkeypatch.setattr(statemachine, "_step", interrupt_decision)
    with pytest.raises(InterruptedRound, match=interruption):
        statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=1, **options)
    assert events.replay(initial["run_dir"]).round == 6
    consumed = interruption == "after_decision"
    assert statemachine._resume_records(initial["run_dir"])[1] == (6 if consumed else 0)

    monkeypatch.setattr(statemachine, "resolve_accept", original_resolve)
    monkeypatch.setattr(statemachine, "_step", original_step)
    observations = []

    def capture(context, *args, **kwargs):
        result = original_evaluate(context, *args, **kwargs)
        observations.append((context["round"], context["_holdout_due"], result["holdout_gain"]))
        return result

    monkeypatch.setattr(statemachine, "evaluate", capture)
    resumed = statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=1, **options)
    assert observations == [(7, not consumed, None if consumed else 0.0)]
    assert resumed["accepted_versions"] == []
    assert statemachine._resume_records(initial["run_dir"])[1] == (6 if consumed else 7)


@pytest.mark.parametrize("next_state,event_type", [("9.5", "PAUSE_FOR_HUMAN"), ("6", "CONTINUE")])
def test_completed_holdout_outcome_consumes_schedule(isolated_holdout_loop, monkeypatch,
                                                    next_state, event_type):
    candidate, run_id, options, initial = isolated_holdout_loop
    original = statemachine.resolve_accept

    def route(*args, **kwargs):
        result = original(*args, **kwargs)
        return {**result, "next_state": next_state, "reason": "synthetic holdout outcome"}

    monkeypatch.setattr(statemachine, "resolve_accept", route)
    statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=1, **options)
    recorded = [json.loads(line) for line in
                (Path(initial["run_dir"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    outcome = [event for event in recorded if event["type"] == event_type][-1]
    assert event_type != "PAUSE_FOR_HUMAN" or outcome["static_reject_reset"] is True
    assert statemachine._resume_records(initial["run_dir"])[1] == 6
    seen = []
    original_evaluate = statemachine.evaluate

    def observe(context):
        seen.append((context["round"], context["_holdout_due"]))
        return original_evaluate(context)

    monkeypatch.setattr(statemachine, "evaluate", observe)
    statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=1, **options)
    assert seen == [(7, False)]
    assert statemachine._resume_records(initial["run_dir"])[1] == 6


@pytest.mark.parametrize("unconsumed", ["next_round", "unevaluated_pause", "unavailable"])
def test_orphan_holdout_marker_does_not_consume_schedule(isolated_holdout_loop, unconsumed):
    _, _, _, initial = isolated_holdout_loop
    run_dir = initial["run_dir"]
    events.append_event(run_dir, {"type": "ROUND_BEGIN", "round": 6})
    events.append_event(run_dir, {"type": "HOLDOUT_MEASURED", "holdout_round": 6})
    if unconsumed == "next_round":
        events.append_event(run_dir, {"type": "ROUND_BEGIN", "round": 7})
        events.append_event(run_dir, {"type": "CONTINUE", "continue_count_delta": 1})
    elif unconsumed == "unevaluated_pause":
        events.append_event(run_dir, {"type": "PAUSE_FOR_HUMAN", "forced_review_delta": 1})
    else:
        events.append_event(run_dir, {"type": "BASELINE_UNAVAILABLE", "reason": "synthetic unavailable"})
    assert statemachine._resume_records(run_dir)[1] == 0


@pytest.fixture
def tiny_frozen_repo(tmp_path, monkeypatch):
    names = ("acceptor.py", "events.py")
    monkeypatch.setattr(immutable, "IMMUTABLE_RELPATHS", names)
    monkeypatch.setattr(immutable, "_IMMUTABLE_SET", frozenset(names))
    from test_immutable import _init_repo_with_sie
    return _init_repo_with_sie(tmp_path), tmp_path / "frozen"


def test_repeat_frozen_materialization_reuses_readonly_committed_bytes(tiny_frozen_repo):
    repository, frozen = tiny_frozen_repo
    args = ("HEAD", str(repository / "tools/sie"), str(frozen))
    first = immutable.materialize_frozen(*args)
    before = {path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
              for path in frozen.iterdir()}
    second = immutable.materialize_frozen(*args)
    assert first == second
    assert before == {path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                      for path in frozen.iterdir()}
    assert all(not path.stat().st_mode & stat.S_IWUSR for path in frozen.iterdir())


def test_repeat_frozen_materialization_refuses_changed_bytes(tiny_frozen_repo):
    repository, frozen = tiny_frozen_repo
    args = ("HEAD", str(repository / "tools/sie"), str(frozen))
    immutable.materialize_frozen(*args)
    altered = frozen / "acceptor.py"
    os.chmod(altered, 0o600)
    altered.write_bytes(b"# Generated tampered decision body\n")
    os.chmod(altered, 0o444)
    before = altered.read_bytes()
    with pytest.raises(immutable.ImmutableViolation, match="acceptor.py"):
        immutable.materialize_frozen(*args)
    assert altered.read_bytes() == before


def test_selfboot_can_reopen_its_existing_frozen_run(tiny_frozen_repo, tmp_path):
    repository, _ = tiny_frozen_repo
    runs = runtime_data.private_root() / "targets" / tmp_path.name / "runs"
    first = selfboot.selfboot_init(str(repository), "HEAD", "synthetic-resume", str(runs))
    second = selfboot.selfboot_init(str(repository), "HEAD", "synthetic-resume", str(runs))
    assert first["candidate_worktree"] == second["candidate_worktree"]
    assert first["frozen_dir"] == second["frozen_dir"]
    assert first["frozen_digests"] == second["frozen_digests"]
    assert second["supervisor"] is not None


def test_continue_resets_static_rejections_in_durable_replay(tmp_path):
    run = tmp_path / "counter-run"
    run.mkdir()
    for event in [{"type": "INIT", "run_id": "synthetic-counter", "tier": "B"},
                  {"type": "STATIC_REJECT", "static_reject_delta": 1},
                  {"type": "CONTINUE", "continue_count_delta": 1, "no_progress_delta": 1},
                  {"type": "STATIC_REJECT", "static_reject_delta": 1}]:
        events.append_event(str(run), event)
    state = events.replay(str(run))
    assert state.static_reject == 1
    assert state.continue_count == 1 and state.no_progress == 1
    assert statemachine.circuit_check(state, {"static_reject_circuit": 2}) != "static_reject_circuit"


@pytest.mark.parametrize("grader", [verifiable.grade_pytest, evaluate._grade_pytest_per_task])
def test_raw_candidate_grader_enforces_a_timeout(tmp_path, monkeypatch, grader):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    original_run = subprocess.run

    def timeout(command, **kwargs):
        if command[1:3] != ["-m", "pytest"]:
            return original_run(command, **kwargs)
        limit = kwargs.get("timeout")
        assert isinstance(limit, (int, float)) and math.isfinite(limit) and limit > 0
        raise subprocess.TimeoutExpired(command, limit)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        grader(str(candidate))


@pytest.mark.parametrize("tier,available", [("A", True), ("B", True), ("C", True),
                                           ("A", False), ("C", False)])
def test_only_evaluated_human_review_resets_static_streak(tmp_path, monkeypatch, tier, available):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    case = source13_repair_inputs()
    prof = {**copy.deepcopy(case["profile"]), "tier": tier}
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(candidate))
    monkeypatch.setattr(statemachine, "run_profile", lambda *args: prof)
    monkeypatch.setattr(statemachine, "_parent_baseline", lambda *args:
                        copy.deepcopy(case["grade"]) if available else None)
    monkeypatch.setattr(evaluate, "_grade_pytest_per_task", lambda *args: copy.deepcopy(case["grade"]))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(case["loop_change"])])
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(case["loop_change"])])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)
    monkeypatch.setattr(gate_human, "enqueue", lambda *args: "synthetic-review")
    visible = verified_anchors()
    context = {"tier": "B", "round": 6, "K": 5, "_holdout_due": True,
               "anchors_visible": visible,
               "base_scores": {item["anchor_id"]: 0.0 for item in visible},
               "with_scores": {item["anchor_id"]: 1.0 for item in visible},
               "holdout_base": 1.0, "holdout_with": 0.0}
    monkeypatch.setattr(statemachine, "_btier_round_context", lambda *args: context)
    monkeypatch.setattr(evaluate, "inject_judge_scores", lambda **kwargs:
                        {"judge_gain": 1.0, "alpha": 0.5})
    monkeypatch.setattr(evaluate, "evaluate_c_tier", lambda **kwargs:
                        {"available": available, "no_regression": True,
                         "consistency_paired": [(0.0, 1.0)] * 24, "coverage": 1.0})
    if tier != "B":
        monkeypatch.setattr(statemachine, "decide", lambda *args:
                            {"decision": "FORCE_HUMAN" if tier == "A" else "ACCEPT",
                             "evalue": 100.0, "force_review": True,
                             "reason": "synthetic evaluated review"})
    run_id = "synthetic-review-streak"
    initial = statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=0)
    for _ in range(5):
        events.append_event(initial["run_dir"], {"type": "STATIC_REJECT", "static_reject_delta": 1})
    result = statemachine.run_loop(str(candidate), "synthetic", run_id, max_rounds=1)
    assert result["accepted_versions"] == [] and result["final_phase"] == "PAUSE_FOR_HUMAN"
    events.append_event(result["run_dir"], {"type": "STATIC_REJECT", "static_reject_delta": 1})
    state = events.replay(result["run_dir"])
    assert state.static_reject == (1 if available else 6)
    assert state.forced_review == 1 and state.continue_count == 0 and state.no_progress == 0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_invalid_grader_timeout_cannot_disable_the_bound(monkeypatch, value):
    monkeypatch.setenv("SIE_GRADER_TIMEOUT", value)
    with pytest.raises(ValueError):
        verifiable.grader_timeout()


@pytest.mark.parametrize("grader", [verifiable.grade_pytest, evaluate._grade_pytest_per_task])
def test_native_hanging_pytest_is_terminated(tmp_path, monkeypatch, grader):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    source = "def test_synthetic_loop():\n    while True:\n        pass\n"
    (candidate / "test_loop.py").write_text(source, encoding="utf-8")
    monkeypatch.setenv("SIE_GRADER_TIMEOUT", "2")
    original_run, original_popen = subprocess.run, subprocess.Popen
    children, grading_seconds = [], []

    def bounded_run(command, **kwargs):
        if command[1:3] == ["-m", "pytest"]:
            assert kwargs.get("timeout") == 2.0, "Refuse to launch an unbounded negative control"
            started = time.monotonic()
            try:
                return original_run(command, **kwargs)
            finally:
                grading_seconds.append(time.monotonic() - started)
        return original_run(command, **kwargs)

    def record_popen(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        command = args[0] if args else kwargs["args"]
        if command[1:3] == ["-m", "pytest"]:
            children.append(child)
        return child

    monkeypatch.setattr(subprocess, "run", bounded_run)
    monkeypatch.setattr(subprocess, "Popen", record_popen)
    with pytest.raises(subprocess.TimeoutExpired):
        grader(str(candidate))
    assert grading_seconds and max(grading_seconds) < 15
    assert children and all(child.poll() is not None for child in children)


@pytest.mark.parametrize("self_mode", [False, True])
def test_candidate_timeout_refuses_acceptance_and_restores_parent(tmp_path, monkeypatch, self_mode):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    case = source13_repair_inputs()
    decisions = []
    monkeypatch.setattr(statemachine, "make_worktree", lambda *args: str(candidate))
    monkeypatch.setattr(statemachine, "run_profile", lambda *args: copy.deepcopy(case["profile"]))
    monkeypatch.setattr(statemachine, "_parent_baseline", lambda *args: copy.deepcopy(case["grade"]))
    monkeypatch.setattr(statemachine, "reflect", lambda *args, **kwargs: [dict(case["loop_change"])])
    monkeypatch.setattr(statemachine, "propose", lambda *args, **kwargs: [dict(case["loop_change"])])
    monkeypatch.setattr(statemachine, "check", lambda *args: True)

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic-pytest", 2)

    monkeypatch.setattr(statemachine, "evaluate", timed_out)
    monkeypatch.setattr(statemachine, "decide", lambda *args: decisions.append(args))

    class FrozenSupervisor:
        grade = staticmethod(timed_out)

        def decide(self, *args):
            decisions.append(args)

    options = {"supervisor": FrozenSupervisor(), "candidate_worktree": str(candidate)} if self_mode else {}
    result = statemachine.run_loop(str(candidate), "synthetic", "timeout-refusal", max_rounds=1, **options)
    assert result["accepted_versions"] == [] and decisions == []
    assert not (candidate / case["loop_change"]["file_rel"]).exists()
    records = [json.loads(line) for line in (Path(result["run_dir"]) / "events.jsonl").read_text().splitlines()]
    assert any(row["type"] == "REJECT" and "timed out" in row.get("reason", "") for row in records)


def test_generated_guardrail_source_is_reproducible():
    from tools.make_fixtures import resume_guardrail_test_source
    assert resume_guardrail_test_source() == Path(__file__).read_text(encoding="utf-8")
