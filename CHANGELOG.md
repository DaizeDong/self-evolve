# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

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
