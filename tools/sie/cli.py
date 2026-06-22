"""cli.py — sie command-line interface.

Subcommands:
  init      Create run directory and print run metadata.
  run       Execute run_loop and print summary JSON.
  status    Print current state + archive pareto + pending actions.
  replay    Replay events.jsonl and print reconstructed RunState.
  rollback  Rollback archive to a given version id (vid).

Reserved for later milestones (not implemented here):
  review / land / diff
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

from tools.sie.statemachine import run_loop, _run_dir
from tools.sie.events import replay
from tools.sie.state import load_state
from tools.sie import archive, gate_human


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code (0 = success, non-zero = error)."""
    argv = list(sys.argv[1:] if argv is None else argv)

    ap = argparse.ArgumentParser(prog="sie", description="Self-Improving Engine CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialise a run directory")
    p_init.add_argument("--target", required=True, help="Target repo path")
    p_init.add_argument("--run-id", default=None, help="Run ID (auto-generated if omitted)")

    # run
    p_run = sub.add_parser("run", help="Execute run_loop")
    p_run.add_argument("--target", required=True)
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--base-ref", default="HEAD")
    p_run.add_argument("--max-rounds", type=int, default=3)
    p_run.add_argument("--mode", default="auto", choices=["auto", "gated"])
    p_run.add_argument("--self", dest="self_mode", action="store_true",
                       help="自举：把 self-evolve 自身当 target，开 IMMUTABLE 锁+supervisor 隔离(默认关)")
    p_run.add_argument("--enforce-immutable", dest="enforce_immutable",
                       action="store_true",
                       help="显式开 IMMUTABLE 哈希锁(非自举也可强制)")
    p_run.add_argument("--proposer", default="builtin", choices=["builtin", "llm"],
                       help="propose 后端: builtin(确定性,默认) | llm(真 Claude, cc 优先)")
    p_run.add_argument("--reflect-mode", dest="reflect_mode", default="serial",
                       choices=["serial", "parallel"],
                       help="反思: serial(M1a,默认) | parallel(N=3 MARS 真 Claude)")
    p_run.add_argument("--live", action="store_true",
                       help="便捷开关: 等价 --proposer llm --reflect-mode parallel(真 agent 闭环)")

    # status
    p_st = sub.add_parser("status", help="Print run status")
    p_st.add_argument("--target", required=True)
    p_st.add_argument("--run-id", required=True)

    # replay
    p_rp = sub.add_parser("replay", help="Replay events.jsonl and print RunState")
    p_rp.add_argument("--target", required=True)
    p_rp.add_argument("--run-id", required=True)

    # rollback
    p_rb = sub.add_parser("rollback", help="Rollback archive to a version")
    p_rb.add_argument("--target", required=True)
    p_rb.add_argument("--run-id", required=True)
    p_rb.add_argument("--vid", required=True, help="Version ID to restore")

    args = ap.parse_args(argv)

    # ------------------------------------------------------------------
    if args.cmd == "init":
        rid = args.run_id or uuid.uuid4().hex[:12]
        rd = _run_dir(args.target, rid)
        os.makedirs(rd, exist_ok=True)
        print(json.dumps({"run_id": rid, "run_dir": rd}, ensure_ascii=False))
        return 0

    # ------------------------------------------------------------------
    if args.cmd == "run":
        enforce = args.self_mode or args.enforce_immutable
        # M4.6: 自举模式调 selfboot_init 建独立 worktree + frozen + Supervisor
        _supervisor = None
        _candidate_worktree = None
        if args.self_mode:
            from tools.sie import selfboot as _selfboot
            import os as _os
            _runs_root = _os.path.join(_os.path.abspath(args.target), ".sie", "runs")
            _boot = _selfboot.selfboot_init(
                args.target,
                args.base_ref,
                args.run_id,
                _runs_root,
            )
            _supervisor = _boot["supervisor"]
            _candidate_worktree = _boot["candidate_worktree"]
        _proposer = "llm" if args.live else args.proposer
        _reflect_mode = "parallel" if args.live else args.reflect_mode
        summary = run_loop(
            args.target,
            args.base_ref,
            args.run_id,
            max_rounds=args.max_rounds,
            mode=args.mode,
            enforce_immutable=enforce,
            supervisor=_supervisor,
            candidate_worktree=_candidate_worktree,
            proposer=_proposer,
            reflect_mode=_reflect_mode,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    # ------------------------------------------------------------------
    if args.cmd == "status":
        rd = _run_dir(args.target, args.run_id)
        st = load_state(rd)
        arch = os.path.join(rd, "archive")
        out = {
            "phase": st.phase,
            "round": st.round,
            "tier": st.tier,
            "no_progress": st.no_progress,
            "static_reject": st.static_reject,
            "forced_review": st.forced_review,
            "pareto": archive.pareto_front(arch) if os.path.isdir(arch) else [],
            "pending": gate_human.pending(rd),
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0

    # ------------------------------------------------------------------
    if args.cmd == "replay":
        rd = _run_dir(args.target, args.run_id)
        st = replay(rd)
        print(json.dumps(st.__dict__, ensure_ascii=False))
        return 0

    # ------------------------------------------------------------------
    if args.cmd == "rollback":
        rd = _run_dir(args.target, args.run_id)
        archive.rollback(os.path.join(rd, "archive"), args.vid)
        print(json.dumps({"rolled_back_to": args.vid}, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
