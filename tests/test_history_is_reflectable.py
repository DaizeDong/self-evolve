"""History is the only evidence the reflectors get, so it has to contain evidence.

WHY THIS FILE EXISTS. Every FAILING branch of the loop wrote a real reason into history; every
SUCCEEDING branch wrote the constant string "accepted". A run that went well therefore produced a
history that was a column of identical words, and the reflectors, asked to diagnose an improvement
direction from "round 1 accepted, round 2 accepted, ...", returned nothing. The loop had less to
reflect on the better it did.

Rounds that ended in a static reject appended nothing at all, so a barren round left a HOLE: the
history jumped from 4 to 6. The reflectors read that as possible data loss rather than as a round
that produced no proposal, and said so.

Both were found by the reflectors themselves, once their output was finally being written to disk,
six rounds running and in two languages. These tests pin what they asked for.
"""
from __future__ import annotations

import inspect

from tools.sie.statemachine import _round_record, run_loop


def test_an_accepted_round_records_what_changed_not_just_that_it_passed():
    rec = _round_record(7, "accepted", True,
                        props=[{"file_rel": "scripts/score.py", "new_content": "..."}],
                        dec={"decision": "ACCEPT", "evalue": 42.5, "reason": "e-process cleared"})
    assert rec["files_changed"] == ["scripts/score.py"]
    assert rec["evalue"] == 42.5
    assert rec["decision"] == "ACCEPT"
    # The point of the whole change: a reflector reading this can name a file and a number.
    assert set(rec) > {"round", "summary", "passed"}, (
        "an accepted round still carries only the three fields the reflectors called too sparse")


def test_a_barren_round_leaves_a_record_instead_of_a_hole():
    rec = _round_record(5, "the proposer produced no admissible proposal", False, phase="PROPOSE")
    assert rec["round"] == 5 and rec["passed"] is False
    assert rec["phase"] == "PROPOSE", "a barren round must say WHERE it died, or it reads as data loss"


def test_every_static_reject_site_appends_to_history():
    """The hole came from four sites, and fixing three of them would leave the same symptom.

    Reads the source because the alternative is driving a live loop, and because the failure mode is
    precisely "one site was missed".
    """
    src = inspect.getsource(run_loop)
    lines = src.split("\n")
    reject_lines = [i for i, l in enumerate(lines) if '"type": "STATIC_REJECT"' in l]
    assert len(reject_lines) >= 4, "expected the four static-reject sites; found %d" % len(reject_lines)

    # Each site is checked INDIVIDUALLY, within its own few lines. Counting records against rejects
    # across the whole function does not work: the accept branches also append, so deleting one
    # reject's record still satisfies a total-count comparison. Poisoning proved exactly that, and a
    # check that survives the poison is not checking the thing it was written for.
    for i in reject_lines:
        window = "\n".join(lines[i:i + 12])
        assert "history.append(_round_record(rnd," in window, (
            "the static-reject site at run_loop line %d does not append to history, so a round "
            "dying there leaves a hole the reflectors read as data loss:\n%s" % (i, window))


def test_no_accept_branch_writes_a_bare_constant_any_more():
    """The regression itself. Any of these literals reappearing means the column of identical words
    is back for that tier."""
    src = inspect.getsource(run_loop)
    for bad in ('{"round": rnd, "summary": "accepted", "passed": True}',
                '{"round": rnd, "summary": "B ACCEPT", "passed": True}',
                '{"round": rnd, "summary": "C ACCEPT", "passed": True}'):
        assert bad not in src, "an accept branch went back to a bare constant summary: %s" % bad


def test_the_record_stays_json_serializable():
    """It is written to reflections/history and shipped to an agent as JSON; a value that cannot be
    serialized would take out the round rather than the record."""
    import json
    rec = _round_record(1, "accepted", True,
                        props=[{"file_rel": "a.py"}, {"no_file_rel": True}],
                        dec={"decision": "ACCEPT", "evalue": 1.0})
    json.dumps(rec)
    assert rec["files_changed"] == ["a.py"], "a proposal without file_rel must be skipped, not crash"


def test_missing_inputs_degrade_to_the_old_shape_rather_than_raising():
    """Not every call site has props or dec. Those must still produce a usable entry."""
    rec = _round_record(2, "accepted", True)
    assert rec == {"round": 2, "summary": "accepted", "passed": True}
    assert _round_record(3, "x", False, props=[], dec=None)["passed"] is False
