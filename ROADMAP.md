# Roadmap

The milestones below describe the original v0.1.0 plan. Use the current README and
module documentation for implemented behavior and limitations.

## v0.1.0 historical milestone scope

This list records intended milestone scope. It is not a current readiness assessment
or test receipt. Current safety and style kits use pinned submodules; validation must
identify the source snapshot, executed tests and unresolved failures.

- **M1a**, deterministic state-machine harness: 10-state run_loop, `events.jsonl` append-only source of truth + crash-replay, git worktree sandbox, three orthogonal counters, A-tier no-regression hard gate.
- **M1b**, PACE e-process acceptor (anti-self-deception linchpin, type-I ≤ α verified, ONS fallback), AST danger gate, mutation-validity gate, non-blocking human-review queue, circuit breaker + liveness.
- **M2**, B-tier external anchors (extract / coverage / de-correlation / deterministic holdout / EDGAR verify / EVE marginal gain), three-gate acceptor, self-deception holdout divergence, outbound proxy anti-exfil.
- **M3**, C-tier heterogeneous judges (Claude + Codex), `pairwise_agreement`, judge↔anchor calibration, multi-gate anti-self-deception, two-sided α gate, pure-C forced human review, Pareto hard-dimension gate, N=3 MARS, BenchTrace.
- **M4**, self-bootstrap isolation: IMMUTABLE manifest + frozen, startup-hash gate, patch hard-reject, supervisor dual-process adjudication, frozen bootstrap grader, `--self` end-to-end.

## Planned

- Land full A/B↔C accept-parity in the scenario-eval module (real scenario-to-intent coverage; lift pure-C out of the conservative `coverage=0` / low-weight / default-human-review path). Nothing of this module is built yet, `tools/` and `tests/` contain no scenario code; the design target is [`docs/modules/scenario-eval.md`](docs/modules/scenario-eval.md).
- Make `--mode gated` mean per-step human review. Today the flag is accepted but is consulted at exactly one place, the pure-C accept gate, where only `auto` forces the human-review fallback.
- Broaden A-tier auto-ACCEPT signal beyond "more tests pass" so green-baseline targets gain headroom.
- More external anchor verifiers beyond EDGAR.
- Wider `--live` real-agent coverage and judge-family diversity.
