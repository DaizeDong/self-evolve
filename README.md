# self-evolve

Improve a skill or repository through proposed changes, evaluation in a Git worktree, and evidence-based acceptance.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](README_CN.md)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

## ⭐ Read this first

Define how improvement will be measured before proposing a change. Models produce
suggestions; deterministic code checks the evidence and decides acceptance. Missing
measurements remain unavailable. Passing a gate establishes only what it measured.

The loop is `profile → reflect → propose → patch → evaluate → accept or review`.
Accepted candidates are archived for review. Publishing, merging, and sending are
separate actions governed by the caller's authorization.

## Install

Clone the repository with its pinned guard and style submodules:

```bash
git clone --recursive https://github.com/DaizeDong/self-evolve.git
```

The skill entry is [SKILL.md](SKILL.md); command adapters live in [commands/](commands/).
Use the absolute `tools/sie_cli.py` entrypoint from another directory or an
installation alias. Run `python -m pytest tests` for the business suite.

## Config

Set `SELF_EVOLVE_CONFIG` to an existing PRIVATE Git companion, or
`SELF_EVOLVE_DATA_DIR` to an absolute directory inside it. Runtime writes require
valid PRIVATE destination proof; missing, stale, public, or unknown proof blocks
writes. See [DATA.md](DATA.md) for storage and retention, and
[runtime configuration](reference/runtime.md#configuration) for prerequisites.

Model calls use installed `llmcall` routing, model, timeout, and fallback settings.
Agents use `mode="agent"`; text judges use default judge mode. Actual returned
providers establish review independence, not requested aliases.

## Usage

From the repository, inspect prerequisites, initialize, then run:

```bash
python -m tools.sie.cli doctor --target <target>
python -m tools.sie.cli init --target <target>
python -m tools.sie.cli run --target <target> --run-id <id> --base-ref HEAD --max-rounds 3
python -m tools.sie.cli status --target <target> --run-id <id>
```

Read the doctor's JSON, including `private_data.available`; a zero exit status
alone does not prove readiness. The target needs Git history and usable evaluation
evidence. Default `builtin` proposals consume supplied fixes. Add `--live` for
model proposals and parallel reflection, or `--proposer llm-artifact` for JSON
artifact proposals. Resume by running the same run ID again.

[CLI and recovery](reference/runtime.md#cli) covers all options, replay, rollback,
and selfboot. [Evaluation](reference/evaluation.md) defines accepted evidence.

## Current limits

- A measures test outcomes. If no paired result changes, it requests human review.
- B compares frozen facts using independent verification; synthetic anchors only test mechanics.
- C can validate supplied evidence at the API level, but the loop has no regression
  or consistency measurement producer. Automatic scenario generation is unimplemented.
- Profiling can detect A+B; the loop refuses that combination before proposals.
- `--mode gated` does not provide per-step review. `--self` supports A evaluation.
- Worktrees, prompt filtering, and static checks do not establish an operating-system sandbox.
- Statistical guarantees require the assumptions in
  [acceptor math](reference/acceptor_math.md); there is no established run-wide error bound.

## Documentation

[Agent workflow](SKILL.md) · [Runtime](reference/runtime.md) ·
[Evaluation](reference/evaluation.md) · [Data](DATA.md) · [Roadmap](ROADMAP.md)

## License

[MIT](LICENSE). Release history is in [CHANGELOG.md](CHANGELOG.md).
