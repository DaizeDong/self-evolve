# Documentation lifecycle and handoff

These are contributor and workflow obligations. The current runtime freezes its
profile and selfboot decision code; it has no automatic documentation-completeness
gate or review/landing CLI. Record the following in the change's PRIVATE working
evidence and handoff rather than assuming the loop enforces it.

## Record documentation impact before implementation

Identify the behavior being changed, source base revision, allowed files, affected
entry documents, and an explicit reason for each document that needs no change.
Use the target repository's own document contract and repository kind. A PRIVATE
companion needs maintenance and DATA guidance; it does not need an invented plugin
manifest or the public tool's complete document set.

| Change affects | Review and update where applicable |
| --- | --- |
| Purpose, design choices, or tradeoffs | Both READMEs and PHILOSOPHY.md |
| Trigger, workflow, or acceptance obligations | SKILL.md and the relevant reference |
| Installation, configuration, or CLI | Both READMEs, configuration/data contract, and runtime reference |
| Evidence, support limits, or recovery | Evaluation, DATA, and runtime references; README limitations |
| Delivered capability or future work | ROADMAP current/future distinction and CHANGELOG Unreleased |
| Release version | The target's authoritative manifest and linked version sites, using its version tooling |

Public examples must be generated synthetic fixtures. Keep real observations,
private infrastructure details, and change evidence in a PRIVATE companion.

## Preserve the evaluator freeze; finish the candidate before review

1. Before implementation, freeze the goal, evaluator policy, comparison
   obligations, holdout, and required review method. Preserve existing frozen
   profiles when resuming. A changed evaluation goal needs a new contract.
2. Implement within the allowed scope and update affected documentation in the
   same candidate. Finalize current capability statements, EN/CN parity, important
   Unreleased records, and any authorized version updates. Keep historical release
   facts and label planned work accurately. Do not bump a version just to repair docs.
3. Freeze the complete candidate before independent review: record its commit or
   exact snapshot, diff, document-impact decisions, and checks. Runtime archive
   retention is not proof that this documentation review happened.
4. Review that candidate and run the applicable documentation contract, link,
   style, security, and affected behavior checks. Record unavailable checks and
   their reasons. A check's process success alone does not establish its coverage.
5. If review changes the candidate, identify the new snapshot and repeat the
   affected review and checks. Do not attach a prior approval to changed bytes.

Keep long design rationale here or in PHILOSOPHY.md and link it from the entry.
Entry simplification must preserve reasons, tradeoffs, and current boundaries;
moving a section is complete only when the destination remains reachable.

## Handoff the reviewed result

Record the base and reviewed candidate revisions, changed files, documentation
impact and no-change decisions, exact check results, independent-review evidence,
acceptance reason, remaining limits, and PRIVATE recovery location. Distinguish
synthetic/offline checks, live observations, and checks not run.

State whether installation, merge, publication, and any outbound action occurred
or remain pending under the caller's authorization. Keep candidate worktrees and
recovery dependencies until the authorized integration and verification finish;
the storage classification alone does not authorize cleanup.
