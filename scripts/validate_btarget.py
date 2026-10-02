#!/usr/bin/env python
"""Check B-target artifact structure and optionally exercise the installed llmcall proposer.

Choose --artifact PATH in the configured PRIVATE companion or --synthetic.
Profile and proposer scratch stay in that companion. Structural checks do not
verify facts, establish improvement, or demonstrate an ACCEPT decision.
--live explicitly enables one proposer call using llmcall's current policy.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts.setup_btarget_repo import _artifact_content
from tools.sie.profile import run_profile
from tools.sie import anchors as _anchors
from tools.sie.backends import llm as _llm
from tools.sie.runtime_data import agent_scratch, make_directory, private_file_path

_ARTIFACT_REL = "report.json"


def validate_profile(target, run_dir) -> dict:
    """Check B classification and anchor structure with execution probes disabled."""
    prof = run_profile(str(target), "artifact-only", run_dir=str(run_dir),
                       include_exec_probe=False)
    visible = prof.get("anchors_visible", [])
    hold_ref = prof.get("anchors_holdout_ref", {})
    n_visible = len(visible)
    n_hold = int(hold_ref.get("count", 0))
    all_anchors = _anchors.extract_anchors(str(Path(target) / _ARTIFACT_REL))
    hypothetical_verified = [{**anchor, "verified": True} for anchor in all_anchors]
    upper_bound = _anchors.effective_independent_count(hypothetical_verified)
    tier = prof.get("tier", "")
    return {
        "ok": "B" in tier and n_visible + n_hold >= 24 and upper_bound >= 12,
        "scope": "artifact structure only; no execution probe or factual verification",
        "tier": tier,
        "anchors_visible": n_visible,
        "anchors_holdout": n_hold,
        "anchors_total": n_visible + n_hold,
        "effective_independent_upper_bound": upper_bound,
        "facts_verified": False,
    }


def validate_proposer(target) -> dict:
    """Check one llmcall proposal for JSON shape and retained anchor count."""
    findings = [
        "Review this selected artifact and propose a well-formed JSON revision.",
        "Preserve synthetic labels and example.com sources in synthetic input. "
        "Do not present synthetic values as real financial facts.",
        "For real input, do not claim factual corrections without independent evidence.",
    ]
    props = _llm.generate_artifact(str(target), [{"merged_findings": findings}],
                                   artifact_rel=_ARTIFACT_REL)
    if not props:
        return {"ok": False, "reason": "no proposal returned by the configured llmcall backend"}
    proposal = props[0]
    new_doc = json.loads(proposal["new_content"])
    original = json.loads((Path(target) / _ARTIFACT_REL).read_text(encoding="utf-8"))

    def anchor_count(document):
        return sum(len(section.get("anchors", [])) for section in document.get("sections", []))

    n_orig, n_new = anchor_count(original), anchor_count(new_doc)
    return {
        "ok": n_new >= n_orig,
        "scope": "proposer transport and JSON shape only; improvement not adjudicated",
        "file_rel": proposal["file_rel"],
        "anchors_orig": n_orig,
        "anchors_new": n_new,
        "content_changed": new_doc != original,
        "facts_verified": False,
        "accept_tested": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact", help="absolute JSON artifact path in the PRIVATE companion")
    source.add_argument("--synthetic", action="store_true", help="use generated example.com anchors")
    live = parser.add_mutually_exclusive_group()
    live.add_argument("--live", action="store_true", help="enable one installed llmcall proposer call")
    live.add_argument("--no-live", action="store_true", help="explicitly keep the default structural check")
    args = parser.parse_args(argv)
    content = _artifact_content(args.artifact, synthetic=args.synthetic)
    with agent_scratch() as scratch:
        target = make_directory(scratch / "target")
        artifact = private_file_path(target / _ARTIFACT_REL)
        artifact.write_text(content, encoding="utf-8", newline="\n")
        run_dir = make_directory(scratch / "profile")
        profile = validate_profile(target, run_dir)
        print(json.dumps(profile, ensure_ascii=False, indent=2))
        if not profile["ok"]:
            print("FAIL: artifact does not meet the B-tier structural thresholds")
            return 1
        if args.live:
            proposed = validate_proposer(target)
            print(json.dumps(proposed, ensure_ascii=False, indent=2))
            if not proposed["ok"]:
                print("FAIL: proposer did not return an adequate JSON artifact")
                return 1
    print("PASS: requested structural checks completed; factual improvement and ACCEPT were not tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
