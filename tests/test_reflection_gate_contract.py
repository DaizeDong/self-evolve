"""The reflect stage's output must pass the gate that stands in front of the proposer.

WHY THIS FILE EXISTS. `merged_findings`, the key the parallel MARS path actually produces, was
missing from the gate's key list for the whole life of that path. The effect was not a stricter
gate, it was an INVERTED one: a fanout that produced real findings arrived as
{"merged_findings": [...]}, matched nothing, and was rejected, while a fanout that produced NOTHING
fell back to serial reflect(), which manufactures a placeholder out of the last history summary,
and THAT passed. The loop only ever forwarded its empty reflections. Three calibration runs made
every one of their accepted changes from a one line stale summary such as "B ACCEPT".

WHY 651 TESTS MISSED IT. Forcing check() to return False for everything turned only 3 of them red,
and all three drove the serial shape. test_reflect_fanout.py asserted on meta_aggregate's return
value and stopped there; test_reflect_propose.py asserted on a hand written literal. Neither ever
carried a real fanout result across into the gate, and the defect lived exactly in that gap.

So every test here starts from a value produced BY THE REAL CODE, never from a literal typed by
whoever wrote the test. A literal is a restatement of what the author already believed.
"""
from __future__ import annotations

from tools.sie.check_reflection import check, _REFLECTION_CONTENT_KEYS
from tools.sie.reflect import meta_aggregate, reflect
from tools.sie.backends.llm import _extract_findings


def _parallel_refs(reflections):
    """Rebuild exactly what statemachine.py hands the gate on the parallel path.

    Kept as one helper so the shape is asserted in one place; if statemachine ever changes how it
    wraps the aggregate, test_the_wrapper_here_still_matches_the_loop below goes red.
    """
    agg = meta_aggregate(reflections)
    return [{"merged_findings": agg.get("merged_findings", [])}]


def test_a_successful_parallel_reflection_passes_the_gate():
    """THE LOAD BEARING TEST. Real reflector output, through real aggregation, into the real gate."""
    fanout = [{"reflector": 0, "findings": ["freshness floors age at the collection cadence"],
               "family": "claude"},
              {"reflector": 1, "findings": ["evidence_origins folds lane aliases inconsistently"],
               "family": "codex"}]
    refs = _parallel_refs(fanout)
    kept = [r for r in refs if check(r, 0.5)]
    assert kept, ("a fanout that produced findings was rejected by the gate; the loop would emit "
                  "STATIC_REJECT and never call the proposer. refs=%r" % refs)


def test_an_empty_parallel_reflection_is_still_rejected():
    """NEGATIVE CONTROL. Widening the gate must not make it accept nothing at all, or the fuse that
    stops a stuck loop stops meaning anything."""
    refs = _parallel_refs([{"reflector": 0, "findings": [], "family": "claude"}])
    assert not [r for r in refs if check(r, 0.5)]
    assert not check({}, 0.5)
    assert not check({"reflector": 0, "family": "claude"}, 0.5)   # shape present, content absent


def test_the_serial_fallback_still_passes():
    """The other real producer. Both branches of the loop's reflect step must clear the gate."""
    first_round = reflect(".", [], n=1)
    assert [r for r in first_round if check(r, 0.5)], first_round
    with_history = reflect(".", [{"round": 5, "summary": "B ACCEPT", "passed": True}], n=1)
    assert [r for r in with_history if check(r, 0.5)], with_history


def test_everything_the_gate_admits_is_something_the_proposer_can_read():
    """The gate and the next stage must agree, in that direction.

    A reflection the gate admits but the proposer cannot extract findings from would be a silent
    dead end: the round is spent, no proposal appears, and the loop records a PROPOSE reject whose
    real cause is here. Checked against the live extractor rather than against a list of names.
    """
    fanout = [{"reflector": 0, "findings": ["a concrete finding"], "family": "claude"}]
    refs = _parallel_refs(fanout)
    assert [r for r in refs if check(r, 0.5)]
    assert _extract_findings(refs), ("the proposer extracted nothing from a reflection the gate "
                                     "admitted: %r" % refs)


def test_the_wrapper_here_still_matches_the_loop():
    """Guards the one thing this file cannot verify by construction: that _parallel_refs above is
    still what statemachine.py does. Reads the source, because the alternative is this whole file
    quietly testing a shape the loop stopped producing."""
    import inspect
    from tools.sie import statemachine
    src = inspect.getsource(statemachine.run_loop)
    assert 'refs = [{"merged_findings": agg.get("merged_findings", [])}]' in src, (
        "statemachine no longer wraps the aggregate the way this file assumes; update "
        "_parallel_refs to match, or these tests are green about a shape nothing produces")


def test_merged_findings_is_in_the_recognized_key_list():
    """The regression itself, stated once directly, so a future edit that drops the key names it."""
    assert "merged_findings" in _REFLECTION_CONTENT_KEYS
