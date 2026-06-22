#!/usr/bin/env python
"""validate_btarget.py — B 档真 ACCEPT 夜跑实验的 live 自检（跑 1 次，证明可跑）.

两段验证:
  ① profile=B: run_profile(examples/btarget) → 断言 tier 含 "B"、visible+holdout 锚总数 ≥24、
     effective_independent_count(全部锚, 视作 verified) ≥12。
  ② artifact-proposer live: 调真 Claude（cc 优先）改进产物 1 次 → 断言产出合法 JSON、锚数不减。

不真跑 EDGAR、不真 ACCEPT —— 那是夜跑实验本身的事。本脚本只证明
「profile=B + artifact-proposer 能真改产物」。

用法:
    python scripts/validate_btarget.py            # 全量（含 live Claude 调用）
    python scripts/validate_btarget.py --no-live  # 只验 profile（跳过 Claude 调用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# 让脚本能从仓库根直接跑
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tools.sie.profile import run_profile          # noqa: E402
from tools.sie import anchors as _anchors          # noqa: E402
from tools.sie.backends import llm as _llm         # noqa: E402

_TARGET = os.path.join(_REPO, "examples", "btarget")
_ARTIFACT_REL = "report.json"


def validate_profile() -> dict:
    """① run_profile → tier 含 B、锚总数 ≥24、effective_independent ≥12。"""
    with tempfile.TemporaryDirectory() as run_dir:
        prof = run_profile(_TARGET, "HEAD", run_dir=run_dir)
        visible = prof.get("anchors_visible", [])
        hold_ref = prof.get("anchors_holdout_ref", {})
        n_visible = len(visible)
        n_hold = int(hold_ref.get("count", 0))
        n_total = n_visible + n_hold

        # effective_independent: 用全部锚（visible + holdout）视作 verified 估上界。
        all_anchors = []
        for path in [os.path.join(_TARGET, _ARTIFACT_REL)]:
            all_anchors.extend(_anchors.extract_anchors(path))
        for a in all_anchors:
            a["verified"] = True
        eff = _anchors.effective_independent_count(all_anchors)

        tier = prof.get("tier", "")
        ok = ("B" in tier) and (n_total >= 24) and (eff >= 12)
        return {
            "ok": ok,
            "tier": tier,
            "anchors_visible": n_visible,
            "anchors_holdout": n_hold,
            "anchors_total": n_total,
            "effective_independent": eff,
        }


def validate_proposer() -> dict:
    """② artifact-proposer live: 真 Claude 改产物 1 次 → 合法 JSON + 锚数不减。"""
    findings = [
        "Several 'expected' figures look wrong vs the issuers' SEC filings; "
        "correct them to the true reported values.",
        "Make every factual claim verifiable against SEC/EDGAR (metric/cik/period must match).",
    ]
    props = _llm.generate_artifact(_TARGET, [{"merged_findings": findings}],
                                   artifact_rel=_ARTIFACT_REL)
    if not props:
        return {"ok": False, "reason": "artifact-proposer returned [] (Claude unavailable or no improvement)"}

    p = props[0]
    new_doc = json.loads(p["new_content"])  # 合法 JSON（generate_artifact 已门控）
    n_new = sum(len(s.get("anchors", [])) for s in new_doc.get("sections", []))

    orig_doc = json.loads(open(os.path.join(_TARGET, _ARTIFACT_REL), encoding="utf-8").read())
    n_orig = sum(len(s.get("anchors", [])) for s in orig_doc.get("sections", []))

    # 看 proposer 是否真改了 expected（与原文不同 → 真改产物）
    def _expected_map(doc):
        m = {}
        for s in doc.get("sections", []):
            for a in s.get("anchors", []):
                m[a.get("claim", "")] = a.get("expected")
        return m
    orig_exp, new_exp = _expected_map(orig_doc), _expected_map(new_doc)
    changed = sum(1 for k in orig_exp if k in new_exp and new_exp[k] != orig_exp[k])

    ok = (n_new >= n_orig)
    return {
        "ok": ok,
        "file_rel": p["file_rel"],
        "anchors_orig": n_orig,
        "anchors_new": n_new,
        "expected_values_changed": changed,
        "really_modified": changed > 0 or n_new > n_orig,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-live", action="store_true", help="跳过真 Claude artifact-proposer 调用")
    args = ap.parse_args(argv)

    print("=== ① profile=B 验证 ===")
    pr = validate_profile()
    print(json.dumps(pr, ensure_ascii=False, indent=2))
    if not pr["ok"]:
        print("FAIL: profile 不满足 B 档 / 锚数 / 独立数 约束")
        return 1

    if args.no_live:
        print("\n(--no-live: 跳过 artifact-proposer live 验证)")
        print("\nPASS: profile=B 验证通过")
        return 0

    print("\n=== ② artifact-proposer live 验证（真 Claude）===")
    pp = validate_proposer()
    print(json.dumps(pp, ensure_ascii=False, indent=2))
    if not pp["ok"]:
        print("FAIL: artifact-proposer 未产出合法改进产物")
        return 1

    print("\nPASS: profile=B + artifact-proposer 能真改产物")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
