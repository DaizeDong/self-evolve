"""statemachine.py — 10-state M1a orchestration loop + parent selection.

Public API (contract-locked):
  select_parent(run_dir, st) -> str
  run_loop(target, base_ref, run_id, max_rounds=3, mode="auto",
           _injected_fix=None) -> dict

M1b.6 additions (contract-locked):
  apply_acceptor_outcome(st, decision, params) -> str
  note_static_reject(st) -> str
  note_forced_review(st) -> None
  circuit_check(st, params) -> str | None

Crash-replay invariant (M1a hard spec):
  Every state transition calls append_event BEFORE save_state.
  events.jsonl is the source of truth; deleting state.json and calling
  replay(run_dir) must produce an identical RunState.

_injected_fix: M1a scaffold for deterministic testing of the ACCEPT path.
  Format: {"file_rel": str, "fix_content": str, "target_failure": str}
  Merged into the reflect output so builtin.generate produces a valid proposal.
  This parameter is removed in M3 when real LLM fanout is wired.
"""
from __future__ import annotations

import os

from tools.sie.state import RunState, save_state
from tools.sie.events import append_event, replay
from tools.sie.sandbox import make_worktree
from tools.sie.profile import run_profile, freeze_target, load_target
from tools.sie.reflect import reflect
from tools.sie.check_reflection import check
from tools.sie.propose import propose
from tools.sie.patch import apply_patch
from tools.sie.evaluate import evaluate
from tools.sie.acceptor import decide
from tools.sie import archive


# ---------------------------------------------------------------------------
# M1b.6 契约函数 — 三计数器 + 熔断 + CONTINUE 落点 + A 档守卫
# ---------------------------------------------------------------------------

def apply_acceptor_outcome(st: RunState, decision: dict, params: dict) -> str:
    """依 acceptor decision 更新计数器并返回下一态 token.

    Returns: "EVALUATE" | "ARCHIVE" | "LOOP" | "PAUSE_FOR_HUMAN"

    三计数器正交语义:
    - no_progress: REJECT/CONTINUE 每轮各自增 1 (acceptor 无进展轮次)
    - continue_count: CONTINUE 专属计数 (A 档禁 CONTINUE 不增)
    - forced_review: 由 note_forced_review 在 PAUSE_FOR_HUMAN 进入时增计

    CONTINUE 上限落点: continue_count >= cap → 强制 REJECT 语义 (LOOP)
    A 档禁 CONTINUE: base_tier=="A" 且 decision=="CONTINUE" → 守卫降级为 REJECT
    FORCE_HUMAN: 直接路由到 PAUSE_FOR_HUMAN (不增 no_progress)
    ACCEPT: 清零 no_progress / forced_review / continue_count 返回 ARCHIVE
    """
    d = decision["decision"]
    cap = params.get("continue_count_cap", 5)
    base_tier = st.tier.split("+")[0]

    if d == "ACCEPT":
        st.no_progress = 0
        st.forced_review = 0
        st.continue_count = 0
        return "ARCHIVE"

    if d == "FORCE_HUMAN":
        return "PAUSE_FOR_HUMAN"

    if d == "CONTINUE":
        # A 档禁 CONTINUE 守卫: 异常决策降级为 REJECT, 不增 continue_count
        if base_tier == "A":
            st.no_progress += 1
            return "LOOP"
        # CONTINUE 上限落点: 达 cap 则落点为 REJECT
        if st.continue_count >= cap:
            st.no_progress += 1
            return "LOOP"
        st.continue_count += 1
        st.no_progress += 1
        return "EVALUATE"

    # REJECT (default)
    st.no_progress += 1
    return "LOOP"


def note_static_reject(st: RunState) -> str:
    """态4 空 / 态5 全拒时调用: static_reject++ 返回 "LOOP".

    static_reject 计数器正交独立于 no_progress (不增 no_progress).
    """
    st.static_reject += 1
    return "LOOP"


def note_forced_review(st: RunState) -> None:
    """态9.5 PAUSE_FOR_HUMAN 进入时调用: forced_review++."""
    st.forced_review += 1


def circuit_check(st: RunState, params: dict) -> str | None:
    """检查熔断/释放阀条件, 返回原因 token 或 None.

    优先级 (从高到低):
    1. no_progress >= N (no_progress_circuit_N) → 熔断 "no_progress_circuit"
    2. static_reject >= N_sr (static_reject_circuit) → "static_reject_circuit"
    3. forced_review >= N_fr (forced_review_circuit) → "forced_review_circuit"
    4. drift_count >= N_drift (drift_circuit) → "drift_circuit"
    5. no_progress >= M (no_progress_release_M, M<N) → "no_progress_release" (升人审频率, 非熔断)

    注: 熔断阈 (N) 必须在释放阀 (M) 之前判定, 确保 no_progress 同时 >=M 且 >=N 时优先报熔断.
    """
    if st.no_progress >= params.get("no_progress_circuit_N", 8):
        return "no_progress_circuit"
    if st.static_reject >= params.get("static_reject_circuit", 6):
        return "static_reject_circuit"
    if st.forced_review >= params.get("forced_review_circuit", 5):
        return "forced_review_circuit"
    if st.drift_count >= params.get("drift_circuit", 4):
        return "drift_circuit"
    if st.no_progress >= params.get("no_progress_release_M", 3):
        return "no_progress_release"
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_dir(target: str, run_id: str) -> str:
    """Return the absolute run directory: <target>/.sie/runs/<run_id>."""
    return os.path.join(os.path.abspath(target), ".sie", "runs", run_id)


def _step(run_dir: str, ev: dict) -> RunState:
    """Append ev to events.jsonl, then replay to get new RunState, then save_state.

    The order (append → replay → save) is the crash-replay hard invariant:
    events.jsonl is always written first, state.json is the derived side-channel.
    Deleting state.json and calling replay(run_dir) must produce the same result.
    """
    append_event(run_dir, ev)        # 真相源先行 (hard invariant)
    st = replay(run_dir)             # derive state purely from events
    save_state(st, run_dir)          # side-channel snapshot (crash-safe)
    return st


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_parent(run_dir: str, st: RunState) -> str:
    """SELECT_PARENT: cold-start (empty archive) -> 'base'; else lineage tail vid.

    Spec 态2: archive empty -> parent = base ref sentinel "base".
    """
    arch = os.path.join(run_dir, "archive")
    lin = archive.lineage(arch)
    if not lin:
        return "base"               # 冷启动 -> base ref (spec 态2)
    return lin[-1]["vid"]           # lineage 末版 (最新已采纳)


def run_loop(
    target: str,
    base_ref: str,
    run_id: str,
    max_rounds: int = 3,
    mode: str = "auto",
    _injected_fix: dict | None = None,
) -> dict:
    """Drive the M1a 10-state closed loop and return a summary dict.

    _injected_fix is an M1a scaffold parameter (not present in M3):
    it allows deterministic testing of the ACCEPT path without a real LLM.
    When provided it is merged into the reflect output so builtin.generate
    can produce a valid proposal (see builtin.py).

    States:
      INIT -> PROFILE -> [REFLECT -> CHECK -> PROPOSE -> PATCH -> EVALUATE ->
                          ACCEPT|REJECT] * max_rounds -> done

    Returns:
      {"run_id": str, "accepted_versions": list[str],
       "final_phase": str, "run_dir": str}
    """
    run_dir = _run_dir(target, run_id)
    os.makedirs(run_dir, exist_ok=True)

    params: dict = {
        "alpha": 0.05,
        "continue_count_cap": 5,
        "no_progress_circuit_N": 8,
        "no_progress_release_M": 3,
        "static_reject_circuit": 6,
        "forced_review_circuit": 5,
        "drift_circuit": 4,
    }
    accepted: list[str] = []

    # ------------------------------------------------------------------
    # 态0 INIT — worktree + initial event
    # ------------------------------------------------------------------
    sandbox_root = make_worktree(target, base_ref, run_id)
    st = _step(run_dir, {
        "type": "INIT",
        "run_id": run_id,
        "phase": "INIT",
        "parent_vid": None,
        "tier": "",
        "round": 0,
    })

    # ------------------------------------------------------------------
    # 态1 PROFILE — freeze tier; idempotent on resume
    # ------------------------------------------------------------------
    target_json = os.path.join(run_dir, "target.json")
    if os.path.exists(target_json):
        prof = load_target(run_dir)             # resume: do not re-profile
    else:
        prof = run_profile(target, base_ref)
        freeze_target(run_dir, prof)

    st = _step(run_dir, {
        "type": "PROFILE",
        "phase": "PROFILE",
        "tier": prof["tier"],
    })

    # ------------------------------------------------------------------
    # Main loop: max_rounds iterations over states 2-9
    # ------------------------------------------------------------------
    history: list[dict] = []

    for rnd in range(1, max_rounds + 1):

        # 态2 SELECT_PARENT
        parent = select_parent(run_dir, st)
        st = _step(run_dir, {
            "type": "ROUND_BEGIN",
            "phase": "REFLECT",
            "round": rnd,
            "parent_vid": parent,
        })

        # 态3 REFLECT — M1a: serial single reflection
        refs = reflect(sandbox_root, history, n=1)
        # M1a scaffold: merge _injected_fix into first reflection for ACCEPT path testing.
        # (This parameter is removed in M3 when real LLM fanout is wired.)
        if _injected_fix:
            # Defensive: if refs is empty, use empty dict to avoid IndexError on refs[0]
            refs = [dict(refs[0] if refs else {}, **_injected_fix)]

        # 态3b CHECK_REFLECTION — weak validation gate
        refs = [r for r in refs if check(r, 0.5)]
        if not refs:
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "REFLECT",
                "static_reject_delta": 1,
            })
            # circuit_check after static_reject
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            continue

        # 态4 PROPOSE — builtin deterministic generator (M3: real LLM fanout)
        props = propose(sandbox_root, refs, backend="builtin")
        if not props:
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PROPOSE",
                "static_reject_delta": 1,
            })
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            continue

        # 态5 PATCH — apply each proposal; AST + boundary gates enforced by apply_patch
        applied = False
        for p in props:
            res = apply_patch(sandbox_root, p["file_rel"], p["new_content"])
            if res["status"] == "APPLIED":
                applied = True

        if not applied:
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PATCH",
                "static_reject_delta": 1,
            })
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            continue

        # 态6 EVALUATE — verifiable grader (A-tier: pytest)
        ev_result = evaluate(sandbox_root, prof["tier"], base_result=None)

        # 态7 DECIDE — acceptor outcome routing (ACCEPT/REJECT/CONTINUE/FORCE_HUMAN)
        dec = decide(ev_result["paired"], prof["tier"], st, params)
        nxt = apply_acceptor_outcome(st, dec, params)

        if nxt == "ARCHIVE":
            # 态8 ACCEPT: add lineage entry + snapshot; apply_acceptor_outcome cleared counters in st
            vid = f"v{len(accepted) + 1}"
            # NOTE: add_version receives run_dir (internally joins "archive"),
            #       snapshot_version receives arch_dir (pre-joined).
            archive.add_version(run_dir, vid, ev_result["result"]["dimensions"], parent)
            arch_dir = os.path.join(run_dir, "archive")
            archive.snapshot_version(arch_dir, vid, sandbox_root)
            accepted.append(vid)

            st = _step(run_dir, {
                "type": "ACCEPT",
                "phase": "ARCHIVE",
                "parent_vid": vid,
                # ACCEPT semantics in _apply: clears no_progress / forced_review / continue_count
            })
            history.append({"round": rnd, "summary": "accepted", "passed": True})

        elif nxt == "EVALUATE":
            # CONTINUE: accumulate evidence, re-enter evaluation next round
            st = _step(run_dir, {
                "type": "CONTINUE",
                "phase": "REFLECT",
                "no_progress_delta": 1,
                "continue_count_delta": 1,
            })
            history.append({
                "round": rnd,
                "summary": dec["reason"],
                "passed": False,
            })
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break

        elif nxt == "PAUSE_FOR_HUMAN":
            # 态9.5 PAUSE_FOR_HUMAN — non-blocking; record & increment forced_review
            from tools.sie import gate_human
            note_forced_review(st)   # in-memory counter update
            gate_human.enqueue(run_dir, {
                "run_id": run_id,
                "round": rnd,
                "action_type": "human_review",
                "payload": {"reason": dec.get("reason", ""), "evalue": dec.get("evalue", 0.0)},
            })
            st = _step(run_dir, {
                "type": "PAUSE_FOR_HUMAN",
                "phase": "PAUSE_FOR_HUMAN",
                "forced_review_delta": 1,
            })
            history.append({
                "round": rnd,
                "summary": dec["reason"],
                "passed": False,
            })
            # Check forced_review circuit after entering 9.5
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break

        else:
            # 态9 REJECT: no_progress already incremented by apply_acceptor_outcome
            st = _step(run_dir, {
                "type": "REJECT",
                "phase": "REFLECT",
                "no_progress_delta": 1,
            })
            history.append({
                "round": rnd,
                "summary": dec["reason"],
                "passed": False,
            })
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break

    return {
        "run_id": run_id,
        "accepted_versions": accepted,
        "final_phase": st.phase,
        "run_dir": run_dir,
    }
