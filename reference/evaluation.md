# Evaluation

An accepted result needs comparable parent and candidate measurements, valid
inputs, and every applicable acceptance gate. Valid JSON, exit zero, or no
observed regression alone does not establish improvement.

## Signal paths

PROFILE freezes the evidence source for a run. A, B, and C describe evaluation
paths, not capability grades.

| Path | Evidence | Current execution boundary |
| --- | --- | --- |
| A | Executed tests paired by task identity | Requires a usable baseline and no passing task regression |
| B | Independently verified frozen facts | Requires identity-preserving pairs, coverage, independent anchors, and holdout checks |
| C | Supplied regression, consistency, and judge evidence | APIs validate supplied evidence; the loop has no regression or consistency producer |

Profiling may detect A+B. The loop refuses it before proposals or patches because
both acceptance components are not enforced. Other composite labels containing B
dispatch through B; a label does not prove every component ran. Automatic
scenario generation is unimplemented.

## A: tests and parent pairing

The execution probe requires tests, a successful nonempty baseline, and a detected
source mutation. It works in a private worktree and restores the mutated source.
One detected mutation proves sensitivity to that mutation, not general test adequacy.

Grader records include:

| Field | Meaning |
| --- | --- |
| `task_passed` | Overall grader verdict, interpreted with process and per-task evidence |
| `grader_exit_code` | Test exit code; infrastructure errors, no collected tests, and timeouts are not passing observations |
| `dimensions` | Named records carrying tier, score, and weight |
| `task_dimensions` | Per-task observations also retained by `grade_pytest` for frozen evaluation |
| `anchors` | Factual records, empty on an ordinary A path |
| `verifiable_coverage` | Grader coverage field, not proof that all user behavior was tested |

Ordinary A execution obtains per-task records through
`_grade_pytest_per_task`. Frozen evaluation projects `grade_pytest`'s
`task_dimensions` to the same units. A legacy aggregate baseline retains
aggregate semantics and cannot establish per-task evidence.

`pair_parent_dimensions` matches by task name. A missing candidate task still
enters comparison with after-score zero; new candidate tests cannot replace
parent obligations. The loop pauses when it cannot establish a usable selected-parent
baseline. Direct low-level evaluation does not perform every loop-level check.

Any paired passing task that regresses causes A rejection. Otherwise the statistical
acceptance condition must also pass. A never uses CONTINUE to accumulate evidence.
If every pair is unchanged, the result requests human review as
`unobservable-by-tier-A`; an already-green suite provides no pass-count headroom.

## B: facts and holdouts

B compares parent and candidate correctness over frozen visible identities and
spans. Numeric facts match `(cik, metric, period)`. Missing, renamed, or ambiguous
candidate facts score zero for the original obligation. New facts do not replace
frozen ones.

The evaluator produces `b_paired`, visible gain, coverage over frozen spans, and
holdout gain on sampled rounds. Both gains and losses matter. B accepts by net
evidence and its own gates; it does not provide A's per-task no-regression guarantee.

Sampled holdout evidence needs a pinned path, positive count, canonical JSON
SHA-256, disjoint identities, and independently measured correctness for both
sides. Missing proof, changed content, overlap, and unavailable verification block
approval. Legacy profiles missing the digest need reinitialization.

Same-source clustering reduces effective anchor count. More correlated rows do
not create independent evidence. Anchor count, effective independence, coverage,
statistical evidence, and visible/holdout divergence all affect the verdict.
The current factual verifier uses EDGAR; synthetic anchors exercise mechanics
and never establish financial correctness.

## C and judges

`evaluate_c_tier` validates nonempty regression replay and finite consistency
pairs supplied by its caller. Both must be available before it can assert
`no_regression`. It reports availability and evidence status explicitly.

The main loop currently supplies empty lists for both inputs, so those observations
are unavailable and C pauses for review. Historical ACCEPT records cannot replace
fresh candidate measurements. Coverage remains zero; no automatic scenario or
rubric generator supplies it.

Text judges use installed llmcall policy and retain actual provider metadata.
Only valid results from known different families support independence checks.
Agreement without measured improvement is a review signal, not proof of collusion.
Prompt filtering excludes verification truth; filesystem isolation requires a
separately verified deployment boundary.

The loop's reflection check validates structure. `check_benchtrace` is a separate
trace-reference API, not an integrated proof that all findings are grounded.

## Mutation grader failures

`mutation_validity_gate` expects a Boolean grader. A false or ordinarily failing
baseline yields an invalid result with no killed mutants. A baseline
`BaseException`, such as interruption, propagates.

For a completed mutant evaluation, false counts as killed and true as survived.
A grader error or timeout aborts without partial kill credit, including at a zero
kill-ratio threshold. The gate attempts byte-for-byte source restoration; only
successful restoration guarantees the original bytes. Restoration failure
propagates and may retain the grading error as context.

A completed result contains `valid`, `killed`, `total`, `kill_ratio`, and
`survivors`. It needs at least one mutant. UTF-8 decoding and newline normalization
select mutations; restoration uses the original byte sequence.

## Supporting checks

Generate public fixtures with `tools/make_fixtures.py`. Real selected artifacts
and reports must follow [DATA.md](../DATA.md).

`scripts/validate_btarget.py --synthetic` checks structural B classification in
private scratch. `--artifact <absolute-private-json>` selects a real private
input. It does not verify facts or demonstrate ACCEPT. Optional `--live` requests
one llmcall proposal and reports its structure.

`scripts/setup_btarget_repo.py` requires either input choice plus
`--private-remote <remote>`. The destination stays beneath the verified private
data root; the target's own remote needs PRIVATE proof. Setup uses Git identity
and hooks and does not push.

Calibration remeasures each oracle for every accepted snapshot. Imported helpers
or configuration can change outcomes even when a defect-bearing file is unchanged.
Its report separates measurements from errors; WORKS requires the full evidence
chain, at least four valid repairs, and a successful final suite with observed tests.

## Reporting a result

Report the source and candidate revisions, actual task or fact population,
measurement failures, acceptance reason, independent-review evidence, and coverage
gaps. Keep offline fixture results separate from live runtime and user-outcome evidence.
Statistical claims require [acceptor_math.md](acceptor_math.md); repeated proposals
have no established run-wide alpha bound.

Implementation: `profile.py`, `probes/`, `verifiable.py`, `evaluate.py`,
`acceptor.py`, `judges.py`, and `statemachine.py` under `tools/sie/`.
