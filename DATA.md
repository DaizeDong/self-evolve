# Runtime storage contract

Real runtime DATA belongs in a verified PRIVATE Git companion. The public tool
contains this contract, code and synthetic fixtures. `runtime_data.py` resolves
`SELF_EVOLVE_DATA_DIR`, `SELF_EVOLVE_CONFIG`, or `SELF_EVOLVE_CONFIG_DIR` in that
precedence; sibling and home discovery follow. The DATA root is always exactly
`<companion>/data/`, including when that directory does not yet exist. Missing
PRIVATE proof or source-contract ownership fails before writing. No companion-root
or public-worktree fallback is allowed. Full initialization and switching steps
are in [runtime configuration](reference/runtime.md#configuration).

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
| SCRATCH | Named interpreter, test and dependency caches | Working execution copies; their classification does not authorize removal. |
| UNKNOWN | Every other run file | Review its writer and recovery use before deciding retention. |

Model-stage writers omit a successful raw response only when its complete JSON
content exactly matches retained findings or proposal fields. Those outcomes use
`result_storage: "parsed"`; proposed file contents remain byte-preserving strings.
Provider identity, attempts, errors, diagnostics and decision evidence remain.
Failed, unmatched, ambiguous or extra-field responses retain their raw text.
The early reflector ledger remains durable before aggregation can fail. Existing
ledgers are not rewritten. `outbound_seq.jsonl` is also read by the live
sequence-anomaly check.

The four run evidence ledgers and metadata manifest have exact contract entries.
Review requests outside a run use only `data/human-review/<run-id>/pending_actions.jsonl`.
Target, state and manifest JSON staging use exact `.tmp` siblings with transient, rebuildable retention;
empty structural containers admit only directory creation, and file writers
reject their artifact IDs. They own no child files. Every final file write is
authorized against the pinned source contract before its parent is created.
Runtime writers stay within the selected `data/` tree; companion-root metadata
entries belong to maintenance and cannot receive runtime output.
Existing archive and holdout subtree declarations retain core protection;
interrupted staging there requires recovery review before removal.

New candidate and probe Git worktrees are source-only TOOL copies at
`<companion-parent>/.worktrees/self-evolve/<companion-name>/<target-key>/<run-id>/`.
The producer no longer creates nested Git worktrees inside the DATA contract.
Existing legacy candidates retain their path for validated resume and remain
visible inventory exceptions until reviewed migration. They are not permanent
core evidence; keep accepted snapshots and frozen run records in the companion.

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
the retained run no longer depends on them. Age alone never proves inactivity.
The reviewed retirement command below is separate from metadata inventory. Disposable agent directories have
context-managed cleanup; other scratch can survive interrupted processes.
Hidden oracle files now use admitted `grader-work/sie-oracle-*/` directories and
are removed when that oracle invocation finishes. Any historical
`calibration-checks/` content remains an inventory exception pending review.
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

## Companion lifecycle

The machine-readable artifact contract is [storage.contract.json](storage.contract.json).
Its paths are relative to the exact PRIVATE companion repository root, including
the `data/` prefix used by the default runtime layout. Each artifact records its
producer, consumer or final deliverable, schema and recovery method. The shared
checker inventories that whole root, including companion setup metadata; selecting
only `data/` does not establish repository coverage. The companion README identifies
selected final deliverables. Runtime records never fall back into this public repository.

The runtime validates the exact `data/` layout before any writer is admitted.
`tools.storage_retention` projects only declarations inside that freshly proved
scope before planning. Existing records and registries are never moved automatically.

Keep a current `retention.json` in DATA, following
[schemas/storage-retention.schema.json](schemas/storage-retention.schema.json).
List active runs, supported rollback dependencies and selected final evidence in
`protected_paths`. A retirement entry requires completed work, released dependencies
and a concrete reason. Unknown files and core artifacts are refused even when a
retirement entry claims completion. Stop writers before maintenance; age is not
an inactivity proof. Preview with `python -m tools.storage_retention`, then apply the
reviewed selection with `python -m tools.storage_retention --apply`.

The command checks confinement, link metadata, content hashes and core protection
before removing ordinary files. It never follows junctions or rewrites event logs.
The registry is one current document, not a sequence of timestamped backups.
Restore retired bytes from its `source_commit` in the existing PRIVATE Git history.
Keep that commit reachable; no new archive bundle is required.

The historical catalog and original event bytes stay on hold while attribution,
selected evidence or recovery obligations remain. Catalog presence does not prove
resume or rollback capability. Necessary current conclusions must be retained
before the owner considers historical retirement. Final research, adopted roadmap
materials and unique cited dependencies keep their existing core protection.

Observed empty legacy run, worktree, snapshot and holdout containers are declared
at their exact container paths. They remain temporarily core on hold for target
and restoration review; replacing a container with a file stays protected, and
child files do not inherit those declarations. The owner must approve a later
reclassification after the obligations close. Do not refill or replicate empty old
execution scaffolding, and do not infer that empty directories preserve accepted
run snapshots. Current run and accepted-parent dependency declarations remain core.

Generated-area admission refuses further writes once existing usage reaches
2,000 files or 128 MiB. The check measures current usage before a writer receives
its destination; it is an admission limit, not a per-write reservation. Core
purchase records, final research, event chains and recovery snapshots are never
evicted to make room. Self-evolve additionally stops admitting new runs at 32
retained run directories; existing runs can continue. Review completed work and
its recovery obligations before reclaiming capacity.
