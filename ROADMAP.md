# Roadmap

Current: **v0.1.0**

The current interface supports isolated proposals, A test evidence, B factual
verification, event replay, archived candidates, and A-path selfboot.
[README.md](README.md) and the [evaluation contract](reference/evaluation.md)
describe the limits of those capabilities.

## Planned research direction

Develop a framework that improves how an agent acquires, represents, applies,
and transfers knowledge, including how it chooses its next experiment. The
current [design philosophy](PHILOSOPHY.md) describes the shipped loop; the
research programme below proposes extensions, not additional current capabilities.

Research should guide design through testable hypotheses and competing evidence.
A recent paper motivates an experiment; adoption requires useful results against
strong baselines in the intended setting. Keep these distinctions explicit:

- **Knowledge and its use:** distinguish observations, reusable procedures,
  applicability conditions, representation, and invocation policy.
- **Improvement and transfer:** separate success on the current task, adaptation
  to a task batch, retained capability, new-task transfer, and a better improver.
- **Exploration and selection:** preserve promising alternatives without treating
  novelty, archive size, or the best candidate in hindsight as deployment quality.
- **Value and cost:** measure new capability, retention, transfer, research cost,
  execution cost, and required human work separately.

All research phases are **planned and unvalidated**. Record pass, fail, or
inconclusive outcomes; a plateau under a finite budget does not prove convergence.

### Phase 0: Establish a learning evaluation baseline

Compare the current loop with a strong fixed harness, repeated sampling or
reflection, and structure-only controls that do not evolve. Cover executable,
source-grounded, and preference-based tasks. Separate research, selection, and
final-test task families; include later fresh-session tasks and earlier-capability
checks. Distinguish task, environment, and model transfer.

Before each study, specify the minimum useful effect, uncertainty rule, retention
floor, feedback access, and total budget. Count proposals, task generation,
judging, unsuccessful search, training or sandbox use, final execution, and human
intervention. Report research and deployment costs separately.

**Exit evidence:** reproducible baseline measurements and controls that can
distinguish task-local adaptation from retained learning. Neither better scores
on the search set nor a structurally valid report is sufficient.

Research anchors: [PAST-Bench](https://arxiv.org/abs/2608.04003),
[S3Gym](https://arxiv.org/abs/2608.31100), and
[Rethinking Harness Evolution](https://arxiv.org/abs/2607.12227).
Their results motivate the comparisons; none establishes a universal evaluation
protocol or the effectiveness of this tool.

### Phase 1: Test six mechanism hypotheses

Run these studies independently where possible after the relevant Phase 0
baseline exists. Share measurement interfaces, not selection data with the final
test. Allow bounded joint experiments when a specific interaction hypothesis
justifies them, even if neither component helps alone.

| ID | Hypothesis and minimum comparison | Evidence needed to advance |
| --- | --- | --- |
| H1 | Stateful diagnosis: fixed proposal loop versus diagnostic tools and refreshed experiment state. | Better held-out gain or research efficiency under the same complete budget, beyond extra calls alone. |
| H2 | Knowledge organization and evidence routing: cross family/non-family organization with summary replacement/routing to source evidence. | Better transfer or quality-cost tradeoff; isolate each mechanism and their interaction under matched context/storage budgets. |
| H3 | Diversity and incubation: global-best selection, niche selection, and niches with limited development time. | More implemented, tested discoveries or a better quality-cost frontier; embedding distance alone is insufficient. Evaluate an actual selector separately from oracle portfolio scores. |
| H4 | Active curriculum: fixed tasks, failure resampling, difficulty-directed practice, and an independent exploration stream. | Better final-test transfer while meeting the retention floor; producing more easy tasks is not a gain. |
| H5 | Selective sharing: independent workers, periodic summaries, broadcast, and state-conditioned exchange. | Gains beyond matched timing and random-content controls, including communication cost and loss of independent exploration. |
| H6 | Research replay: fixed allocation, textual experience, and replay-based strategy selection. | Replay rankings predict fresh discovery runs; saved research cost exceeds replay and policy-search overhead. |

Research anchors by hypothesis:

- H1: [ReASearch](https://arxiv.org/abs/2608.06714) and
  [AIDE2](https://arxiv.org/abs/2609.26457).
- H2: [SkillGLoW](https://arxiv.org/abs/2609.02217),
  [MemCodex](https://arxiv.org/abs/2609.39765), and the counterevidence in
  [Useful Memories](https://arxiv.org/abs/2605.12978).
- H3: [QDEvo](https://arxiv.org/abs/2607.11916) and
  [Heuresis](https://arxiv.org/abs/2606.25198). Incubation is a hypothesis here,
  not an established remedy for the quality-novelty gap.
- H4: [Skill Self-Play](https://arxiv.org/abs/2607.22529) and
  [SESA](https://arxiv.org/abs/2607.29468).
- H5: [Adaptive Transmission Programs](https://arxiv.org/abs/2608.24545) and
  [From Solo to Social Learning](https://arxiv.org/abs/2609.38516).
- H6: [Dream-RSI](https://arxiv.org/abs/2609.14858). Recorded branches do not
  establish unobserved outcomes or effects of changing their generation context.

### Phase 2: Compare representation and update schedules

After establishing single-mechanism baselines and interpretable ablations, compare
fixed, random, diagnosis-driven, and learned operator schedules. Start with
content, representation, and invocation changes. Use small factorial studies to
identify complementary effects and interference before expanding the interface.

Candidate later operators include curriculum changes, evaluator learning,
world-model updates, parameter training, and a trainable adviser around a frozen
executor. Introduce them only with suitable feedback and resource accounting;
adding more operators is not itself evidence of progress. Evaluate new judges
against independent calibration evidence before using them in a later phase.

**Exit evidence:** composition or scheduling improves held-out capability and
cost tradeoffs beyond the strongest single operator and fixed pipeline, with
scheduler overhead and negative interactions reported.

Research anchors: [SkillSpec](https://arxiv.org/abs/2610.00704),
[EvoOntology](https://arxiv.org/abs/2609.15779),
[MetaRSI](https://arxiv.org/abs/2609.06396),
[J-Zero](https://arxiv.org/abs/2608.26582), and
[AdviSD](https://arxiv.org/abs/2609.38142).

### Phase 3: Test meta-improvement and long-term learning

Freeze the resulting research controller. Compare it with the original controller
from identical starting artifacts on unseen task families through independent
complete research runs. Measure learning curves, retention, environment shifts,
task-order sensitivity, budget sensitivity, and human intervention.

**Exit evidence:** replicated gains in transferable capability per complete
research budget. Better task performance alone cannot establish a better
self-improver; AIDE2's direct ignition comparison remains inconclusive. Compare
fixed-improver composition, such as [Meta^n](https://arxiv.org/abs/2608.24735),
with controller revision rather than assuming that more self-rewriting is better.

Use [open-endedness](https://arxiv.org/abs/2406.04268) as a research question about
novelty and learnability, not a guarantee inferred from a finite upward curve.
[Improvement Fidelity](https://arxiv.org/abs/2609.32677) motivates checking update
effects under the deployment conditions those updates induce.

## Planned engineering prerequisites

These existing gaps remain open. Address them where required by a study; an
unrelated missing capability need not block an independent research experiment.

- Implement regression replay, consistency measurements, and scenario generation
  for C; require real coverage before claiming subjective improvement.
- Enforce both evidence components before allowing A+B execution.
- Define per-step review behavior for `--mode gated`.
- Add improvement signals for changes that leave an already-green test suite unchanged.
- Broaden independently verified facts beyond the current EDGAR path.
- Measure live provider diversity and operating-system isolation in supported deployments.

## Research maintenance and evidence

Keep reusable principles, phase status, and public source links in the tool.
Keep full literature notes, briefs, experimental results, documentation-impact
records, and review receipts in the verified PRIVATE versioned companion under
the [storage contract](DATA.md), without a public-repository fallback.

For each design decision retain the problem, supporting sources and counterevidence,
hypothesis, experiment, decision, and conditions for reconsideration. Track first
publication, revision, and reading dates separately; a new revision date alone is
not a new scientific result. Update this roadmap when evidence changes a priority,
and update PHILOSOPHY and the entry documents when a supported design is adopted.

A planned item is not an implemented capability, a validation receipt, or a
release commitment.
