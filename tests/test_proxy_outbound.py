import os
import re
from tools.sie import proxy

ALLOW = {
    "edgar_facts": {
        "url_template": "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{metric}.json",
        "params": {"cik": r"^\d{1,10}$", "metric": r"^[A-Za-z]+$"},
    }
}


def test_shannon_entropy_high_for_random():
    low = proxy.shannon_entropy("aaaaaaaaaaaaaaaa")
    high = proxy.shannon_entropy(os.urandom(64))
    assert high > low
    assert high > 4.0


def test_looks_encoded_detects_base64_and_hex():
    assert proxy.looks_encoded("U29tZVNlY3JldFBheWxvYWREYXRhMTIzNDU2Nzg5MA==")
    assert proxy.looks_encoded("deadbeefcafebabe0123456789abcdef0123456789abcdef")
    assert not proxy.looks_encoded("hello world this is plain text")


def test_screen_blocks_high_entropy_query():
    payload = "U2VjcmV0RXhmaWxBbnN3ZXJQYXlsb2FkQmFzZTY0RGF0YQ=="
    out = proxy.screen_request("GET", f"https://data.sec.gov/x?q={payload}", {}, b"")
    assert out["ok"] is False
    assert any("encoded" in v or "entropy" in v for v in out["violations"])


def test_screen_blocks_high_entropy_body():
    out = proxy.screen_request("POST", "https://data.sec.gov/x", {}, os.urandom(256))
    assert out["ok"] is False


def test_screen_passes_clean_request():
    out = proxy.screen_request(
        "GET",
        "https://data.sec.gov/api/xbrl/companyconcept/CIK320193/us-gaap/Revenues.json",
        {},
        b"",
    )
    assert out["ok"] is True


def test_dispatch_rejects_unknown_kind(tmp_path):
    out = proxy.dispatch({"kind": "evil_exfil", "params": {}}, str(tmp_path), ALLOW)
    assert out["ok"] is False
    assert "kind" in out["reason"]


def test_dispatch_rejects_param_failing_regex(tmp_path):
    out = proxy.dispatch(
        {"kind": "edgar_facts", "params": {"cik": "320193;DROP", "metric": "Revenues"}},
        str(tmp_path),
        ALLOW,
    )
    assert out["ok"] is False
    assert "param" in out["reason"]


def test_dispatch_builds_url_and_calls_fetcher(tmp_path):
    captured = {}

    def fake_fetch(method, url, headers, body):
        captured["url"] = url
        return {"status": 200, "body": '{"v": 1.2e9}'}

    out = proxy.dispatch(
        {"kind": "edgar_facts", "params": {"cik": "320193", "metric": "Revenues"}},
        str(tmp_path),
        ALLOW,
        fetcher=fake_fetch,
    )
    assert out["ok"] is True
    assert captured["url"] == "https://data.sec.gov/api/xbrl/companyconcept/CIK320193/us-gaap/Revenues.json"
    assert out["result"]["status"] == 200


# --- Additional edge-case tests ---

def test_dispatch_rejects_extra_params(tmp_path):
    """Candidate cannot sneak extra params (potential URL injection)."""
    out = proxy.dispatch(
        {"kind": "edgar_facts", "params": {"cik": "320193", "metric": "Revenues", "url": "evil.com"}},
        str(tmp_path),
        ALLOW,
    )
    assert out["ok"] is False
    assert "param" in out["reason"].lower() or "unexpected" in out["reason"].lower()


def test_dispatch_rejects_direct_url_in_spec(tmp_path):
    """Candidate may not pass a raw url key in request_spec; harness ignores it and uses template."""
    captured = {}

    def fake_fetch(method, url, headers, body):
        captured["url"] = url
        return {"status": 200, "body": "{}"}

    out = proxy.dispatch(
        {"kind": "edgar_facts", "url": "https://evil.com/exfil", "params": {"cik": "320193", "metric": "Revenues"}},
        str(tmp_path),
        ALLOW,
        fetcher=fake_fetch,
    )
    # Regardless of whether dispatch accepted or rejected, the fetched URL must never be evil.com
    assert "evil.com" not in captured.get("url", "")
    # If it succeeded, the URL must be the template-derived one
    if out["ok"]:
        assert captured["url"] == "https://data.sec.gov/api/xbrl/companyconcept/CIK320193/us-gaap/Revenues.json"


def test_screen_blocks_encoded_header(tmp_path):
    long_b64 = "U29tZVNlY3JldFBheWxvYWREYXRhMTIzNDU2Nzg5MA=="
    out = proxy.screen_request("GET", "https://data.sec.gov/x", {"X-Secret": long_b64}, b"")
    assert out["ok"] is False
    assert any("header" in v for v in out["violations"])


def test_screen_blocks_oversized_body():
    big_body = b"A" * 9000  # > 8192 limit
    out = proxy.screen_request("POST", "https://data.sec.gov/x", {}, big_body)
    assert out["ok"] is False
    assert any("size" in v for v in out["violations"])


def test_looks_encoded_rejects_short_strings():
    """Strings shorter than _ENCODED_MIN_LEN should not trigger looks_encoded."""
    assert not proxy.looks_encoded("deadbeef")  # 8 hex chars < threshold


def test_shannon_entropy_uniform_bytes():
    """256 distinct byte values should give maximum entropy (~8 bits)."""
    data = bytes(range(256))
    h = proxy.shannon_entropy(data)
    assert h > 7.9


def test_shannon_entropy_empty():
    assert proxy.shannon_entropy(b"") == 0.0
    assert proxy.shannon_entropy("") == 0.0
