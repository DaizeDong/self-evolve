# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [Unreleased]

### Added
- A research roadmap with phased evaluation, six falsifiable mechanism studies, operator scheduling, and long-term meta-improvement criteria. These are planned studies; detailed evidence remains in the private companion.
- Read-only prerequisite diagnosis and metadata-only storage inventory, with explicit unavailable and boundary-failure results.
- Reproducible synthetic B-target fixtures and support commands that require an explicit input and verified PRIVATE destination.
- Reachable bilingual design rationale and documentation-impact, candidate-freeze, review, and handoff obligations. Documentation obligations are a contributor workflow, not an automatic runtime gate.

### Changed
- Real run state, worktrees, model scratch, and reports resolve to a verified PRIVATE Git companion; missing, stale, public, or unknown proof blocks writes without a public-repository fallback.
- Model calls inherit installed llmcall policy and retain actual provider, attempts, diagnostics, and errors. Successful raw JSON is omitted only when its complete content is retained in parsed fields; existing ledgers are not rewritten.
- Runtime and evidence documentation now distinguishes current A/B support from missing C measurement production, refused A+B execution, absent gated per-step review, and A-only selfboot. Earlier release entries remain historical records, not current support claims.
- Runtime storage documentation distinguishes recovery-critical snapshots and events from derived, historical, and scratch records; candidate worktrees use detached HEAD without creating branches.

### Fixed
- Parent/candidate comparison retains task and fact identities, requires a usable selected-parent baseline, and blocks unavailable or altered holdout evidence.
- Evaluation decisions and holdout progress remain durable across resume; restoration failures stop iteration rather than silently continuing on the wrong parent.
- Frozen selfboot grades and archives the same candidate, and snapshot comparison and restoration share business-tree exclusions.
- UTF-8 subprocess decoding and measurement failures remain explicit; timeouts and empty test collections are not passing observations.

## [0.1.0] - 2026-06-24
### Added
- Initial release. Methodology skill + deterministic harness for self-iterating any skill / repo / project behind an un-gameable acceptance gate.
- Five milestones (M1a, M1b, M2, M3, M4): deterministic state-machine harness, PACE e-process acceptor, B-tier external anchors, C-tier heterogeneous judges, and `--self` self-bootstrap isolation. 52 tasks / 521 tests passing.
- Six self-deception paths closed; `--live` real-agent closed loop (proposer / reflector / dual judges).

### Changed
- docs: unify repo structure (Skill Repo Spec v1).

### Fixed
- Acceptor e-value is the running maximum `sup_t W_t` over the wealth path, not the final value `W_n`. An early draft of the spec described taking `W_n`, which loses power whenever wealth crosses the threshold and then falls back before the run ends.
- ONS betting tightens the λ clip to ±(2 − 1e-6) rather than flooring the wealth factor at `1e-10`. Flooring the factor let the gradient `payoff / factor` explode to ±5e7 at λ=±2 with payoff=∓0.5, which broke the martingale identity (the wealth multiplier and the gradient stopped agreeing) and drove wealth permanently to zero. Clipping λ instead keeps the factor strictly positive, so the martingale property and Ville's inequality hold.
