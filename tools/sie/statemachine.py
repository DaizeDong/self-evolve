"""statemachine.py — 10-state M1a orchestration loop + parent selection.

Public API (contract-locked):
  select_parent(run_dir, st) -> str
  run_loop(target, base_ref, run_id, max_rounds=3, mode="auto",
           _injected_fix=None) -> dict

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

    params: dict = {"alpha": 0.05}
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
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "REFLECT",
                "static_reject_delta": 1,
            })
            continue

        # 态4 PROPOSE — builtin deterministic generator (M3: real LLM fanout)
        props = propose(sandbox_root, refs, backend="builtin")
        if not props:
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PROPOSE",
                "static_reject_delta": 1,
            })
            continue

        # 态5 PATCH — apply each proposal; AST + boundary gates enforced by apply_patch
        applied = False
        for p in props:
            res = apply_patch(sandbox_root, p["file_rel"], p["new_content"])
            if res["status"] == "APPLIED":
                applied = True

        if not applied:
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PATCH",
                "static_reject_delta": 1,
            })
            continue

        # 态6 EVALUATE — verifiable grader (A-tier: pytest)
        ev_result = evaluate(sandbox_root, prof["tier"], base_result=None)

        # 态7/8 ACCEPT or REJECT — no-regression hard gate
        dec = decide(ev_result["paired"], prof["tier"], st, params)

        if dec["decision"] == "ACCEPT":
            # 态8 ACCEPT: add lineage entry + snapshot + clear no_progress
            vid = f"v{len(accepted) + 1}"
            # NOTE: add_version receives run_dir (internally joins "archive"), snapshot_version receives arch_dir (pre-joined).
            archive.add_version(run_dir, vid, ev_result["result"]["dimensions"], parent)
            arch_dir = os.path.join(run_dir, "archive")
            # NOTE: snapshot_version receives archive_dir (already joined), not run_dir.
            archive.snapshot_version(arch_dir, vid, sandbox_root)
            accepted.append(vid)

            st = _step(run_dir, {
                "type": "ACCEPT",
                "phase": "ARCHIVE",
                "parent_vid": vid,
                # ACCEPT semantics in _apply: clears no_progress + forced_review
            })
            history.append({"round": rnd, "summary": "accepted", "passed": True})

        else:
            # 态9 REJECT: increment no_progress counter
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

    return {
        "run_id": run_id,
        "accepted_versions": accepted,
        "final_phase": st.phase,
        "run_dir": run_dir,
    }
