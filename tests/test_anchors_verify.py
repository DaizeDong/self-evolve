"""M2.4: TDD tests for edgar_cache.prepare_cache + anchors.verify_anchor.

All tests use injected fake fetchers — no real network calls, no real edgar import.
"""
import os
from tools.sie import edgar_cache, anchors


# ---------------------------------------------------------------------------
# edgar_cache tests
# ---------------------------------------------------------------------------

def test_prepare_cache_creates_dir_and_sets_env(tmp_path, monkeypatch):
    root = tmp_path / "edgar_run"
    p = edgar_cache.prepare_cache(str(root))
    assert os.path.isdir(p)
    assert os.environ.get("EDGAR_LOCAL_DATA_DIR") == p


def test_prepare_cache_clears_existing_nonempty(tmp_path):
    root = tmp_path / "edgar_run"
    os.makedirs(root, exist_ok=True)
    with open(root / "stale.bin", "wb") as f:
        f.write(b"old")
    sub = root / "sub"; os.makedirs(sub, exist_ok=True)
    with open(sub / "x.bin", "wb") as f:
        f.write(b"y")
    p = edgar_cache.prepare_cache(str(root))
    # After clear: dir exists but is empty (WinError 145 tolerant: must not crash)
    assert os.path.isdir(p)
    assert os.listdir(p) == []


def test_prepare_cache_returns_path_string(tmp_path):
    root = tmp_path / "ec"
    p = edgar_cache.prepare_cache(str(root))
    assert isinstance(p, str)
    assert p == str(root)


# ---------------------------------------------------------------------------
# verify_anchor tests — all use injected fetcher, zero network
# ---------------------------------------------------------------------------

def test_verify_anchor_pass_within_rel_tol():
    a = {
        "anchor_id": "x",
        "claim": "rev=1.2e9",
        "span": "rev",
        "source_url": "https://sec.gov/x",
        "metric": "Revenues",
        "expected": 1.20e9,
        "cik": "320193",
        "period": "FY2024",
    }
    def fetch(anchor):  # 1.205e9: 0.4% deviation — within 1% rel_tol
        return 1.205e9
    out = anchors.verify_anchor(a, fetcher=fetch)
    assert out["verified"] is True
    assert out["observed"] == 1.205e9
    assert out["fetched_at"]


def test_verify_anchor_fail_outside_tol():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "Revenues",
        "expected": 1.20e9,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: 2.0e9)  # 67% deviation
    assert out["verified"] is False


def test_verify_anchor_unfetchable_is_unverified():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "Revenues",
        "expected": 1.0,
        "cik": "1",
        "period": "FY2024",
    }
    def boom(_a):
        raise RuntimeError("network fail")
    out = anchors.verify_anchor(a, fetcher=boom)
    assert out["verified"] is False
    assert "error" in out["verify_reason"].lower()


def test_verify_anchor_absolute_tol_for_zero_expected():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": 0.0,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: 0.004)  # within abs_tol 0.01
    assert out["verified"] is True


def test_verify_anchor_absolute_tol_outside():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": 0.0,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: 0.02)  # outside abs_tol 0.01
    assert out["verified"] is False


def test_verify_anchor_fetcher_returns_none():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": 1.0,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: None)
    assert out["verified"] is False
    assert "observed" in out
    assert out["observed"] is None


def test_verify_anchor_returns_copy_not_mutate():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": 1.0,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: 1.0)
    # output is a copy — original should not have verify_reason key
    assert "verify_reason" not in a
    assert "verify_reason" in out


def test_verify_anchor_exact_boundary_rel_tol():
    """Exactly at 1% relative tolerance — should be verified (<=)."""
    expected = 100.0
    observed = 101.0  # exactly 1% — within boundary
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": expected,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: observed)
    assert out["verified"] is True


def test_verify_anchor_just_outside_rel_tol():
    """Slightly above 1% relative tolerance — should fail."""
    expected = 100.0
    observed = 101.01  # 1.01% deviation
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": expected,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: observed)
    assert out["verified"] is False


def test_verify_anchor_fetched_at_is_iso_string():
    a = {
        "anchor_id": "x",
        "claim": "c",
        "span": "s",
        "source_url": "https://sec.gov/x",
        "metric": "X",
        "expected": 1.0,
        "cik": "1",
        "period": "FY2024",
    }
    out = anchors.verify_anchor(a, fetcher=lambda _a: 1.0)
    from datetime import datetime
    # Should parse without error as ISO datetime
    dt = datetime.fromisoformat(out["fetched_at"])
    assert dt is not None
