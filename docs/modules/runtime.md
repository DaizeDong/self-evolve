# Runtime configuration and model calls

The runtime uses the installed `llmcall` interface. Agent tasks call
`llmcall.call(prompt, mode="agent")`; judge decisions omit the mode argument.
Routing, model, effort, timeout and fallback settings remain at installed defaults.
Compatibility parameters in older Python signatures do not override that policy.
The old JavaScript provider launchers are disabled and return a nonzero status.

`llm_adapter.py` validates synchronous terminal results and keeps their actual
provider, normalized family, attempts and failure details. `codex` and `codexg`
belong to one known family; `cc` and `claude` belong to another. Unknown families
cannot prove independence. Requested aliases are informational. A second review
can use llmcall's `avoid` argument with the actual prior provider.

Agent calls use the packaged Python helper `llm_agent_child.py`. JSON travels on
stdin; the child runs in a separate temporary cwd inside the PRIVATE companion.
The parent process never changes cwd. Each call cleans its own temporary directory
after success or failure. This preserves the patch gate's control over candidate
edits, but does not establish an operating-system sandbox against malicious code.

Set `SELF_EVOLVE_CONFIG` to a PRIVATE Git companion or `SELF_EVOLVE_DATA_DIR` to
an absolute directory in it. The pinned guards kit supplies discovery; the runtime
additionally verifies Git origin, canonical containment and a current PRIVATE
entry in `~/.pii-guard/visibility.json`. The `_refreshed` timestamp must include a
timezone and be within the past 30 days. No proof means no runtime write. Real
records remain versioned in the private companion.

Every target has a namespace under the private data root. Run state, candidate
worktrees and calibration reports use that namespace. EDGAR caches are distinct
private directories, and EDGAR_IDENTITY must be configured privately. Earlier
cache records are preserved.

Direct writers validate the actual destination against the configured companion,
including nested Git repositories. Profile holdouts, human-review queues, event
logs, frozen profiles, snapshots and grader scratch all require that proof before
writing. An enclosing private repository does not authorize a nested repository.

The loop requires a usable baseline for its selected parent before acceptance.
Missing or failed grading, empty dimensions and unknown parents pause
with a structured `BASELINE_UNAVAILABLE` event. Task pairing uses test identities.
Rejection mirrors the selected snapshot, including created and deleted files,
while preserving Git metadata. A failed restoration writes `RESTORE_FAILED` and
stops before another reflection or evaluation. B-tier comparisons preserve the frozen visible identities and spans, using the selected
parent only for their values. Missing candidate facts score zero. Sampled holdouts require
pinned content, disjoint identities and independently observed correctness on both sides. Accepted snapshots and version IDs
are retained when a run resumes.

Holdout sampling advances only after a measured round records a durable ACCEPT, REJECT,
CONTINUE or evaluated human-review decision. A measurement marker alone remains pending:
interruption before evaluation, decision calculation or decision writing keeps the holdout
due on resume, even off the original modulo cadence. An unrelated later round cannot
consume that pending marker. Older human-review events without an explicit evaluated flag
conservatively leave the holdout due. Reaching an ACCEPT, REJECT, CONTINUE or post-evaluation
human-review outcome clears the consecutive static-rejection count. Pausing for
unavailable baseline or C-tier evidence does not clear that count.

Candidate pytest grading has a finite positive timeout, defaulting to 600 seconds and
configurable through `SIE_GRADER_TIMEOUT`. Invalid limits raise an error. Both raw graders
propagate timeouts so mutation testing cannot count them as killed mutants. The normal
and frozen candidate loops reject timed-out grades, record the reason and restore the
selected parent. The timeout terminates and waits for the direct pytest child; it does
not establish containment of arbitrary descendant processes.

Use `python <absolute-skill-path>/tools/sie_cli.py doctor --target <target>` from
any cwd. Doctor lists evidence providers, patchable scope, required inputs, model
policy and scenario-evaluation status without model calls or runtime writes.
Automatic scenario generation remains unimplemented. Empty regression or
consistency evidence cannot establish no-regression success.

`IMMUTABLE_RELPATHS` protects the decision code and its runtime/model adapters.
Provider metadata, valid score spans and finite scores in `[0, 1]` are necessary
inputs, not proof of improved user outcomes. Preserve candidate and oracle hashes,
independent reviews and actual test evidence before claiming acceptance.


Current execution accepts individual A, B or C signal paths. Profiling may detect A+B,
but run_loop refuses that composite before proposing or patching until both components
can be enforced. Selfboot uses one canonical candidate tree for patching, frozen grading
and archived snapshots. The same frozen per-task grader measures its baseline and candidate.
Reopening a frozen run reuses existing read-only files only when their exact bytes match
the committed base. A mismatch is refused without overwriting the existing file.

Archive schema 1 stores finite Pareto coordinates in scores and preserves per-task records
separately in task_dimensions. Legacy records are normalized and validated on read.
Calibration WORKS requires at least four valid repairs, a successful final suite with passing
test observations, and a complete baseline, loop, event and attribution chain. BROKEN and
failed completion return nonzero; downstream errors retain the partial report.

The AST gate recognizes simple imported and assigned aliases, keyword open paths and
basic pathlib expressions. It rejects outside or unprovable paths for recognized filesystem
operations. Arbitrary Python indirection, runtime capabilities, filesystem races and ambient
permissions still require an operating-system boundary; passing a static scan proves none
of those properties. Relative literal paths resolve against the sandbox cwd, including
when the file being patched is in a subdirectory. Execution must use the same cwd.

## PRIVATE destination proof

Runtime writes use the pinned guards kit to bind the actual filesystem repository and
check both its physical and effective fetch/push destinations. Process Git selectors cannot
borrow another repository's PRIVATE receipt. A public, unknown or unproved destination blocks
the write before output directories are created; no public-worktree fallback is available.

Use canonical GitHub HTTPS or SSH remotes with fresh PRIVATE receipts. The shared kit rejects
ambiguous aliases and unproved transport overrides. The legacy URL parser remains available
for compatibility, but parsing an alias alone does not authorize a runtime destination.
Missing guards files or proof APIs require updating the submodule, not bypassing validation.
