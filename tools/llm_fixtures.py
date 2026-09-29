"""Synthetic values consumed by tools.make_fixtures and offline LLM tests."""
import json
from copy import deepcopy


def llm_samples():
    spans = ["Synthetic section alpha", "Synthetic section beta"]
    document = {"sections": [{"text": spans[0], "anchors": [{
        "span": spans[0], "claim": "Synthetic assertion", "expected": 7654321,
        "source_url": "https://example.com/synthetic-facts", "metric": "us-gaap:Assets",
        "cik": "1000001", "period": "2024-FY",
        "verified": True, "observed": 7654322, "marginal_gain": 0.314159,
    }]}]}
    code = "def value():\n    return 2\n"
    scores = {"span_scores": [{"span": spans[0], "score": 0.8},
                              {"span": spans[1], "score": 0.6}]}
    samples = {
        "prompt": "Inspect the supplied synthetic evidence.",
        "text": "Synthetic terminal response.",
        "providers": ["cc", "claude", "codexg", "codex", "unrecognized-provider"],
        "attempts": [{"provider": "cc", "ok": True, "ms": 12, "error": None}],
        "spans": spans, "scores": scores, "document": document,
        "malformed_artifact": json.dumps(document)[:-1],
        "code_path": "sample.py", "code": code,
        "proposal": {"file_rel": "sample.py", "new_content": code},
        "artifact_path": "sample.json",
        "artifact_proposal": {"file_rel": "sample.json", "new_content": json.dumps(document)},
        "reflection": {"findings": ["The synthetic check failed."]},
        "history": [{"round": 1, "summary": "The synthetic check failed."}],
        "bad_texts": ["", " ", "not JSON", "[]", "null"],
        "bad_scores": [True, "0.8", -0.1, 1.1, float("nan"), float("inf")],
        "verdicts": [{"verdict": "accept"}, {"verdict": "reject"}],
        "replay": [{"task": "synthetic-task", "before": True, "after": True}],
        "consistency": [(0.6, 0.7)],
    }
    payload = {key: samples[key] for key in ("proposal", "artifact_proposal", "attempts")}
    samples["child_module"] = '''"""Generated offline llmcall replacement; no provider or network code."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path

CONFIG = json.loads(PAYLOAD)

@dataclass
class Attempt:
    provider: str
    ok: bool
    ms: int
    error: str | None = None

@dataclass
class Result:
    text: str = ""
    provider: str | None = None
    data: object = None
    error: str | None = None
    attempts: list = field(default_factory=list)
    depth: int = 0

def call(prompt, **kwargs):
    assert kwargs == {"mode": "agent"}, kwargs
    Path("synthetic-call.txt").write_text(prompt, encoding="utf-8")
    scenario = os.environ.get("SIE_SYNTHETIC_RESPONSE", "reflection")
    if scenario == "exception":
        raise RuntimeError("synthetic child failure")
    if scenario == "proposal":
        text = json.dumps(CONFIG["proposal"])
    elif scenario == "artifact":
        text = json.dumps(CONFIG["artifact_proposal"])
    else:
        text = json.dumps({"findings": [str(Path.cwd())]})
    result = Result(text=text, provider="cc", attempts=[Attempt(**a) for a in CONFIG["attempts"]])
    if scenario == "pending":
        result.status = "running"
    return result
'''.replace("PAYLOAD", repr(json.dumps(payload)))
    return samples


def artifact_schema_samples():
    """Generate malformed structures and independent finite-number controls."""
    sample = llm_samples()
    document = sample["document"]
    invalid = {}

    def anchor_case(name, key, value=None, remove=False):
        doc = deepcopy(document)
        anchor = doc["sections"][0]["anchors"][0]
        if remove:
            anchor.pop(key)
        else:
            anchor[key] = value
        invalid[name] = doc

    for key in ("claim", "span", "source_url", "metric", "cik", "period", "expected"):
        anchor_case("missing_" + key, key, remove=True)
    for key in ("claim", "span", "source_url", "metric", "cik", "period"):
        anchor_case("empty_" + key, key, "")
        anchor_case("object_" + key, key, {})
    for name, value in (("bool", True), ("null", None), ("string", "12"),
                        ("nan", float("nan")), ("inf", float("inf")),
                        ("negative_inf", -float("inf")), ("overflow", 10 ** 400)):
        anchor_case("expected_" + name, "expected", value)
    for name, sections in (("section_scalar", [False]),
                           ("collection_object", [{"anchors": {"claim": "Synthetic"}}]),
                           ("anchor_scalar", [{"anchors": [None]}])):
        invalid[name] = {"sections": deepcopy(document["sections"]) + sections}
    nonnumeric = deepcopy(document)
    for key in ("metric", "cik", "period", "expected"):
        nonnumeric["sections"][0]["anchors"][0].pop(key)
    invalid["numeric_schema_removed"] = deepcopy(nonnumeric)
    nonnumeric["sections"].append({"text": "Synthetic unanchored section"})
    return {"source": document, "invalid": invalid, "nonnumeric": nonnumeric,
            "finite_values": [0, 1, 1.0, -12.5, 1e300],
            "path": sample["artifact_path"], "wrong_value": 123,
            "fenced_content": "```json\n" + json.dumps(document) + "\n```",
            "source_value": document["sections"][0]["anchors"][0]["expected"]}


def c_evidence_samples():
    """Generate a pure-C run with proposals but no measurement provider."""
    sample = llm_samples()
    return {
        "profile": {"tier": "C", "verifiability_score": 0.0, "anchors_visible": [],
                    "anchors_holdout_ref": {"path": "", "count": 0, "ref": "isolated"},
                    "probe_evidence": {"fact": {}, "anchor_count": 0},
                    "probes": {"exec": {}}, "base_ref": "HEAD", "visible": [], "holdout": []},
        "reflection": [{"file_rel": sample["code_path"], "fix_content": sample["code"],
                        "target_failure": "Synthetic missing measurement"}],
        "proposals": [sample["proposal"]], "run_id": "synthetic-missing-evidence",
    }
