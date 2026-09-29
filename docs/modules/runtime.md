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
stops before another reflection or evaluation. B-tier comparisons use anchors
from the selected parent. Accepted snapshots and version IDs
are retained when a run resumes.

Use `python <absolute-skill-path>/tools/sie_cli.py doctor --target <target>` from
any cwd. Doctor lists evidence providers, patchable scope, required inputs, model
policy and scenario-evaluation status without model calls or runtime writes.
Automatic scenario generation remains unimplemented. Empty regression or
consistency evidence cannot establish no-regression success.

`IMMUTABLE_RELPATHS` protects the decision code and its runtime/model adapters.
Provider metadata, valid score spans and finite scores in `[0, 1]` are necessary
inputs, not proof of improved user outcomes. Preserve candidate and oracle hashes,
independent reviews and actual test evidence before claiming acceptance.
