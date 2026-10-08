# Runtime

## Configuration

The target must have Git history and usable evaluation evidence. Runtime DATA
uses exactly `<companion>/data/`; arbitrary subdirectories and the companion root
are rejected before writing. The directory may be absent when its existing
companion repository is selected. Discovery order is:

1. `SELF_EVOLVE_DATA_DIR`, the absolute `<companion>/data/` path.
2. `SELF_EVOLVE_CONFIG`, the absolute companion repository root.
3. `SELF_EVOLVE_CONFIG_DIR`, the equivalent companion-root alias.
4. Proved `self-evolve-config` sibling candidates from the shared resolver.
5. `~/.self-evolve-config`, then the legacy `~/.self-evolve-data` candidate.

Home and sibling candidates still require PRIVATE Git proof and the same `data/`
layout. The legacy home name is usable only as a companion repository root.
An invalid explicit selection fails; it never falls through to another store.
When switching A to B, clear inherited DATA_DIR and CONFIG_DIR before setting
CONFIG to B, or set DATA_DIR explicitly to B's `data/`. Use `doctor` to inspect
the resolved `private_data.path` before `init`; repeat for A to verify switching
back. This is storage selection, with no separate settings migration or registry.
Clone the intended PRIVATE companion, refresh its PRIVATE visibility receipt,
select it, inspect doctor, then `init` to create a run. Missing data does not
authorize an unversioned directory or a new companion repository.

Real run state, model scratch and reports stay in that companion. Source-only
Git working copies use `<companion-parent>/.worktrees/self-evolve/<companion-name>/`
`<target-key>/<run-id>/`. They are transient TOOL copies, outside persistent
DATA, and must not serve as a destination for real run records. They retain
native detached Git worktree and resume semantics. Existing candidates in
`data/targets/<target-key>/worktrees/<run-id>/` are resumed only after validating
their Git ownership; they are never silently moved or removed. Review their
active dependencies before an explicit `git worktree move` to the new layout,
and reconcile frozen profile paths before resuming. Legacy nested candidates
remain a visible companion inventory exception until that migration is complete.
Storage and retention are defined in [DATA.md](../DATA.md).

Before writing, the runtime uses the pinned guards kit to authorize the concrete
artifact against this source's storage contract and prove the actual
filesystem repository and its effective fetch/push destinations. A fresh PRIVATE
GitHub receipt in `~/.pii-guard/visibility.json` is required. Its `_refreshed`
timestamp must include a timezone and be no older than 30 days. Public, unknown,
stale, or missing proof blocks writing; there is no fallback into the tool repo.
A private enclosing repository does not authorize an unproved nested repository.
Missing ownership, ambiguous declarations and a missing authorization helper
also stop writes before parent creation. Target, state and manifest JSON staging
has exact transient declarations separate from the retained final artifacts.
Archive and holdout subtrees keep their existing core recovery protection.

Keep the guards submodule available. Unsupported transport overrides and ambiguous
aliases require resolution, not bypassing proof. EDGAR identity and caches must
also be configured privately when factual verification is needed.

## CLI

Use `python -m tools.sie.cli` from the repository, or
`python <absolute-skill-path>/tools/sie_cli.py` from any cwd.

| Command | Required arguments | Behavior |
| --- | --- | --- |
| `doctor` | `--target` | Prints local prerequisites and capability gaps without model calls or runtime writes |
| `init` | `--target` | Creates a private run directory; optional `--run-id`, otherwise generates a 12-character hex ID |
| `run` | `--target --run-id` | Starts or resumes the loop and prints its summary |
| `status` | `--target --run-id` | Reads state, archive Pareto records, and pending actions |
| `replay` | `--target --run-id` | Prints state reconstructed from the event log |
| `rollback` | `--target --run-id --vid` | Restores the selected snapshot into archive `current/` |
| `storage` | `--target --run-id` | Inventories names and sizes; `--write-manifest` saves one bounded report in an existing private run |

A run ID must be a single nonempty path component. Doctor exits zero when the
target directory exists, even if private storage is unavailable. Read
`private_data.available` and its reason. Status and replay can return
`uninitialized` with exit zero; this does not prove a run exists.
Storage exits 1 when unknown entries need review and 2 on an I/O or boundary
failure. A missing run is read-only `uninitialized`; an explicit manifest write
to that missing run fails.

Run options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--base-ref` | `HEAD` | Git revision used for the baseline |
| `--max-rounds` | `3` | Additional rounds for this invocation |
| `--proposer` | `builtin` | `builtin`, `llm`, or `llm-artifact` |
| `--reflect-mode` | `serial` | Deterministic `serial` or model-backed `parallel` reflection |
| `--live` | off | Overrides proposer to `llm` and reflection to `parallel` |
| `--single` | off | Requests one reflector and skips proposal cross-checks |
| `--mode` | `auto` | `auto` or `gated`; this flag does not implement per-step review |
| `--self` | off | Creates the frozen selfboot path and enables immutable enforcement |
| `--enforce-immutable` | off | Enables immutable patch restrictions without requiring selfboot |

`--mode` participates in the pure-C review fallback; other evidence and review
gates still apply. No `review`, `land`, or `diff` CLI command is implemented.
Use the returned verdict and evidence, not process success alone, to report results.

## Proposals and model calls

The builtin proposer converts supplied `file_rel` and `fix_content` into
proposals; it does not discover new repairs. Serial reflection preserves prior
records or inventories source files when history is empty.

The `llm` proposer requests code changes; `llm-artifact` requests a structured
JSON artifact. The former can fall back to supplied builtin fixes while retaining
backend failures. Artifact proposals do not fall back to the code generator.

All model calls use installed `llmcall`: agent work calls
`llmcall.call(prompt, mode="agent")`, and text decisions use default judge mode.
Routing, model, effort, timeout, and fallback remain at installed defaults.
Legacy compatibility arguments do not override that policy.

Each agent call uses a disposable cwd in the PRIVATE companion and leaves the
parent cwd unchanged. Results retain actual provider, normalized family, attempts,
policy metadata, and errors. Only successful known, different actual families
establish heterogeneous review. Requested aliases and preflight checks cannot
prove independence; insufficient independence remains an explicit failure.

Malformed results, missing artifacts, and backend failures remain visible even
when a fallback yields no proposals. Failure to preserve this evidence stops the caller.
Legacy JavaScript launchers are disabled.

## Resume and recovery

The loop derives state from append-only events and freezes the target profile on
its first run. Resume reuses that profile, recorded reflections, accepted versions,
and the next round number. Keep the original target, base revision, and mode options.

`replay` reconstructs and prints state without rewriting `state.json`.
`status` reads the saved snapshot. Run resumes from the event log, so deleting a
state file is unnecessary.

A usable selected-parent baseline is required before acceptance. Missing grading
or unknown parents produce `BASELINE_UNAVAILABLE`. Rejection restores the selected
parent, including removed and added files. A failed restoration records
`RESTORE_FAILED` and stops further iteration.

Holdout cadence advances only after a durable measured decision. Interruption
between measurement and decision keeps the check due on resume. Static rejection,
unavailable measurements, and evaluated decisions have distinct counter semantics.
Review queues and circuit breakers preserve reasons; they do not lower acceptance
thresholds.

Accepted versions use persistent IDs. The archive writes a business-tree snapshot,
adds a lineage record, then records ACCEPT. These writes are not one transaction:
an orphan snapshot after a crash is not proof of acceptance. Existing accepted
snapshots cannot be overwritten. Scores and per-task records are stored separately.

Rollback writes a recovery copy at archive `current/`. It does not change the
target branch or replace the candidate worktree.

## Selfboot and isolation

`--self` materializes decision code from the base revision, checks its digests,
and gives the frozen grader and acceptor to a Supervisor. The same canonical
candidate tree is patched, graded, and archived. Baseline and candidate use the
same frozen per-task grader. The immutable set is defined by
`tools/sie/immutable.py:IMMUTABLE_RELPATHS`.

Selfboot supports A evaluation. B or C under the supervisor is refused. Reopening
a frozen run requires its existing files to match the committed base; mismatches
are not overwritten.

Path containment and Python AST checks reject recognized dangerous operations.
They do not prove protection against arbitrary indirection, filesystem races,
native code, or same-account access to frozen files. Worktrees, prompt truth
filtering, and disposable cwd are not operating-system isolation.

Pytest grading has a finite positive timeout, default 600 seconds, configured by
`SIE_GRADER_TIMEOUT`. Execution probing has its own `SIE_EXEC_PROBE_TIMEOUT`.
Timeouts remain unavailable observations. Terminating the direct pytest child
does not establish containment of arbitrary descendant processes.

## Implementation map

| Concern | Source |
| --- | --- |
| Commands and loop | `tools/sie/cli.py`, `statemachine.py` |
| Runtime destinations | `runtime_data.py` |
| Calls and proposals | `agents.py`, `llm_adapter.py`, `reflect.py`, `propose.py` |
| Patch checks | `patch.py`, `immutable.py` |
| Persistence and recovery | `events.py`, `state.py`, `archive.py`, `business_tree.py` |
| Frozen evaluation | `selfboot.py`, `supervisor.py` |

Evaluation requirements are in [evaluation.md](evaluation.md).
