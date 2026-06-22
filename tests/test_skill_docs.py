"""test_skill_docs.py — doc consistency gate for M1a skill layer.

Verifies:
  1. SKILL.md exists and contains the four gate-law keywords.
  2. commands/ three files each reference 'sie' and the expected CLI subcommand.
  3. reference/target_contract.md contains all five A-grade contract fields.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def test_skill_md_exists_and_mentions_gates():
    t = _read("SKILL.md")
    for kw in ("LLM 只提议", "代码裁决", "沙箱", "人审"):
        assert kw in t, f"SKILL.md missing required keyword: {kw!r}"


def test_commands_reference_cli():
    for cmd, sub in [
        ("self-evolve", "run"),
        ("self-evolve-status", "status"),
        ("self-evolve-resume", "run"),
    ]:
        t = _read(f"commands/{cmd}.md")
        assert "sie" in t, f"commands/{cmd}.md must reference 'sie'"
        assert sub in t, f"commands/{cmd}.md must reference subcommand {sub!r}"


def test_contract_doc_has_grade_fields():
    t = _read("reference/target_contract.md")
    for f in (
        "task_passed",
        "grader_exit_code",
        "dimensions",
        "anchors",
        "verifiable_coverage",
    ):
        assert f in t, f"reference/target_contract.md missing field: {f!r}"
