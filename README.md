# self-evolve

Point an agent at any skill / repo / project and have it self-iterate — behind an un-gameable acceptance gate so "accepted = real improvement," not a self-deceiving score-up-but-capability-flat curve.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-521%20passing-green?style=flat)](tests/)
[![Anti-self-deception](https://img.shields.io/badge/anti--self--deception-6%20paths%20closed-green?style=flat)](SKILL.md)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first — the design philosophy

Most self-improving-agent work succeeds only in **verifiable domains** — code, math, anything with ground truth. The hard, mostly-skipped case is **open-ended generation with no ground truth**, where "I improved" can be asserted but not checked. Stack "set your own task + grade your own work" on top of that, and the literature says you almost always get a **fake upward curve**: the score rises while capability stays flat.

self-evolve is built for exactly that gap. Its guiding stance:

- **The methodology is constant; the signal source adapts.** The loop is always `reflect → propose → evaluate → judge → accept`. The only thing that changes per target is *where the evaluation signal comes from*.
- **Run it if you can, verify it if you can, otherwise generate scenarios and let heterogeneous judges score — so no target is un-evolvable.** Three signal providers (A program adjudication, B anchor verification, C generative evaluation) implement the same `evaluate` contract; you take the strongest available and fall back downward — the floor always exists.
- **LLM proposes, code adjudicates.** Accept / reject / rollback / signal-source selection are all decided by deterministic harness code. The model never grades its own output.
- **Anti-self-deception is the whole point.** Six concrete cheating paths are closed (see the table below), because in a long fully-automatic loop "accepted" must mean real, not self-flattering.

Full philosophy: [`docs/philosophy.md`](docs/philosophy.md) · design specs and rationale in [`docs/superpowers/`](docs/superpowers/).

## What it is (and isn't)

A **methodology skill + lightweight deterministic harness** that lets an agent self-iterate any skill / repo / project inside a `git worktree` sandbox over multiple rounds, with an un-gameable commit gate. It belongs to the **Self-Evolving / Self-Improving Agents** family (the "agent improves its own skill / scaffolding" branch), stitching together ideas from **DGM + SICA + MARS + OMNI + PACE** and adding the guardrails the literature lacks for open, no-ground-truth generation domains: verification-anchor + anytime-valid acceptor + heterogeneous judges + adversarial co-evolution.

It is **not** a magic "make my repo better" button, and **not** a tool that ships changes for you. Everything fully automatic happens inside the sandbox; anything that leaves the sandbox (push / merge to main / outbound send) goes through a separate human-review subflow.

**Anti-self-deception (six paths closed):**

| candidate self-deception path | defense |
|---|---|
| edit the grader / judge to grade itself | IMMUTABLE decision-code manifest + frozen materialization + startup-hash fail-closed + patch hard-reject gate + supervisor dual-process adjudication (candidate never enters `sys.path`, never adjudicates / grades itself) |
| inject an un-verifiable "anchor" | `verify_anchor` (programmatic EDGAR check) + `marginal_gain` is 0 until verified |
| overfit the holdout | holdout ground truth physically isolated (iron law 5) + deterministic split + divergence gate + cumulative drift budget |
| judge collusion | heterogeneous judges (Claude + Codex, forced different model families) + `pairwise_agreement` + judge↔anchor calibration (holdout anchors only) |
| inflated e-value from correlated anchors | `effective_independent_count` same-source de-correlation (8→4) + independence floor gate |
| covert outbound exfil channel | proxy harness relays sends (candidate has no URL-construction power) + entropy / encoding / sequence anomaly review |

## Install

```
/plugin install github:DaizeDong/self-evolve
```

Or clone manually:

```bash
git clone https://github.com/DaizeDong/self-evolve.git ~/.claude/plugins/self-evolve
```

## Quick start

Run one self-iteration round against any git-history target repo (fully automatic inside the sandbox):

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

Default mode is `builtin` / `serial` (deterministic, used by the 521 tests, no external calls). `--live` (= `--proposer llm --reflect-mode parallel`) opens the real-agent closed loop: proposer / reflector / two judges go through the local `cc` gateway (split-billing, fallback `claude`) + the `codex` CLI.

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

- Pure A-tier auto-ACCEPT needs headroom of "more tests pass after the change" — a green baseline has none (by design), so the real open-domain improvement signal lives in the B / C quality tiers.
- The current code treats purely subjective C conservatively (`coverage=0`, low weight, defaults to human review); full A/B↔C accept-parity is the scenario-eval module's design / landing direction, not yet fully landed.
- Everything automatic is sandbox-only; landing actions (push / merge / outbound) always require the human-review subflow.

## Languages

English (`README.md`, authoritative) · 中文 ([`README_CN.md`](README_CN.md))

## Roadmap · Changelog · License

See [ROADMAP.md](ROADMAP.md) · [CHANGELOG.md](CHANGELOG.md) · [LICENSE](LICENSE) (MIT).

Sister skill: [market-intel](https://github.com/DaizeDong/market-intel) — the academic toolchain cross-validation in [`docs/02-crossval-deepdive.md`](docs/02-crossval-deepdive.md) feeds this project's guardrail design.
