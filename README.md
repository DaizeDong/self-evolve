# self-evolve

Improve a skill or repository through proposed changes, isolated evaluation and evidence-based acceptance. Passing a gate establishes only the capability measured by that gate.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-local%20suite-blue?style=flat)](tests/)
[![Anti-self-deception](https://img.shields.io/badge/acceptance-evidence%20gates-blue?style=flat)](SKILL.md)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first, the design philosophy

Most self-improving-agent work succeeds only in **verifiable domains**, code, math, anything with ground truth. The hard, mostly-skipped case is **open-ended generation with no ground truth**, where "I improved" can be asserted but not checked. Stack "set your own task + grade your own work" on top of that, and the literature says you almost always get a **fake upward curve**: the score rises while capability stays flat.

self-evolve is built for exactly that gap. Its guiding stance:

- **The methodology is constant; the signal source adapts.** The loop is always `reflect → propose → evaluate → judge → accept`. The only thing that changes per target is *where the evaluation signal comes from*.
- **Choose observable evidence.** Use A program adjudication or B independently verified anchors where available. C can consume supplied regression and consistency evidence; automatic scenario generation is not implemented. Missing evidence cannot establish improvement.
- **LLM proposes, code adjudicates.** Accept / reject / rollback / signal-source selection are all decided by deterministic harness code. The model never grades its own output.
- **Keep acceptance attributable.** Record candidate hashes, tests, source evidence and actual provider metadata. Review the limitations of each gate before interpreting its result.

Full philosophy: [`docs/philosophy.md`](docs/philosophy.md) · design specs and rationale in [`docs/superpowers/`](docs/superpowers/).

## What it is (and isn't)

A **methodology skill + lightweight deterministic harness** that lets an agent self-iterate any skill / repo / project inside a `git worktree` sandbox over multiple rounds, with deterministic acceptance gates. It belongs to the **Self-Evolving / Self-Improving Agents** family (the "agent improves its own skill / scaffolding" branch), stitching together ideas from **DGM + SICA + MARS + OMNI + PACE** and adding the guardrails the literature lacks for open, no-ground-truth generation domains: verification-anchor + anytime-valid acceptor + heterogeneous judges + adversarial co-evolution.

It is **not** a magic "make my repo better" button, and **not** a tool that ships changes for you. Everything fully automatic happens inside the sandbox; anything that leaves the sandbox (push / merge to main / outbound send) goes through a separate human-review subflow.

**Acceptance controls:**

| candidate self-deception path | defense |
|---|---|
| edit the grader / judge to grade itself | IMMUTABLE decision-code manifest + frozen materialization + startup-hash fail-closed + patch hard-reject gate + supervisor dual-process adjudication (candidate never enters `sys.path`, never adjudicates / grades itself) |
| inject an un-verifiable "anchor" | `verify_anchor` (programmatic EDGAR check) + `marginal_gain` is 0 until verified |
| overfit the holdout | holdout values excluded from prompts; filesystem isolation requires a separately verified deployment boundary + deterministic split + divergence gate + cumulative drift budget |
| judge collusion | judges with known, distinct families derived from actual returned providers + `pairwise_agreement` + judge↔anchor calibration (holdout anchors only) |
| inflated e-value from correlated anchors | `effective_independent_count` same-source de-correlation (8→4) + independence floor gate |
| covert outbound exfil channel | proxy harness relays sends (candidate has no URL-construction power) + entropy / encoding / sequence anomaly review |

## Install

```
/plugin install github:DaizeDong/self-evolve
```

Or clone manually:

```bash
git clone --recursive https://github.com/DaizeDong/self-evolve.git ~/.claude/plugins/self-evolve
```

## Quick start

Configure the private companion as described below, then run these commands from the skill repository against a target with Git history:

```bash
# initialize a run (returns a run_id)
python -m tools.sie.cli init   --target <absolute path to target repo>

# run the loop
python -m tools.sie.cli run    --target <target> --run-id <id> --base-ref HEAD --max-rounds 3

# inspect / recover
python -m tools.sie.cli status   --target <target> --run-id <id>     # current state
python -m tools.sie.cli replay   --target <target> --run-id <id>     # rebuild from events after a crash
python -m tools.sie.cli rollback --target <target> --run-id <id> --vid <vid>

# self-bootstrap (evolve self-evolve itself, with IMMUTABLE enforcement on)
python -m tools.sie.cli run --target <self-evolve itself> --run-id <id> --self --enforce-immutable
```

Default `builtin` / `serial` behavior uses supplied deterministic evidence. Run
`python -m pytest tests` for the business suite; pinned guard tests are separate.
`--live` selects model-backed proposals and reflections through installed
`llmcall.call(..., mode="agent")`; judges use default judge mode. Routing, model,
timeout and fallback choices belong to llmcall. A requested provider alias does
not establish independence. Agent calls use separate disposable directories in
the private companion, leaving the caller's working directory unchanged.

## Configuration and first-run diagnosis

Set `SELF_EVOLVE_CONFIG` to an existing PRIVATE Git companion, or set
`SELF_EVOLVE_DATA_DIR` to an absolute directory inside it. Keep the companion
versioned. Runtime writes require its GitHub origin to have a current PRIVATE
entry in `~/.pii-guard/visibility.json`; `_refreshed` must include a timezone and
be no older than 30 days. Missing, stale, public or unknown proof blocks writes.
Refresh the fleet visibility registry after creating or changing the companion.
Ordinary SSH aliases resolve through local `Host` and `HostName` rules without
running SSH or configuration commands. Dynamic Include, Match and canonicalization
rules are refused; literal HTTPS origins do not read SSH configuration.

From the skill repository, run `python -m tools.sie.cli doctor --target <target>`
before `init`. From another directory or an installation alias, use
`python <absolute-skill-path>/tools/sie_cli.py doctor --target <target>`; the
same entrypoint supports every subcommand. Doctor reports configuration and
capability gaps without calling a model or creating runtime directories.

Run state is stored under the private data root, namespaced by canonical target
identity. `init` reports its exact path. Both ordinary runs and `--self` use this
resolver; foreign public targets receive no runtime directory. Use a nonempty
single-component run ID. `status` and `replay` explicitly report uninitialized
state when there is no record. Scratch cwd containment is not an operating-system
sandbox against deliberate absolute-path writes. Profiling can classify A+B, but execution
currently refuses that composite until both acceptance components are supported. B scoring
preserves all frozen identities and spans; sampled holdouts need pinned, independently
measured observations. Selfboot patches, grades and snapshots the same candidate tree.


## Synthetic fixtures and B-target checks

The two JSON fixtures under `tests/fixtures/` are generated synthetic data with
reserved example.com sources. Regenerate them with:

```bash
python tools/make_fixtures.py --out tests/fixtures
```

Without `--out`, the generator retains its legacy stdout samples. Synthetic
anchors exercise schema and scoring mechanics; they are not financial evidence.

B-target support scripts require an explicit source. After configuring the PRIVATE
companion, validate either generated input or an absolute PRIVATE artifact:

```bash
python scripts/validate_btarget.py --synthetic
python scripts/validate_btarget.py --artifact <absolute-private-json>
```

The validator copies that selected input into disposable PRIVATE scratch and
disables execution probes. It reports structural B classification and an independence
upper bound computed under hypothetical verification; it does not verify facts or
test ACCEPT. Add `--live` only to request one installed llmcall proposal. That check
reports JSON shape and anchor count, which do not establish factual improvement.

To prepare a persistent standalone target, supply the target's own PRIVATE remote:

```bash
python scripts/setup_btarget_repo.py --synthetic --private-remote <target-private-remote>
python scripts/setup_btarget_repo.py --artifact <absolute-private-json> --private-remote <target-private-remote>
```

The destination defaults beneath the PRIVATE data root; `--dest` must remain beneath
it. The remote must already have current PRIVATE visibility proof. Setup verifies
that proof before writing the artifact and uses the configured Git identity and
hooks. It does not push. The companion's remote is never assumed to be the target's
remote. A failed visibility check can leave empty Git initialization metadata; no
artifact has been copied at that point.

## How to invoke

Slash commands (deploy the repo to `~/.claude/skills/self-evolve` first, e.g. via a junction):

```
/self-evolve <target>            # start a self-iteration run against a target
/self-evolve-status <run_id>     # check run state
/self-evolve-resume <run_id>     # resume an existing run
```

Iron laws, the gate sequence, and the per-tier / per-anchor contracts are in [`SKILL.md`](SKILL.md) and [`reference/`](reference/).

## Example output

The loop is a 10-state gated state machine collapsed into six intuitive verbs:

```
              ┌──────────────────── one iteration ───────────────────┐
  PROFILE ──► REFLECT ──► PROPOSE ──► PATCH ──► EVALUATE ──► JUDGE ──┐
  (fix signal) (read hist) (propose)  (sandbox)  (get signal)(adjudge)│
     │                                              accept/reject/rollback
     └──────────────────◄── LOOP ◄───────────────────────────────────┘
                              │  self-deception/breaker hit → PAUSE(human) → STOP
```

Accepted versions enter an archive lineage; anything that leaves the sandbox goes to human review. See [`examples/`](examples/) for sample runs.

## Limitations

- Pure A-tier auto-ACCEPT needs headroom of "more tests pass after the change", a green baseline has none (by design), so the real open-domain improvement signal lives in the B / C quality tiers.
- The current code treats purely subjective C conservatively (`coverage=0`, low weight, defaults to human review); full A/B↔C accept-parity is the scenario-eval module's design / landing direction, not yet fully landed.
- Everything automatic is sandbox-only; landing actions (push / merge / outbound) always require the human-review subflow.
- Ville's inequality controls a single valid nonnegative process under its conditional-null assumptions. Each proposal evaluation currently starts fresh wealth; there is no run-wide alpha allocation, so repeated proposals do not have an established family-wise error bound of alpha. The returned `evalue` is a path maximum, not automatically an expectation-bounded e-value. See [the mathematical scope](reference/acceptor_math.md).

## Languages

English (`README.md`, authoritative) · 中文 ([`README_CN.md`](README_CN.md))

## Roadmap · Changelog · License

See [ROADMAP.md](ROADMAP.md) · [CHANGELOG.md](CHANGELOG.md) · [LICENSE](LICENSE) (MIT).

Sister skill: [market-intel](https://github.com/DaizeDong/market-intel), the academic toolchain cross-validation in [`docs/02-crossval-deepdive.md`](docs/02-crossval-deepdive.md) feeds this project's guardrail design.

Calibration attribution remeasures every oracle for each accepted snapshot. Changes
to imported helpers or configuration can alter a result even when a defect-bearing
file is unchanged. This conservative policy costs more oracle executions; cache
reuse requires a complete dependency contract. The calibration runner reports
measurement results and errors separately.
