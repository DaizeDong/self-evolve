# Roadmap

Current: **v0.1.0**

The current interface supports isolated proposals, A test evidence, B factual
verification, event replay, archived candidates, and A-path selfboot.
[README.md](README.md) and the [evaluation contract](reference/evaluation.md)
describe the limits of those capabilities.

Planned work:

- Implement regression replay, consistency measurements, and scenario generation
  for C; require real coverage before claiming subjective improvement.
- Enforce both evidence components before allowing A+B execution.
- Define per-step review behavior for `--mode gated`.
- Add improvement signals for changes that leave an already-green test suite unchanged.
- Broaden independently verified facts beyond the current EDGAR path.
- Measure live provider diversity and operating-system isolation in supported deployments.

A planned item is not an implemented capability or a validation receipt.
