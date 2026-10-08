# self-evolve

Improve a skill or repository through proposed changes, evaluation in a Git worktree, and evidence-based acceptance.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](README_CN.md)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

## ⭐ Design Philosophy

A self-improvement loop can raise its score by changing the task, dropping hard
cases, or grading its own output. Open-ended work makes that especially difficult
to detect because there may be no single ground truth. self-evolve therefore
starts with an observable improvement contract and keeps the comparison stable.

- **Keep one method, adapt the evidence.** The loop is
  `profile → reflect → propose → patch → evaluate → accept or review`.
  A uses executed tests, B uses independently verified facts, and C needs supplied
  measurements. Missing measurements remain unavailable; changing a label cannot
  create evidence.
- **Freeze the rules before changing the candidate.** Keep the evaluation policy,
  obligations, and holdout fixed, and compare the parent and candidate by the same
  identities. This limits task removal and grader changes as routes to a higher
  score, at the cost of starting a new evaluation contract when the goal changes.
- **Let models propose and code decide.** Deterministic gates handle evidence and
  acceptance. Retain actual provider metadata when judging independence; different
  requested aliases cannot establish it. A gate still depends on the quality of
  its inputs and the assumptions behind its statistics.
- **Retain reasons and recoverable candidates.** Failures, rejection, and review
  are useful outcomes. Preserve measured populations and exact candidate bytes,
  with the final documentation and source revision ready before review. This costs
  storage and review effort but makes a decision auditable and a rollback possible.
- **Separate tool, data, and landing authority.** Real evidence stays in a verified
  PRIVATE Git companion. Worktrees isolate edits, but do not prove operating-system
  isolation. Accepted candidates are archived; publishing, merging, and sending
  follow the caller's authorization as separate actions.

The [full rationale and tradeoffs](PHILOSOPHY.md) explain these choices.
[Current limits](#current-limits) define what the shipped loop can execute.

## Install

Clone the repository with its pinned guard and style submodules:

```bash
git clone --recursive https://github.com/DaizeDong/self-evolve.git
```

The skill entry is [SKILL.md](SKILL.md); command adapters live in [commands/](commands/).
Use the absolute `tools/sie_cli.py` entrypoint from another directory or an
installation alias. Run `python -m pytest tests` for the business suite.

## Config

Set `SELF_EVOLVE_CONFIG` (alias `SELF_EVOLVE_CONFIG_DIR`) to an existing PRIVATE
Git companion, or `SELF_EVOLVE_DATA_DIR` to exactly its absolute `data/` path.
Discovery checks DATA_DIR, CONFIG, CONFIG_DIR, the proved sibling companion,
then home candidates, in that order. An inherited DATA_DIR wins over a new CONFIG.
The `data/` directory may be absent; the companion root is never a DATA fallback.
Runtime writes require source-contract ownership and
valid PRIVATE destination proof; missing, stale, public, or unknown proof blocks
writes. See [DATA.md](DATA.md) for storage and retention, and
[runtime configuration](reference/runtime.md#configuration) for prerequisites.

[config.contract.json](config.contract.json) records runtime-storage-only
applicability. Per-run profiles and the retention obligation ledger are DATA;
there is no separate settings registry to initialize. New source worktrees use
the sibling `.worktrees/self-evolve/` layout described in the runtime reference.

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

[Philosophy](PHILOSOPHY.md) · [Agent workflow](SKILL.md) · [Runtime](reference/runtime.md) ·
[Evaluation](reference/evaluation.md) · [Data](DATA.md) · [Roadmap](ROADMAP.md)

For changes to the tool or a target, record the affected documentation, finish it
before reviewing the candidate, and hand off the exact reviewed revision and
checks. See [documentation lifecycle](reference/maintenance.md).

## License

[MIT](LICENSE). Release history is in [CHANGELOG.md](CHANGELOG.md).

## Private storage lifecycle

See [DATA.md](DATA.md) and [storage.contract.json](storage.contract.json) for core outputs, reviewed retirement, recovery and generated-storage admission limits. Keep final deliverables and their unique cited evidence in the PRIVATE companion.
