"""A change the test signal cannot see must reach a human, not be reported as refused.

WHY. The A-tier e-process returns its null value, exactly 1.0, in two completely different
situations: it weighed evidence and found it wanting, and it received no evidence at all. Both used
to come out as REJECT with "insufficient evidence", which states "this change is not an improvement"
when the truthful statement is "this instrument cannot see this change".

It is not hypothetical. The calibration seeds 21 defects whose ADMISSION CRITERION is that the
target's own 1160 tests stay green, because every real defect ever found in this codebase was
invisible to its suite until a human looked. A correct repair of such a defect flips zero tests, so
every diff is zero, so e stays at 1.0. Measured: the gate needs about ten tests to go red-to-green
before e clears 1/alpha = 20, and this defect class supplies zero. Two runs against a pinned commit
refused 8 of 8 proposals this way while hidden oracles confirmed several were correct repairs.

Iron law 4 already provides the human arm; this only stops the loop from claiming it adjudicated
something it never measured.
"""
from __future__ import annotations

from tools.sie.acceptor import decide
from tools.sie.state import RunState


def _st():
    return RunState(run_id="r", phase="JUDGE", round=1, parent_vid=None, tier="A")


P = {"alpha": 0.05}


def test_zero_movement_routes_to_human_rather_than_refusing():
    """THE LOAD BEARING CASE: a correct repair of a suite-invisible defect."""
    d = decide([(1.0, 1.0)] * 1160, "A", _st(), P)
    assert d["force_review"] is True
    assert d["degrade_reason"] == "unobservable-by-tier-A"
    assert d["evalue"] == 1.0
    assert "blind spot" in d["reason"]


def test_movement_that_is_merely_insufficient_still_refuses_outright():
    """NEGATIVE CONTROL, and the one that matters most. Three tests went red to green: the signal DID
    observe the change and the evidence genuinely did not reach the bar. Sending this to a human too
    would turn the escape hatch into the default path and make the distinction meaningless."""
    d = decide([(1.0, 1.0)] * 1157 + [(0.0, 1.0)] * 3, "A", _st(), P)
    assert d["decision"] == "REJECT"
    assert d["force_review"] is False, "observed-but-weak evidence must not be laundered as unseen"
    assert d["evalue"] > 1.0


def test_a_regression_is_still_refused_flatly_and_never_escalated():
    """A change that turns tests red is refused by the hard gate. It must not reach a human as an
    open question; the answer is already known."""
    d = decide([(1.0, 1.0)] * 1157 + [(1.0, 0.0)] * 3, "A", _st(), P)
    assert d["decision"] == "REJECT" and d["force_review"] is False
    assert "no-regression" in d["reason"]


def test_a_genuine_improvement_is_still_accepted():
    """The gate must still be able to say yes, or this change traded one stuck verdict for another."""
    d = decide([(1.0, 1.0)] * 1150 + [(0.0, 1.0)] * 10, "A", _st(), P)
    assert d["decision"] == "ACCEPT" and d["force_review"] is False


def test_an_empty_pairing_is_not_the_same_as_an_unmoved_one():
    """No pairs at all means evaluation produced nothing, which is a different failure from
    evaluation producing pairs that did not move. The first is a broken measurement."""
    d = decide([], "A", _st(), P)
    assert d["decision"] == "REJECT" and d["reason"] == "empty paired"
    assert d["force_review"] is False

# --------------------------------------------------------------------------- the consumer side
#
# The tests above check that the ACCEPTOR raises the flag. They all passed while a full calibration
# run still produced 8 REJECT and 0 PAUSE_FOR_HUMAN, because apply_acceptor_outcome branched on the
# decision STRING and never read the field. Producer fixed, consumer not. These drive the consumer.

from tools.sie.statemachine import apply_acceptor_outcome


def _rs():
    return RunState(run_id="r", phase="JUDGE", round=1, parent_vid=None, tier="A")


def test_force_review_on_a_reject_routes_to_the_human_arm():
    """THE ONE THAT WAS MISSING. A REJECT carrying force_review is a blind spot, not a refusal."""
    nxt = apply_acceptor_outcome(_rs(), {"decision": "REJECT", "evalue": 1.0, "reason": "",
                                         "force_review": True}, {"continue_count_cap": 5})
    assert nxt == "PAUSE_FOR_HUMAN", (
        "the acceptor flagged this as unobservable and the state machine handled it as an ordinary "
        "refusal, which is how 8 of 8 flagged rounds reached REJECT in a live run")


def test_an_ordinary_reject_still_loops():
    """NEGATIVE CONTROL. If every REJECT reached a human the escape hatch would be the default path."""
    nxt = apply_acceptor_outcome(_rs(), {"decision": "REJECT", "evalue": 1.6, "reason": "",
                                         "force_review": False}, {"continue_count_cap": 5})
    assert nxt == "LOOP"


def test_the_producer_and_consumer_agree_end_to_end():
    """Drives the real acceptor into the real state machine, because each was individually correct
    while the pair was broken. No hand written decision dict anywhere in this test."""
    unobserved = decide([(1.0, 1.0)] * 1160, "A", _st(), P)
    assert apply_acceptor_outcome(_rs(), unobserved, {"continue_count_cap": 5}) == "PAUSE_FOR_HUMAN"

    weak = decide([(1.0, 1.0)] * 1157 + [(0.0, 1.0)] * 3, "A", _st(), P)
    assert apply_acceptor_outcome(_rs(), weak, {"continue_count_cap": 5}) == "LOOP"

    good = decide([(1.0, 1.0)] * 1150 + [(0.0, 1.0)] * 10, "A", _st(), P)
    assert apply_acceptor_outcome(_rs(), good, {"continue_count_cap": 5}) == "ARCHIVE"
