# self-evolve SDD progress ledger

plan: docs/superpowers/plans/2026-06-21-self-evolve.md (52 tasks)
branch: feat/self-evolve
base: ecf585a

Task M1a.1: complete (commits ffe7500..a26ba85, review clean after fix)
Task M1a.2: complete (commits f050b7c..5a43a9b, review clean after fix)
  minors-for-final-review: events.replay init uses ""/None mixed sentinel; _DIRECT silently ignores direct counter writes in events
Task M1a.3: complete (commits 146fbea..4cf3267, review clean after fix; security boundary approved, no bypass)
  minors-for-final-review: symlink-escape test skipped on Windows (logic verified, POSIX CI covers)
Task M1a.4: complete (commits 7b6eb36..abcf272, review clean after fix; mutation-test fake-grader defense verified)
  minors-for-final-review: _pick_src single-file heuristic (import-graph upgrade deferred); pytest timeout=60 fixed
Task M1a.5: complete (commits 6f48d3d..3f59473, review clean after fix; UDP sendto/sendmsg blocked, creds isolated, snapshot lock)
  M2-PREREQ: replace parent-sys.path PYTHONPATH with isolated venv (Python-layer attack surface) [reviewer Important, plan-deferred to M2]
  minors-for-final-review: jail chmod reverted (empty-jail is operative protection); native/ctypes net bypass = accepted residual (spec §6)
Task M1a.6: complete (commits 76c8989..30bd56f, review clean after fix; ImportFrom danger-symbol bypass closed)
  M1b-PREREQ(full AST gate): alias bypass (fn=eval;fn()), importlib.import_module, builtins.__import__ — deferred to M1b full danger-call list
Task M1a.7: complete (commit 7079ac1, review clean, no fix needed; acceptor no-regression fallback, signature locked for M1b PACE)
  minors-for-final-review: placeholder evalue 'improved' counts fail->partial (M1b PACE replaces evalue)
Task M1a.8: complete (commit 786e5b4, review clean, no fix needed; lineage append-only + rollback真恢复内容)
  M3-PREREQ: retire_stale dedup/idempotency; snapshot_version guard (lineage consistency); rollback atomicity (copytree-to-temp+os.replace) for concurrency/crash
Task M1a.9: complete (commit 6e9cae5, review clean, Minors-only no fix; non-blocking enqueue/pending queue)
  CROSS-CUTTING-for-final-review: jsonl readers (events.replay / gate_human.pending / archive lineage) should try/except json.loads skip corrupt lines (crash-safety); gate_human tests should assert all 8 schema fields
Task M1a.10: complete (commit 5b66400, review clean, Minors-only no fix; reflect串行/check弱校验/propose builtin)
  M3-PREREQ: check_reflection drop fix_content from validity keys (semantic; M3 rewrites to BenchTrace); builtin warn on empty proposals; reflect history-branch test gap
Task M1a.11: complete (commit 4e3811a, review clean, Minors-only no fix; evaluate paired direction verified correct)
  M1b-PREREQ: add regression-direction test (before=1.0,after=0.0 -> paired (1.0,0.0)) when M1b rewrites acceptor; coverage hardcoded 1.0 (M2 refine)
Task M1a.12: complete (commits 1bb50c8..190b2c9, review clean after fix; M1a END-TO-END capstone works: full loop+accept+rollback+crash-replay consistent)
  minors-for-final-review: CLI rollback subcommand not e2e-tested (Python API covered); evaluate base_result=None 0.0 baseline (M1b feeds prev grade)
NOTE: M1a.0 (confseq spike, 第0步硬前置) was initially skipped (started at M1a.1). M1a.1-12 used no-regression fallback acceptor (no confseq dep) so no rework. Running M1a.0 now before M1b (which builds real PACE on confseq). If spike fails -> STOP and reselect acceptor approach.
Task M1a.0: complete (commits 62e45b0..856ba0a, gate PASSED; pure-noise false-reject 0.005, drift detect 0.97)
  *** KEY DECISION for M1b acceptor ***
  - confseq real interface: confseq.betting.betting_mart(x, m=0.5) -> stepwise wealth array; max(wealth)>=1/alpha => "gain". x = [0,1]-mapped paired diffs.
  - confseq 0.0.11 does NOT install on Windows+Py3.13 (needs Boost/cmake). Validated only in conda env `confseq_test` (Py3.10).
  - ARCH DECISION: harness stays default Py3.13, confseq OPTIONAL. M1b PACE acceptor: use confseq.betting_mart IF importable else pure-python betting-martingale fallback (_ons_betting_wealth, anticipated in M1b plan). conda env = reference validation only.
  - confseq tests use pytest.importorskip -> skipped in default env, run via `conda run -n confseq_test`.
Task M1a.13: complete (commit cd0b325, review clean, Minors-only no fix; SKILL.md/commands/target_contract honest to M1a state)
  verified ⚠️ accurate: --mode is real CLI flag (cli.py:45); status emits 3 counters (cli.py:94-96); CHECK_REFLECTION exists (statemachine:155)
  minors-for-final-review: test_skill_docs lacks negative assert (review/land/diff not callable); unused import re
========== MILESTONE M1a COMPLETE (14 tasks M1a.0-13) ==========
  Deliverable: A-tier verifiable self-iteration loop end-to-end (init|run|status|replay|rollback), accept via no-regression gate, rollback, crash-replay consistent. Default suite green (~59 passed, 2 confseq skipped).
Task M1b.1: complete (commits c14579b..d6d05a2, security re-review APPROVED; full AST danger gate: subscript/bare/multi-hop-alias/importlib/builtins all blocked, false positives (client.get/db.run) eliminated, no new holes)
  minors-for-final-review: call-result alias (s=socket.socket(); s.bind()) not tracked (backstopped by import prefix); getattr check covers only bare-4 (backstopped by prefix)
  note: brief Consumes signatures were wrong (_import_whitelist_check / apply_patch(worktree,patch)); used actual import_gate / apply_patch(sandbox_root,file_rel,new_content,allow)
Task M1b.2: complete (commit 49af1f3, review APPROVED, Minors-only no fix; mutation_validity_gate: inject_mutants(arith/cmp/bool)+gate(baseline+try/finally restore+valid=total>0&&kill_ratio>=min, default 1.0))
  minors-for-final-review: survivors id format "rel:mut_id" (brief said [mut_id]); and/or BoolOp not mutated (brief optional)
Task M1b.3: complete (commits af684f3..fac9ab1, math re-review APPROVED) *** ANTI-SELF-DECEPTION CORE ***
  - PACE A-tier anytime-valid e-process; e-process STANDALONE type-I false-accept=0.0075 (<=alpha, bypasses hard gate, true null, Ville sup_t W_t)
  - true-gain acceptance=1.00; no-regression hard overlay preserved; A-tier two-state
  - _wealth_betting: confseq.betting_mart if importable else self-contained ONS-betting (default env uses ONS, anytime-valid); lambda-clip +/-(2-1e-6) factor>0 no clamping
  - reference/acceptor_math.md documents sup_t W_t (path-max, Ville) -- supersedes brief "末值"
  - 2 M1a test_acceptor cases flipped (semantic upgrade: no-change/small-sample now REJECT, legit)
  minors-for-final-review: redundant path_max var in type-I test; _true_gain_pairs before_p<0.5 docstring
Task M1b.4: complete (commit 03cdf81, review APPROVED, Minors-only no fix; _decorrelate_downweight 1/size + adversarial tests (small correlated set / subjective drift rejected via real decide chain))
  M2/M3-PREREQ: wire _decorrelate_downweight + effective_independent_anchor_min into decide B-tier (not consumed yet)
  minors-for-final-review: adversarial assert !=ACCEPT should be ==REJECT; _decorrelate_downweight no len-check; in-function imports
Task M1b.5: complete (commit 7fe4224, review APPROVED, Minors-only no fix; gate_human enqueue/pending(latest-status+ttl)/resolve(append-only terminal), non-blocking, M1a compat)
  minors-for-final-review: TTL boundary >= (design choice); test_latest_state_reduction doesn't test same-aid double-resolve (logic correct); _read_all json.loads no try/except (cross-cutting, deferred)
Task M1b.6: complete (commits 51f58ae..91f9516, review APPROVED) -- LIVENESS bug (round-2) CLOSED & integration-tested
  - 3 counters orthogonal, persist via event deltas through _step->replay (verified no double-count), circuits fire, CONTINUE cap landing, A-tier no-CONTINUE guard, PAUSE_FOR_HUMAN non-blocking
  - integration test run_loop forced-REJECT accumulates no_progress->circuit (locks persistence path)
  minors-for-final-review: note_static_reject in-memory ++ is dead (replay-overwritten, return discarded) - simplify in M3; no_progress_release action TODO(M3 raise human-review freq)
Task M1b.7: complete (commits f42a3eb..994dcc9, review APPROVED after skip-guard fix; M1b acceptance suite 5 groups substantive, env-robust)
========== MILESTONE M1b COMPLETE (7 tasks M1b.1-7) ==========
  Deliverable: full AST danger gate (subscript/alias/importlib/builtins, no false-positives), mutation-validity fake-grader gate, PACE A-tier e-process acceptor (anti-self-deception core; standalone type-I<=alpha verified; ONS fallback for default env), de-correlation adversarial coverage, non-blocking human-review queue, 3 orthogonal counters+circuits+liveness (round-2 bug closed & integration-tested), M1b acceptance suite. Default suite green (~186 passed, 2 confseq skipped).
Task M2.1: complete (commits dd81218..b6716ad, review APPROVED after fix; anchors.extract_anchors(7 fields,stable id,dedup,required-field filter)+coverage(span-weighted,empty-span weight 0))
  minors-for-final-review: anchor_id 16-hex collision note (single-doc safe); extract no file/json exception wrap
Task M2.2: complete (commit 751a927, review APPROVED, Minors-only no fix; effective_independent_count cluster(host+cik+period) per-cluster floor(1+log2(size)), 8 same-source->4)
  minors-for-final-review: "主题" dim omitted (anchor dict has no topic field; conservative; add when upstream adds topic); verified=0 edge
Task M2.3: complete (commit f61ca49, review APPROVED, Minors-only no fix; split_visible_holdout SHA256(seed|anchor_id) deterministic, holdout=round(frac*N), disjoint+union)
  minors-for-final-review: determinism test doesn't compare visible; different-seed test probabilistic; missing anchor_id silent degrade
Task M2.4: complete (commit c91afa8, review APPROVED, no real defect; verify_anchor(fetcher-injected, lazy edgar import, rel/abs tol, 4-field copy) + edgar_cache.prepare_cache(WinError145 3-stage fault-tolerant + EDGAR_LOCAL_DATA_DIR); tests no-network verified)
  minors-for-final-review: unify _within_tol to spec max(|exp|,1) single-segment (currently equivalent); prepare_cache(None) no concurrent isolation; prepare_cache called per-fetch (perf)
Task M2.5: complete (commit 996a3bc, review APPROVED, Minors-only no fix; marginal_gain=max(0,with-base) with unverified-gate (forced 0), anti-self-deception verified)
  minors-for-final-review: clamp ternary vs max(0,..) (equivalent); no {} missing-verified test
Task M2.6: complete (commits e84e7b2..671f0fe, fix re-review APPROVED; B-tier decide branch: 3 hard gates (n_min/effective_independent/evalue_max_step) before e-value, B allows CONTINUE, A unchanged, no-regression A-only, evalue=min(evalue,step_cap))
  minors-for-final-review: default step_cap=1e6 comment says "no limit" but effectively ~2^20 cap (no impact at normal anchor counts); C-tier still uses _scale_subjective per-diff cap (M3)
Task M2.7: complete (commit a3ddc33, review APPROVED, Minors-only no fix; selfdeception.index 4 gates (low_anchor_gain/overfit_holdout+force_human/judge_anchor_divergence), value=judge-visible, reads drift_count read-only)
  minors-for-final-review: missing boundary tests (|value|==band no-alert; params=None band default)
Task M2.8: complete (commits fdcafcc..25cc6b7, review APPROVED after fix; proxy dispatch(harness-mediated, fullmatch whitelist CIK/ticker/date, candidate no url权, allowlist deepcopy) + screen_request(entropy+base64/hex on url/header/body) + shannon_entropy/looks_encoded; no-network)
  minors-for-final-review: _B64_RE numeric false-positive (low risk); url path-segment entropy not checked in screen_request
Task M2.9: complete (commit 687afb4, review APPROVED, no real defect; record_outbound + sequence_anomaly (sign① monotone/dictionary-order, ③ freq spike; ② degraded - no answer-data access), dispatch wired on success, M2.8 no regression)
  minors-for-final-review: cross-kind monotone mixing (per-kind more precise, low impact); hardcoded thresholds (freq 100/monotone 6); sign② docstring injection framing; timing channel residual (spec §6 accepted)
========== HALFWAY: 30/52 tasks complete ==========
Task M2.10: complete (commit b5d1062, review APPROVED, no correctness defect; fact_probe code-judges anchors via extract_anchors (anti-prose structural), anchor_set_min=24 gate -> tier_signal B/None, recursive scan)
  minors-for-final-review: evidence["scanned"] only records files-with-anchors (audit gap: add total_files_scanned); coverage test asserts fixed 0.0 (fragile); base_ref unused (add to evidence)
Task M2.11: complete (commits 80d6bf5..bc1f34e, review APPROVED after test-hardening; profile A/B/C additive tiers + visible/holdout split, 铁律5 holdout truth physically isolated to _holdout/holdout.json (target.json only ref+count), tier freeze preserved; 铁律5 test now falsifiable)
  minors-for-final-review: _exec_signal swallows exceptions (observability); holdout writes to target dir when run_dir=None (low risk)
Task M2.12: complete (commits a25166c..6650a4f, review APPROVED after fix; evaluate B-tier branch (backward-compat via ctx dict dispatch): b_paired(zero-mean per-anchor pairs)/visible_anchor_gain/holdout_gain(K-round spot-check)/coverage/coverage_floor_violation(accept-intent gated + raw fallback); selfdeception left to statemachine; A-tier unchanged; no-network)
  minors-for-final-review: holdout_base/with source not verifiable at evaluate layer (M2.13 must inject isolated holdout means)
Task M2.13: complete (commits f511731..286603e, 2 fixes + 2 re-reviews, APPROVED; statemachine B-tier wired end-to-end through run_loop: 态6 builds B evaluate ctx (anchors_visible/holdout K-round/fetcher injection) -> B grader routed -> resolve_accept (coverage gate + selfdeception force_human -> 态9.5) -> decision; drift_count via real DRIFT_SIGNAL event -> replay -> drift_circuit; enqueue run_dir; holdout None skips gate③; A-tier unchanged; e2e test через run_loop)
  minors-for-final-review/M3-carryover: coverage_floor not passed to ev_ctx (defaults 0.5, ignores params); holdout.json no try/except; e2e b_paired non-empty half-stub; base/with scores empty placeholder (M3 wires real grader/judge -> real judge_gain/scores)
========== MILESTONE M2 COMPLETE (13 tasks M2.1-13) ==========
  Deliverable: B-tier verification-anchor stack (extract/coverage/effective_independent/split/verify_anchor[edgar,no-net tests]/marginal_gain), B-tier acceptor (n_min+independence+evalue_max_step gates before e-value, CONTINUE allowed), selfdeception.index (low_anchor_gain/overfit_holdout+force_human/judge_anchor_divergence), outbound proxy (dispatch harness-mediated whitelist + screen_request entropy/base64-hex + sequence_anomaly), fact_probe (anti-prose), profile A/B/C additive + 铁律5 holdout physical isolation, evaluate B orchestration (coverage floor + holdout K-round spot-check), statemachine B end-to-end + drift persistence. Full suite ~314 passed, 2 confseq skipped. NOTE: real judge scoring is placeholder until M3 (heterogeneous Claude+Codex judge).
Task M3.1: complete (commits 80c03cb..a71e945, review APPROVED after fix; judges.score(family claude/codex) + judge_codex.invoke_codex_judge(strongest gpt-5.5+xhigh, graceful-unavailable on ratelimit/non-zero/timeout) + build_judge_prompt(no-truth 铁律5, type-boundary enforced) + workflows/codex-judge.js(browser/playwright disable enforcement point, double-lock); claude stub via score() returns contract sentinel; tests no real codex/claude)
  minors-for-final-review: codex-judge.js depends on codex CLI in PATH (absent -> available=False, covered); judge_claude full impl in M3.2
Task M3.2: complete (commits 90feff2..ccdb8c8, review APPROVED after fix; judge_claude.invoke_claude_judge (mirrors codex graceful-unavailable) + pairwise_agreement->Optional[float] (None on unavailable, span-aligned α∈[0,1]) + debias_order (position sort; length debias prompt-delegated); tests no real claude)
  minors-for-final-review: debias_order length-debias is prompt-delegated not explicit normalization
Task M3.3: complete (commit 1a6539b, review APPROVED, Important fail-safe-deferred + Minors; calibrate_judge_anchor Pearson on holdout-only (not visible/e-process), effective_independent_count de-correlation, degenerate on indep<4 or zero-variance)
  minors-for-final-review: effective_independent_count counts verified=True only (False-heavy holdout over-degenerates, fail-safe); noqa E402 mid-module import; _CALIB_MIN_INDEP=4 low df (prod >=8)
Task M3.4: complete (commits 31cbaa9..c2907bb, review APPROVED after fix; selfdeception full multi-gate extends M2.7: index adds block_accept/force_review (force_human preserved compat), retained_visible_gain (new anchors excluded gate①), cumulative_drift (gate④); dual-alert old+new names for M2.7/M3.4 compat; gate②③ independence tested)
  minors-for-final-review: dual-alert -> downstream must NOT use len(alerts) for drift count (commented); collusion string uses abs
Task M3.5: complete (commits 3a6cf6b..ed9e07c, review APPROVED after fix; acceptor C-tier branch (c_weight=0.05 never-alone) + force_review/degrade_reason on ALL paths + c_tier_no_regression hard gate + alpha_gate(two-sided 0.4/0.85, None=force_review, collusion count) + judge_degrade(Codex-unavailable -> single_claude_block); pure-C(coverage=0) all-paths force_review; A/B zero regression)
  ** M3.6 CARRYOVER (Important): judge_degrade NOT wired into decide() (standalone per brief) -> M3.6 statemachine MUST compose judge_degrade + alpha_gate + selfdeception block_accept/force_review into C-tier accept path, else Codex-unavailable single-Claude auto-ACCEPT not blocked end-to-end **
  minors-for-final-review: (covered by fix) base_tier gate, test is-False, docstring
Task M3.6: complete (commits a00cbd1..eb0e656, review APPROVED-functions; release_valve(returns raised review-freq ONLY, never auto-accept/lower-threshold) + drift_circuit(consecutive ACCEPT holdout-flat -> drift++ >=N, event-persist) + route_accept_with_gates(combines decision/sd.block_accept/force_review/alpha_gate/judge_degrade/pure-C-auto->PAUSE/Codex-unavail->PAUSE); params drift_circuit_N added; A/B/M2 no regression)
  ** M3.11 CRITICAL CARRYOVER: run_loop 态7/9/9.5 C-tier wiring MISSING (route_accept_with_gates/release_valve/drift_circuit are orphan, C-tier goes legacy hard-REJECT in run_loop). Wiring depends on evaluate-C (M3.7, judges.score data). M3.11 e2e MUST wire C into run_loop + add run_loop-level C integration test (pure-C auto->PAUSE, Codex-unavail single-Claude->PAUSE end-to-end). **
Task M3.7: complete (commit d6bc646, review APPROVED, Minors-only no fix; evaluate_c_tier(c_tier_no_regression + consistency passthrough + coverage=0, doesn't read artifact) + inject_judge_scores(both families independent, alpha=pairwise None-propagated, codex-first fallback calibration/judge_gain, contract-external = candidate can't self-report); additive-only no A/B regression; tests no real codex/claude; full suite 434 passed)
  minors-for-final-review: judge_gain codex["aggregate"] KeyError-defensive; late noqa E402 imports
Task M3.8: complete (commit 53e1b50, review APPROVED, Minors-only no fix; pareto_front multi-dim hard-dimension gate (软涨硬平 high-judge low-A/anchor reaches front but blocked by median gate -> not selectable), retire_stale Library Drift (append retired.jsonl, never touches lineage.json, cap + outcome-driven), selectable_parents; M1a 7 tests traced no regression)
  minors-for-final-review: median even-length docstring; test add 'v1 not in sel' + unconditional retired.exists assertion
Task M3.9: complete (commit 3f718fa, review APPROVED, Minors-only no fix; run_reflections_parallel N=3 process-level independent MARS (no shared draft) + meta_aggregate dedup/cluster + workflows/reflect-fanout.js+review-fanout.js; trace read-only 铁律2 (3-layer defense); M1 serial reflect intact; tests no real subagent/LLM)
  minors-for-final-review: independence test add assert len(set(received_histories))==3; list(history) shallow copy (read-only safe, deepcopy for strict)
Task M3.10: complete (commit c92dbbe, review APPROVED, Minors-only no fix; check_benchtrace anti-fabrication (each finding must cite >=1 real trace id in available_traces, set-based validation, grounded_ratio, threshold>=0.5 gate); M1 check untouched)
  minors-for-final-review: mixed-ref findings don't surface fake ids in audit (spec doesn't require); no trailing newline
Task M3.11: complete (commits acca573..fd04d39, fix + re-review APPROVED; C-tier wired end-to-end into run_loop (态6 inject_judge_scores+evaluate_c_tier, 态7 decide(C)+selfdeception+alpha_gate+judge_degrade->route_accept_with_gates, 态9 release_valve+drift_circuit, 态9.5 pure-C/Codex-block->PAUSE) -- route/release/drift NO LONGER orphan; M3 acceptance ①-④ (③④ e2e through full run_loop); no-regression gate non-vacuous (fail-safe REJECT on prior-passed history, round1 not affected, regression_unverified flag); A/B/M1/M2 no regression; doc updated)
  minors-for-final-review: fail-safe e2e coverage gap (inject history passed=True -> REJECT, statically derivable+unit-tested); historical-replay-under-candidate infra is future item (C multi-round ACCEPT needs it)
========== MILESTONE M3 COMPLETE (11 tasks M3.1-11) ==========
  Deliverable: heterogeneous judge pool (Claude+Codex adapters, codex-judge.js browser/playwright-disable enforcement, graceful-unavailable, prompt no-truth 铁律5), pairwise_agreement(Optional[float]), judge-anchor calibration (holdout-only Pearson), selfdeception full multi-gate (new-anchor-excluded/block_accept/overfit/cumulative-drift), acceptor C-tier (c_weight low never-alone, c_tier_no_regression, alpha_gate two-sided, judge_degrade Codex-unavailable), statemachine C gates (release_valve human-freq-only, drift_circuit event-persist, route_accept_with_gates) wired into run_loop e2e, evaluate C + contract-external judge injection, archive Pareto hard-dim gate (软涨硬平 blocked) + Library Drift retire_stale, N=3 parallel MARS reflect, BenchTrace anti-fabrication check. Full suite 465 passed, 2 confseq skipped.
Task M4.1: complete (commits 7e8e4ae..24763c5, review APPROVED after Critical fix; immutable.py IMMUTABLE_RELPATHS now 14 decision-code files (added patch.py/proxy.py/events.py - were critical omissions), is_immutable_relpath normalize-defends bypass (./,..,backslash,absolute), materialize_frozen(git show base ref + sha256 + chmod 0o444))
  minors-for-final-review: basename normalization (top-level files only); supervisor.py forward-ref silent skip until M4.4; archive.py/state.py correctly excluded (policy/schema not gate)
Task M4.2: complete (commits 258a6b6..6d467e6, review APPROVED after fix; verify_immutable fail-closed (mismatch/missing/empty-frozen all raise ImmutableViolation, no swallow) via unified hash_file(normalize_crlf=True) - no impl fork; ImmutableViolation exception)
  minors-for-final-review: CRLF-only tamper blind spot (Python semantics harmless); base_ref-missing IMMUTABLE files skipped in materialize (supervisor.py forward-ref until M4.4)
Task M4.3: complete (commit 9a4dd7f, review APPROVED, Minors-only no fix; immutable_gate(target_relpaths,enforce)->REJECT immutable_hit on hit+enforce/None else, wired into apply_patch as Gate 0 BEFORE AST gate + I/O (file not written on reject), enforce_immutable default False backward-compat; uses is_immutable_relpath; M1a/M1b 73 tests no regression)
  minors-for-final-review: apply_patch reason="immutable_hit: <path>" descriptive (M4.6 caller use `in` match like other reasons); immutable_gate gate-level returns pure reason+paths structured
Task M4.4: complete (commits fa1dc27..99c03c3, review APPROVED after Critical fix; supervisor.py two-process arbitration: load_frozen_decider(spec_from_file_location frozen abs path, no sys.path, load-and-pop sys.modules, missing->ImmutableViolation), Supervisor.decide uses frozen acceptor not candidate, candidate_path_is_isolated(empty-string->cwd expanded, normcase, frozen-exempt); candidate never in sys.path; frozen-vs-candidate test real)
  minors-for-final-review: (covered by fix) cwd hole, sys.modules cleanup, Windows normcase
Task M4.5: complete (commits 6300c32..1d4b247, fix; Supervisor.grade(self_mode=True) uses REAL frozen grade_pytest(candidate_worktree) [was production-broken fictional run_grader], candidate grade()/grader-hook never trusted/called in self-mode (worktree not imported), candidate_grade_is_trusted(self_mode) False/True; self_mode=False fail-closed raise (supervisor is self-mode only); test frozen verifiable real-shaped grade_pytest)
  minors-for-final-review: frozen verifiable copy must contain grade_pytest (it's the real module copy, satisfied)
Task M4.6: complete (commits 15ff5b9..30e7921, fix + re-review APPROVED; --self wires all M4 isolation end-to-end: selfboot_init (independent worktree + frozen materialize + verify_immutable fail-closed + candidate_path_is_isolated assert + Supervisor), CLI --self/--enforce-immutable calls selfboot_init + threads supervisor/candidate_worktree into run_loop; run_loop supervisor!=None -> 态6 supervisor.grade(self_mode=True frozen) + 态7 supervisor.decide(frozen) [candidate-modified acceptor/evaluate ignored], PATCH enforce_immutable=True (IMMUTABLE reject); non-self supervisor=None zero impact; state_patch dead path removed)
  ** M4.7 items: (1) B/C-tier self-mode guard (if supervisor!=None and tier has B/C -> raise or route through supervisor; self-evolve repo is A-tier in practice but defense-in-depth); (2) dead _patch_module import cleanup **
Task M4.7: complete (commit 5f9cce8, review APPROVED, Minors-only no fix; test_m4_selfboot_negative 4 negative cases genuinely e2e via real selfboot_init: (a) patch->IMMUTABLE rejected not-written, (b) candidate lying grade() ignored by frozen Supervisor.grade (graded_by=FROZEN), (c) tampered IMMUTABLE->verify_immutable raises ImmutableViolation startup fail-closed, (d) candidate_path_is_isolated; B/C self-mode guard (supervisor!=None+B/C tier->ValueError, A passes, non-self zero impact); dead _patch_module import removed)
  minors-for-final-review: test digest rebuild use normalize_crlf=True for symmetry; test comment ImmutableViolation semantics
========== MILESTONE M4 COMPLETE (7 tasks M4.1-7) ==========
  Deliverable: self-bootstrap isolation - IMMUTABLE manifest (14 decision-code files incl patch/proxy/events) + frozen materialize (git show base ref, sha256, chmod 0o444), verify_immutable fail-closed startup gate, patch immutable_gate (reject IMMUTABLE writes), supervisor two-process arbitration (load_frozen_decider isolated, candidate never in sys.path, candidate can't self-judge), self-mode frozen grade_pytest (candidate can't self-grade), --self recursive isolation (independent worktree + selfboot_init + run_loop Supervisor wiring), self-boot negative acceptance suite. 4 iron rules enforced end-to-end.
========================================================
ALL 52 TASKS COMPLETE (M1a 14 + M1b 7 + M2 13 + M3 11 + M4 7).
