"""Tests for BenchTrace grounding validation in check_reflection."""
from tools.sie import check_reflection as cr


def test_benchtrace_grounded_passes():
    """All findings reference real trace IDs -> grounded_ratio=1.0, pass=True."""
    refl = {"findings": [
        {"text": "test t1 flaky", "trace_refs": ["tr_001"]},
        {"text": "build slow", "trace_refs": ["tr_002"]}
    ]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001", "tr_002"],
                              threshold=0.5)
    assert out["pass"] is True
    assert out["grounded_ratio"] == 1.0
    assert out["ungrounded"] == []


def test_benchtrace_fabricated_fails():
    """Findings reference non-existent trace IDs -> grounded_ratio=0.0, pass=False."""
    refl = {"findings": [
        {"text": "imagined issue", "trace_refs": ["tr_999"]},  # does not exist
        {"text": "no ref at all", "trace_refs": []}
    ]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001"], threshold=0.5)
    assert out["pass"] is False
    assert out["grounded_ratio"] == 0.0
    assert len(out["ungrounded"]) == 2
    # Check that bad refs are recorded
    assert any("tr_999" in str(item) for item in out["ungrounded"])


def test_benchtrace_mixed_grounding():
    """Mix of grounded and ungrounded findings."""
    refl = {"findings": [
        {"text": "valid finding", "trace_refs": ["tr_001"]},
        {"text": "fabricated", "trace_refs": ["tr_999"]},
        {"text": "no refs", "trace_refs": []}
    ]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001", "tr_002"],
                              threshold=0.5)
    assert out["pass"] is False
    assert out["grounded_ratio"] == 1.0 / 3.0
    assert len(out["ungrounded"]) == 2


def test_benchtrace_threshold_boundary():
    """Test grounded_ratio == threshold (edge case)."""
    refl = {"findings": [
        {"text": "valid", "trace_refs": ["tr_001"]},
        {"text": "invalid", "trace_refs": ["tr_999"]}
    ]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001"],
                              threshold=0.5)
    assert out["grounded_ratio"] == 0.5
    assert out["pass"] is True  # ratio >= threshold


def test_benchtrace_multiple_refs_per_finding():
    """Finding with multiple trace refs, at least one valid -> grounded."""
    refl = {"findings": [
        {"text": "complex issue", "trace_refs": ["tr_999", "tr_001", "tr_888"]},
        {"text": "another", "trace_refs": ["tr_002"]}
    ]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001", "tr_002"],
                              threshold=0.5)
    assert out["grounded_ratio"] == 1.0
    assert out["pass"] is True


def test_benchtrace_empty_findings():
    """Empty findings list -> ratio=0.0, pass=False."""
    refl = {"findings": []}
    out = cr.check_benchtrace(refl, available_traces=["tr_001"],
                              threshold=0.5)
    assert out["pass"] is False
    assert out["grounded_ratio"] == 0.0
    assert out["ungrounded"] == []


def test_benchtrace_no_findings_key():
    """Missing 'findings' key -> empty findings, ratio=0.0."""
    refl = {}
    out = cr.check_benchtrace(refl, available_traces=["tr_001"],
                              threshold=0.5)
    assert out["pass"] is False
    assert out["grounded_ratio"] == 0.0
