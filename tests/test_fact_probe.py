"""Test fact_probe: code-based anchor verification -> B tier signal (resist prose claiming)."""
import os
import json
from pathlib import Path
from tools.sie.probes import fact_probe


def _write_artifact(tmp_path, n_anchors):
    """Write a test artifact.json with n_anchors structured anchors."""
    secs = []
    for i in range(n_anchors):
        secs.append({
            "text": f"fact {i}",
            "anchors": [
                {
                    "claim": f"c{i}",
                    "span": f"s{i}",
                    "source_url": f"https://h{i%3}.com/x",
                    "cik": str(i),
                    "period": "FY"
                }
            ]
        })
    p = tmp_path / "artifact.json"
    p.write_text(json.dumps({"sections": secs}), encoding="utf-8")
    return str(tmp_path)


def test_fact_probe_gives_b_signal_when_enough_anchors(tmp_path):
    """At least 24 anchors -> tier_signal='B'."""
    target = _write_artifact(tmp_path, 24)
    out = fact_probe.probe(target, base_ref="HEAD")
    assert out["tier_signal"] == "B"
    assert out["anchor_count"] == 24


def test_fact_probe_no_signal_below_min(tmp_path):
    """Below anchor_set_min (24) -> tier_signal=None."""
    target = _write_artifact(tmp_path, 5)
    out = fact_probe.probe(target, base_ref="HEAD")
    assert out["tier_signal"] is None
    assert out["anchor_count"] == 5


def test_fact_probe_ignores_prose_claiming_anchors(tmp_path):
    """Prose claiming anchors but no structured fields -> no signal (code-based, resist prose)."""
    p = tmp_path / "artifact.json"
    p.write_text(
        json.dumps({
            "sections": [{
                "text": "I have 100 verified anchors trust me",
                "no_anchor": True
            }]
        }),
        encoding="utf-8"
    )
    out = fact_probe.probe(str(tmp_path), base_ref="HEAD")
    assert out["tier_signal"] is None
    assert out["anchor_count"] == 0


def test_fact_probe_coverage_reflects_anchor_verification(tmp_path):
    """Coverage should reflect verified anchors (initially 0.0 since unverified)."""
    target = _write_artifact(tmp_path, 10)
    out = fact_probe.probe(target, base_ref="HEAD")
    # All anchors unverified by default -> coverage = 0.0
    assert out["verifiable_coverage"] == 0.0
    assert out["anchor_count"] == 10


def test_fact_probe_evidence_includes_scanned_files(tmp_path):
    """Evidence should document which files were scanned and the threshold."""
    target = _write_artifact(tmp_path, 24)
    out = fact_probe.probe(target, base_ref="HEAD")
    assert "evidence" in out
    assert "scanned_files" in out["evidence"]
    assert len(out["evidence"]["scanned_files"]) > 0
    assert "artifact.json" in out["evidence"]["scanned_files"][0]
    assert out["evidence"]["anchor_set_min"] == 24


def test_fact_probe_incomplete_anchor_fields_ignored(tmp_path):
    """Anchors missing claim/span/source_url -> ignored (code validation, not prose)."""
    p = tmp_path / "artifact.json"
    p.write_text(
        json.dumps({
            "sections": [{
                "text": "partial anchors",
                "anchors": [
                    # Missing source_url
                    {"claim": "c1", "span": "s1"},
                    # Missing claim
                    {"span": "s2", "source_url": "https://example.com"},
                    # Missing span
                    {"claim": "c3", "source_url": "https://example.com"},
                    # Complete
                    {"claim": "c4", "span": "s4", "source_url": "https://example.com"},
                ]
            }]
        }),
        encoding="utf-8"
    )
    out = fact_probe.probe(str(tmp_path), base_ref="HEAD")
    # Only the complete anchor should be counted
    assert out["anchor_count"] == 1


def test_fact_probe_duplicates_deduplicated(tmp_path):
    """Identical anchors -> deduplicated (extract_anchors already dedupes)."""
    p = tmp_path / "artifact.json"
    secs = [{
        "text": "duplicates",
        "anchors": [
            {"claim": "c1", "span": "s1", "source_url": "https://ex.com"},
            {"claim": "c1", "span": "s1", "source_url": "https://ex.com"},
            {"claim": "c1", "span": "s1", "source_url": "https://ex.com"},
        ]
    }]
    p.write_text(json.dumps({"sections": secs}), encoding="utf-8")
    out = fact_probe.probe(str(tmp_path), base_ref="HEAD")
    # Should be deduplicated to 1
    assert out["anchor_count"] == 1
