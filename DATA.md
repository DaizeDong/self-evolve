# Runtime storage contract

Real runtime DATA belongs in a verified PRIVATE Git companion. The public tool
contains this contract, code and synthetic fixtures. `runtime_data.py` resolves
`SELF_EVOLVE_CONFIG` or `SELF_EVOLVE_DATA_DIR`; missing PRIVATE proof fails before
writing. No public-worktree fallback is allowed.

## What a current run retains

| Category | Paths relative to a run | Purpose |
| --- | --- | --- |
| CORE | `events.jsonl` | State transitions, round history and holdout progress. |
| CORE | `target.json`, referenced `_holdout/holdout.json` | Frozen evaluation obligations and held-out evidence. |
| CORE | `base-snapshot/` | Exact initial business files until a retained accepted parent exists. |
| CORE | `archive/lineage.json`, `archive/versions/<vid>/snapshot/` | Accepted parent scores and each retained rollback target. |
| CORE | `pending_actions.jsonl` | Human requests and their subsequent resolutions. |
| CORE | `_frozen/` for self mode | Frozen decision code used by the current supervisor. |
| DERIVED | `state.json`, `archive/current/`, `storage-manifest.json` | State projection, requested rollback output and metadata inventory. |
| EVIDENCE | `reflections.jsonl`, `reflector-outcomes.jsonl`, `proposals.jsonl`, `outbound_seq.jsonl`, `archive/retired.jsonl` | Existing diagnostic or decision evidence outside the state reducer. |
| SCRATCH | Candidate worktrees and named interpreter, test and dependency caches | Working execution copies; their classification does not authorize removal. |
| UNKNOWN | Every other run file | Review its writer and recovery use before deciding retention. |

Model-stage writers omit a successful raw response only when its complete JSON
content exactly matches retained findings or proposal fields. Those outcomes use
`result_storage: "parsed"`; proposed file contents remain byte-preserving strings.
Provider identity, attempts, errors, diagnostics and decision evidence remain.
Failed, unmatched, ambiguous or extra-field responses retain their raw text.
The early reflector ledger remains durable before aggregation can fail. Existing
ledgers are not rewritten. `outbound_seq.jsonl` is also read by the live
sequence-anomaly check.

Accepted changes need recoverable bytes: an exact retained snapshot, or a future
verified base revision plus complete change records including additions and
deletions. A digest alone cannot recreate a candidate. Current code uses complete
snapshots; it has no supported compact replacement for them or for the event log.

## Recovery boundaries

`events.jsonl` reconstructs `RunState`, round history and holdout cadence. Resume
also requires the frozen profile, selected archive scores and source snapshot.
A baseline additionally uses the profile's external probe worktree. B holdouts
require the separately referenced file and frozen content identity. Self mode
also requires its frozen oracle and exact base revision. None of these external
dependencies is verified by a metadata inventory.

Keep `state.json` for the current status command: it is derived, but the replay
command only prints its reconstruction. Missing `target.json` currently triggers
profiling again; missing `base-snapshot/` can snapshot the current candidate.
Neither is a safe cleanup operation. Resume starts another round rather than
continuing an interrupted phase. Archive acceptance writes snapshot, lineage and
event separately, so an interrupted write needs reconciliation. CLI rollback
materializes `archive/current/`; it does not change the future selected parent.

Candidate trees, profile probes, `agent-work/`, `grader-work/`, `edgar-cache/` and
`calibration/` may be removed only after an explicit activity check and proof that
the retained run no longer depends on them. The tool has no durable inactivity
contract and performs no automatic deletion. Disposable agent directories have
context-managed cleanup; other scratch can survive interrupted processes.
New run, probe and self-mode worktrees use detached HEAD without creating branches;
resuming an existing worktree preserves its checkout and uncommitted changes.

Snapshots omit `.git`, `.sie`, `__pycache__` and the conventional cache directories
`.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `.nox`, `.venv` and
`node_modules`. Snapshot, comparison and restoration use the same exclusions;
restoration leaves existing excluded directories in place. Comparison requires
every business entry in the source snapshot, including its empty directories.
Only extra destination directories containing exclusively recognized ordinary
cache directories may remain. Ordinary `data/`,
`build/`, `dist/`, reports and other target inputs remain business files.

## Metadata inventory

`python -m tools.sie.cli storage --target <target> --run-id <id>` calls
`tools.sie.storage.inventory(target, run_id, write=False)` using the existing
PRIVATE resolver and inspects file names, types and sizes only. It never opens
or hashes source, event, prompt or result payloads. The default is read-only;
`--write-manifest` (`write=True`) writes one `storage-manifest.json` in an existing run. The manifest
excludes itself, contains fixed category totals and at most 64 issue paths, and
follows `schemas/storage-manifest.schema.json`. It is deterministic for unchanged
filesystem metadata. Entries observed as links are reported without traversal;
I/O errors fail the operation. The scan is not atomic: concurrent replacement
can change a directory after inspection or produce a mixed-time view.

`status` is `uninitialized` for an absent run, `review_required` for unknown files,
empty unknown directories or unsupported entries, and otherwise `inventoried`.
`unknown_count` counts those findings, including links that were not followed.
The scope is one run and its normal/self candidate worktrees. Shared scratch and
external profile dependencies are outside that scope. `UNKNOWN` files stay
visible. `cleanup_allowed` and `recovery_verified` are always false: inventory
does not establish inactivity, payload validity or resumability.

## Historical runs

A legacy run may retain its original event bytes and a PRIVATE catalog following
[`schemas/history-catalog.schema.json`](schemas/history-catalog.schema.json).
The catalog records source commit and paths, file/event counts, event digests,
and shared contract gaps. `state_replay_input_retained=true` records input
retention; `resume`, `rollback` and `recovery_verified` remain false when the
required dependencies are absent.

An optional `state_reduction_check` records strict JSON-object line validation
and execution of the identified current reducer. It does not establish agreement
with the old saved state or verify resume/rollback. Recover original files from
the referenced PRIVATE Git commit when needed. Keep that existing history as the
recovery source instead of duplicating retired worktrees, logs or bundles.
