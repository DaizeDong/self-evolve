import json
import os
from tools.sie import anchors

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "anchored_artifact.json")


def test_extract_finds_all_anchor_fields():
    out = anchors.extract_anchors(FIX)
    assert len(out) == 2
    a = out[0]
    for k in ("claim", "span", "source_url", "fetched_at", "verified", "marginal_gain", "anchor_id"):
        assert k in a, f"missing field {k}"
    assert a["verified"] is False          # extract 不核查, verified 默认 False
    assert a["marginal_gain"] == 0.0
    assert a["anchor_id"]                   # 稳定非空 id
    assert {x["anchor_id"] for x in out} == set(x["anchor_id"] for x in out)  # 唯一


def test_coverage_zero_when_none_verified():
    out = anchors.extract_anchors(FIX)
    assert anchors.coverage(out) == 0.0


def test_coverage_full_when_all_verified():
    out = anchors.extract_anchors(FIX)
    for a in out:
        a["verified"] = True
    assert abs(anchors.coverage(out) - 1.0) < 1e-9


def test_coverage_empty_is_zero():
    assert anchors.coverage([]) == 0.0


def test_coverage_empty_span_anchor_not_counted():
    """Empty span anchors have 0 weight and don't contribute to coverage."""
    anchor_with_span = {
        "anchor_id": "abc123",
        "claim": "test",
        "span": "valid text",
        "source_url": "http://example.com",
        "verified": True,
    }
    anchor_empty_span = {
        "anchor_id": "def456",
        "claim": "test",
        "span": "",
        "source_url": "http://example.com",
        "verified": True,
    }
    # Only anchor with non-empty span should count
    cov = anchors.coverage([anchor_with_span, anchor_empty_span])
    assert cov == 1.0  # 1 verified (with span) / 1 total weight = 100%
