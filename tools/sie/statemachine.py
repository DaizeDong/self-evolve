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

import json
import os
import subprocess
import sys

from tools.sie.state import RunState, save_state
from tools.sie.events import append_event, replay
from tools.sie.sandbox import make_worktree
from tools.sie.profile import run_profile, freeze_target, load_target
from tools.sie.reflect import reflect
from tools.sie.check_reflection import check
from tools.sie.propose import propose
from tools.sie.patch import apply_patch
from tools.sie.evaluate import evaluate, candidate_grade_error
from tools.sie.acceptor import decide
from tools.sie import archive, business_tree, runtime_data


# ---------------------------------------------------------------------------
# M1b.6 契约函数, 三计数器 + 熔断 + CONTINUE 落点 + A 档守卫
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

    # static_reject is NOT reset here. It looks like it belongs here and it does not work here:
    # _step replays events.jsonl to rebuild the state right after this returns, so events._apply is
    # the authority and anything mutated on this object is thrown away. The reset lives there, next
    # to the ACCEPT semantics it belongs with.

    if d == "ACCEPT":
        st.no_progress = 0
        st.forced_review = 0
        st.continue_count = 0
        return "ARCHIVE"

    if d == "FORCE_HUMAN":
        return "PAUSE_FOR_HUMAN"

    # `force_review` on any decision routes to the human arm, not only the FORCE_HUMAN decision.
    # This function read the decision STRING and ignored the field, so an acceptor that set
    # force_review=True on a REJECT was silently handled as an ordinary refusal. Measured: after the
    # A-tier gate was taught to flag "the test signal cannot observe this change at all" as a blind
    # spot rather than a verdict, a full run still produced 8 REJECT and 0 PAUSE_FOR_HUMAN, because
    # the flag had nowhere to go. Producer fixed, consumer not: the same shape as the history record
    # that grew new fields the serial reflect path then dropped.
    if decision.get("force_review"):
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
# M3.6: 释放阀 + 累计漂移熔断 + 综合闸路由
# ---------------------------------------------------------------------------

def release_valve(st: "RunState", params: dict) -> int:
    """no_progress >= M 时只升高人审触发频率；绝不降 acceptor 阈、绝不自动采纳。

    Returns: 当前应使用的 review_frequency (int)。
    调用方应用此频率决定何时额外触发人审入队，但不得借此修改 acceptor 阈值或
    自动将当前提案标为 ACCEPT。
    """
    M = params.get("no_progress_release_M", 3)
    base = params.get("review_freq_base", 1)
    boost = params.get("review_freq_boost", 3)
    return boost if st.no_progress >= M else base


def drift_circuit(st: "RunState", holdout_up: bool, params: dict) -> bool:
    """连续 ACCEPT 但 holdout/全量回归不涨 → drift_count++；≥N_drift → True（停机人审）。

    drift_count 在此函数中以内存方式更新（st.drift_count += 1）；
    调用方须在 _step 中写入含 drift_count_delta=1 的事件，以完成 replay 持久化
    （沿用 M2.13 DRIFT_SIGNAL 事件模式，参见 run_loop 态7 B 档路径）。

    Args:
        st:         当前 RunState，in-place 修改 drift_count。
        holdout_up: True 表示本轮 holdout / 全量回归有提升；False 表示无提升。
        params:     支持键 drift_circuit_N（默认 4）。

    Returns:
        True 表示累计漂移达到熔断阈（需停机人审）；False 表示未触发。
    """
    N = params.get("drift_circuit_N", 4)
    if holdout_up:
        st.drift_count = 0
        return False
    st.drift_count += 1
    return st.drift_count >= N


def route_accept_with_gates(
    decision: dict,
    sd: dict,
    alpha_gate_out: dict,
    degrade: dict,
    mode: str,
    tier: str,
    coverage: float,
) -> str:
    """综合所有闸返回最终接受态。

    优先级（从高到低）：
      1. decision != ACCEPT         → "REJECT"
      2. sd.block_accept            → "REJECT"   (visible 留存增益 < ε，禁 ACCEPT)
      3. 任一 force_review 信号     → "PAUSE_FOR_HUMAN"
         （sd / alpha_gate_out / degrade / decision 中任一为 True）
      4. degrade.single_claude_block → "PAUSE_FOR_HUMAN"  (Codex 不可用禁单 Claude auto)
      5. 纯 C + auto + coverage=0  → "PAUSE_FOR_HUMAN"  (纯 C auto 强制 gated)
      6. 否则                       → "ARCHIVE"

    Args:
        decision:      acceptor.decide 返回的决策 dict，含 "decision"/"force_review"。
        sd:            selfdeception.index 返回值，含 "block_accept"/"force_review"。
        alpha_gate_out: acceptor.alpha_gate 返回值，含 "force_review"。
        degrade:       acceptor.judge_degrade 返回值，含 "single_claude_block"/"force_review"。
        mode:          "auto" | "gated" — auto 模式才触发纯 C 强制人审。
        tier:          档位字符串 "A"|"B"|"C"|叠加如"A+B"。
        coverage:      覆盖率浮点；0.0 表示纯 C 无程序化锚覆盖。

    Returns:
        "ARCHIVE" | "PAUSE_FOR_HUMAN" | "REJECT"
    """
    if decision.get("decision") != "ACCEPT":
        return "REJECT"
    # visible 留存增益 < ε → 硬 REJECT（禁 ACCEPT，统计基础不可靠）
    if sd.get("block_accept"):
        return "REJECT"
    # 任一 force_review 信号 → 人审
    if (sd.get("force_review")
            or alpha_gate_out.get("force_review")
            or degrade.get("force_review")
            or decision.get("force_review")):
        return "PAUSE_FOR_HUMAN"
    # Codex 不可用 → 禁单 Claude 自动 ACCEPT（端到端接入 judge_degrade）
    if degrade.get("single_claude_block"):
        return "PAUSE_FOR_HUMAN"
    # 纯 C 档 auto 欲 ACCEPT → 强制 gated（不自动采纳）
    if tier == "C" and coverage == 0.0 and mode == "auto":
        return "PAUSE_FOR_HUMAN"
    return "ARCHIVE"


# ---------------------------------------------------------------------------
# M2.13: B 档 ACCEPT 态接线 (resolve_accept)
# ---------------------------------------------------------------------------

def resolve_accept(st: RunState, eval_out: dict, params: dict,
                   run_dir: str | None = None) -> dict:
    """B 档 ACCEPT 态接线: acceptor + selfdeception 多闸 → 路由到下一态.

    Args:
        st:       当前 RunState (in-place 修改计数器, 调用方再 _step 持久化).
        eval_out: B 档 evaluate 输出 dict (含 tier/b_paired/coverage_floor_violation/
                  visible_anchor_gain/holdout_gain/anchors_visible_verified 等).
        params:   参数字典 (含 alpha/n_min/effective_independent_anchor_min 等).
        run_dir:  run 目录 (用于 gate_human.enqueue 写文件); None 时使用已验证的私有 review 目录.

    Returns:
        {
          "next_state":         "8" | "9" | "9.5" | "6",
          "acceptor_decision":  "ACCEPT" | "REJECT" | "CONTINUE" | "FORCED_REVIEW",
          "selfdeception":      dict (selfdeception.index 返回值),
          "reason":             str,
        }

    路由规则 (B 档):
        1. 调用 acceptor.decide 得到 dec (ACCEPT/REJECT/CONTINUE).
        2. 调用 selfdeception.index 得到 sd.
           - judge_anchor_divergence 信号 → st.drift_count += 1 (in-memory;
             调用方负责写 drift_count_delta 事件完成 replay 持久化).
        3. 欲 ACCEPT 但触发强制人审条件:
               coverage_floor_violation OR sd["force_human"] OR "low_anchor_gain" in alerts
           → 态9.5: st.forced_review += 1, enqueue, return next_state="9.5"
        4. ACCEPT (无强制条件) → next_state="8"
        5. CONTINUE               → st.no_progress += 1, next_state="6"
        6. REJECT                 → st.no_progress += 1, next_state="9"

    非 B 档路由到 _resolve_accept_legacy (M1 A/C 行为不变).
    """
    from . import selfdeception as _selfdeception
    from . import gate_human as _gate_human

    tier = eval_out.get("tier", st.tier)

    if "B" not in str(tier):
        # 非 B 档: 交还旧有逻辑 (A/C 路径, M1 已实现)
        return _resolve_accept_legacy(st, eval_out, params)

    # --- B 档路径 ---
    if eval_out.get("holdout_missing"):
        st.no_progress += 1
        return {"next_state": "9", "acceptor_decision": "REJECT", "selfdeception": {},
                "reason": "Scheduled holdout has no usable paired observation"}
    dec = decide(
        eval_out.get("b_paired", []),
        "B",
        st,
        {**params, "anchors": eval_out.get("anchors_visible_verified", [])},
    )

    # selfdeception 多闸
    visible_gain = eval_out.get("visible_anchor_gain", 0.0)
    holdout_gain = eval_out.get("holdout_gain")   # None 表示非抽检轮，直接传 None 跳过闸③
    # judge_gain: judge 主观判定增益. judge_anchor_divergence 闸检测"judge 声称高于锚
    # 真实核验"(合谋方向 = judge_gain > visible). B 档**无 judge** → 无此发散方向;
    # 缺 judge_gain 时令 judge_gain = visible_gain → value=0 → 不误触发散闸.
    # (此前默认 0.0, 当 visible_anchor_gain 变成真正正值[#1 修复后]会误报 judge_anchor_
    #  divergence → 累计 drift_circuit 误停正在改进的 B 档 run; 锚核验充分是好方向, 非合谋.)
    _jg = eval_out.get("judge_gain")
    judge_gain = float(_jg) if _jg is not None else float(visible_gain)
    sd = _selfdeception.index(
        judge_gain=float(judge_gain),
        visible_anchor_gain=float(visible_gain),
        holdout_gain=holdout_gain,   # None → selfdeception.index 跳过过拟合闸③
        st=st,
        params=params,
    )

    # drift_count 累计 (in-memory; 调用方写 drift_count_delta 事件持久化到 replay)
    if "judge_anchor_divergence" in sd.get("alerts", []):
        st.drift_count += 1

    # 强制人审条件检查:
    # coverage_floor_violation 或 selfdeception.force_human 是全局拦截条件,
    # 无论 acceptor 返回 ACCEPT 还是 CONTINUE (有可能在下一轮变 ACCEPT),
    # 只要这些信号存在就必须提前走人审, 防止在次优数据上持续迭代积累。
    # REJECT 路径不需要额外拦截 (REJECT 已阻断进展)。
    not_rejected = dec["decision"] in ("ACCEPT", "CONTINUE")
    cov_violation = bool(eval_out.get("coverage_floor_violation", False))
    force = cov_violation or sd["force_human"] or ("low_anchor_gain" in sd.get("alerts", []))

    if not_rejected and force:
        _enqueue_dir = run_dir or str(runtime_data.private_root()/'human-review'/
                                     runtime_data.validate_run_id(st.run_id))
        st.forced_review += 1
        _gate_human.enqueue(_enqueue_dir, {
            "run_id": st.run_id,
            "round": st.round,
            "action_type": "human_review",
            "payload": {
                "reason": "B forced human review",
                "coverage_floor_violation": cov_violation,
                "selfdeception": sd,
                "acceptor": dec,
            },
        })
        return {
            "next_state": "9.5",
            "acceptor_decision": "FORCED_REVIEW",
            "selfdeception": sd,
            "reason": "B forced human review",
        }

    if dec["decision"] == "ACCEPT":
        return {
            "next_state": "8",
            "acceptor_decision": "ACCEPT",
            "selfdeception": sd,
            "reason": dec.get("reason", "B ACCEPT"),
        }

    if dec["decision"] == "CONTINUE":
        st.no_progress += 1
        return {
            "next_state": "6",
            "acceptor_decision": "CONTINUE",
            "selfdeception": sd,
            "reason": dec.get("reason", "B CONTINUE"),
        }

    # REJECT (default)
    st.no_progress += 1
    return {
        "next_state": "9",
        "acceptor_decision": "REJECT",
        "selfdeception": sd,
        "reason": dec.get("reason", "B REJECT"),
    }


def _resolve_accept_legacy(st: RunState, eval_out: dict, params: dict) -> dict:
    """M1 A/C 档旧路由 (保留兼容性, 不改变已有行为).

    A 档在 run_loop 中直接调用 acceptor.decide + apply_acceptor_outcome;
    本函数仅作为 resolve_accept 非 B 档分支的安全兜底, 返回 REJECT。
    注: 当前 C 档亦走此分支得到 REJECT; C 档 run_loop 接线(route_accept_with_gates/release_valve/drift_circuit 态7/9/9.5)依赖 evaluate-C(M3.7), 待 M3.11 端到端接入。
    """
    return {
        "next_state": "9",
        "acceptor_decision": "REJECT",
        "selfdeception": {},
        "reason": "non-B tier: delegated to legacy path (A/C handled in run_loop)",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_dir(target: str, run_id: str) -> str:
    """All target run records belong in a verified PRIVATE companion."""
    from tools.sie.runtime_data import run_directory
    return str(run_directory(target, run_id))


def _load_datadir():
    """Load the resolver from the guards submodule. None when absent; every other failure
    propagates. The single caller turns None into a refusal to write, which is the point: a
    resolver that cannot be reached must never degrade into a repo-relative default."""
    p = os.path.join(_REPO_ROOT, "guards", "tools", "datadir.py")
    if not os.path.isfile(p):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dd_for_sie", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _target_is_own_repo(target_abs: str) -> bool:
    """Is this target the repository this code lives in?

    Compared by normalised absolute path rather than by asking git, because the question is about
    where BYTES will land, and a worktree or a symlinked checkout would answer the git question
    differently from the filesystem one.
    """
    return os.path.normcase(target_abs) == os.path.normcase(_REPO_ROOT)


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _round_record(rnd, summary, passed, props=None, dec=None, phase=None):
    """One history entry, carrying what actually happened rather than a verdict word.

    History is the ONLY thing the reflectors are given. Every failing branch already wrote a real
    reason (`dec["reason"]`, `ra.get("reason")`); every SUCCEEDING branch wrote the constant string
    "accepted". A run that goes well therefore produces a history that is a column of identical
    words, and the reflectors, asked to diagnose an improvement direction from "round 1 accepted,
    round 2 accepted, ...", correctly returned nothing at all. The loop got less to reflect on the
    better it did.

    They said so themselves once their output was finally being recorded, six rounds running, in two
    languages: "the history entries are extremely sparse (only round, summary, passed fields), there
    is no record of what was actually changed, what the eval gate checked, or why each round passed".
    They also caught something nobody had noticed: rounds that ended in a static reject appended
    NOTHING, so round 5 was simply missing from the history with no explanation, which reads as data
    loss rather than as a barren round. Both are fixed here.
    """
    rec = {"round": rnd, "summary": summary, "passed": passed}
    if phase:
        rec["phase"] = phase
    if props:
        files = [p.get("file_rel") for p in props if isinstance(p, dict) and p.get("file_rel")]
        if files:
            rec["files_changed"] = files
    if isinstance(dec, dict):
        if dec.get("decision"):
            rec["decision"] = dec["decision"]
        if dec.get("evalue") is not None:
            rec["evalue"] = dec["evalue"]
        if dec.get("reason"):
            rec["reason"] = dec["reason"]
    return rec


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



def _discard_rejected_changes(sandbox_root: str, snapshot: str | None = None) -> None:
    """Restore the selected snapshot; retain the standalone tracked-edit helper."""
    snapshot = snapshot or business_tree._SELECTED_SNAPSHOT.get()
    if snapshot is not None:
        business_tree.restore(snapshot, sandbox_root)
        return
    # Legacy callers have no accepted-version context. The loop always supplies it.
    if not sandbox_root or not os.path.isdir(sandbox_root):
        return
    result = subprocess.run(['git', 'checkout', '--', '.'], cwd=sandbox_root,
                            capture_output=True, text=True, encoding='utf-8',
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    if result.returncode != 0:
        print('sie: standalone tracked-edit discard unavailable: '+result.stderr.strip()[:300],
              file=sys.stderr)


class BaselineUnavailable(RuntimeError):
    def __init__(self, status, detail=''):
        super().__init__(detail or status)
        self.status = status


def _usable_baseline(result):
    import math
    if not isinstance(result, dict) or result.get('available') is False:
        raise BaselineUnavailable('unavailable')
    if result.get('grader_exit_code', 0) != 0:
        raise BaselineUnavailable('grader_failed')
    dimensions = result.get('dimensions')
    if not isinstance(dimensions, list) or not dimensions:
        raise BaselineUnavailable('empty')
    names = set()
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            raise BaselineUnavailable('invalid_dimensions')
        score, name = dimension.get('score'), dimension.get('name')
        if (not isinstance(name, str) or not name or name in names
                or type(score) not in (int, float) or not 0 <= score <= 1
                or not math.isfinite(score)):
            raise BaselineUnavailable('invalid_dimensions')
        names.add(name)
    return result


def _restore_failed(run_dir, parent, error):
    return _step(run_dir, {
        'type': 'RESTORE_FAILED', 'phase': 'STOP', 'parent_vid': parent,
        'reason': 'restore_failed', 'restore_error': {
            'type': type(error).__name__, 'message': str(error)[:600]},
    })


def _pause_for_baseline(run_dir, sandbox_root, parent, snapshot, status, detail):
    try:
        with business_tree.selected_snapshot(snapshot):
            _discard_rejected_changes(sandbox_root)
    except Exception as exc:
        return _restore_failed(run_dir, parent, exc), 'restore_failed'
    state = _step(run_dir, {
        'type': 'BASELINE_UNAVAILABLE', 'phase': 'PAUSE_FOR_HUMAN',
        'parent_vid': parent, 'available': False,
        'baseline_status': status, 'reason': detail,
        'forced_review_delta': 1,
    })
    return state, 'baseline_unavailable'


def _base_ref_worktree(run_dir: str) -> str | None:
    """The probe worktree PROFILE built at the base ref, if it is still on disk.

    Named `profile_probe_<sha12>` by profile.py. Nothing else writes there, and it sits at the exact
    commit the sandbox was branched from, which makes it the honest "before" for round 1.
    """
    target_file = os.path.join(run_dir, 'target.json')
    if os.path.isfile(target_file):
        try:
            prof = load_target(run_dir)
            evidence = prof.get('probes', {}).get('exec', {})
            path, ref = evidence.get('worktree'), evidence.get('base_ref')
            if not path or not ref or not os.path.isdir(path):
                return None
            from tools.sie.profile import _resolve_ref
            return path if _resolve_ref(path, 'HEAD') == ref else None
        except (OSError, ValueError, RuntimeError):
            return None
    # Compatibility for callers inspecting an unfrozen, single-probe run.
    wt = os.path.join(os.path.dirname(os.path.dirname(run_dir)), 'worktrees')
    if not os.path.isdir(wt):
        return None
    candidates = [os.path.join(wt, name) for name in os.listdir(wt)
                  if name.startswith('profile_probe_') and os.path.isdir(os.path.join(wt, name))]
    return candidates[0] if len(candidates) == 1 else None


def _parent_baseline(run_dir: str, parent_vid: str, supervisor=None) -> dict | None:
    """Read only the selected parent's usable scores; missing data stays missing."""
    if not parent_vid or parent_vid == 'base':
        probe = _base_ref_worktree(run_dir)
        if not probe:
            return None
        try:
            if supervisor is not None:
                graded = supervisor.grade({}, probe, self_mode=True)
            else:
                from tools.sie.evaluate import _grade_pytest_per_task
                graded = _grade_pytest_per_task(probe)
        except Exception as exc:
            raise BaselineUnavailable('grader_failed', str(exc)) from exc
        return _usable_baseline(graded)
    try:
        entries = archive.lineage(os.path.join(run_dir, 'archive'))
    except (OSError, ValueError) as exc:
        raise BaselineUnavailable('lineage_unreadable', str(exc)) from exc
    for entry in reversed(entries):
        if entry.get('vid') == parent_vid:
            return _usable_baseline({'dimensions': entry.get('task_dimensions', entry.get('scores'))})
    return None


def _record_model_stage(run_dir, filename, record):
    """Persist caller evidence in its PRIVATE run; failed writes stop the caller."""
    from pathlib import Path
    from tools.sie import runtime_data

    directory = Path(run_dir).resolve()
    path = runtime_data.private_file_path(directory/filename)
    if path.parent != directory:
        raise runtime_data.DataBoundaryError('Model evidence escaped its run directory')
    line = json.dumps(record, ensure_ascii=False) + '\n'
    with path.open('a', encoding='utf-8') as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())



def _resume_records(run_dir):
    """Recover reflection records and holdout progress from the durable event log."""
    records = {}
    last_holdout = 0
    current_round = 0
    path = runtime_data.private_file_path(os.path.join(run_dir, "events.jsonl"))
    if not path.exists():
        return [], last_holdout
    with path.open("rb") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue  # Match replay's handling of a torn event.
            if not isinstance(event, dict):
                raise ValueError("Run event must be an object")
            if event.get("type") == "ROUND_BEGIN":
                current_round = event["round"]
            if event.get("type") == "HOLDOUT_MEASURED":
                last_holdout = max(last_holdout, event["holdout_round"])
            record = event.get("record") if event.get("type") == "ROUND_HISTORY" else None
            if record is not None:
                if not isinstance(record, dict) or type(record.get("round")) is not int:
                    raise ValueError("Invalid durable reflection record")
                records[record["round"]] = record
            elif current_round and event.get("type") in {
                    "ACCEPT", "REJECT", "CONTINUE", "STATIC_REJECT", "PAUSE_FOR_HUMAN",
                    "BASELINE_UNAVAILABLE", "RESTORE_FAILED"}:
                # Older logs retain the decision even when no rich history record was stored.
                records.setdefault(current_round, {
                    "round": current_round, "summary": event.get("reason", event["type"]),
                    "passed": event["type"] == "ACCEPT"})
    return [records[key] for key in sorted(records)], last_holdout


class _RunHistory(list):
    """Persist each completed reflection record before exposing it in memory."""
    def __init__(self, run_dir, records):
        super().__init__(records)
        self.run_dir = run_dir

    def append(self, record):
        frozen = json.loads(json.dumps(record))
        append_event(self.run_dir, {"type": "ROUND_HISTORY", "record": frozen})
        super().append(frozen)


def _btier_round_context(prof, parent_snapshot, sandbox_root, rnd, params, fetcher, parent):
    """Measure frozen visible and sampled holdout obligations on both actual trees."""
    import hashlib
    from tools.sie import evaluate as evaluator
    from tools.sie import anchors as anchor_module
    from tools.sie.probes import fact_probe

    def read_tree(root):
        result = []
        for path in fact_probe._find_artifacts(root):
            result.extend(anchor_module.extract_anchors(path))
        return result

    frozen = prof.get("anchors_visible", [])
    if not frozen:
        raise BaselineUnavailable("empty_anchors", "No frozen visible obligations")
    candidate = read_tree(sandbox_root)
    parent_anchors = frozen if parent == "base" else read_tree(parent_snapshot)
    measured = evaluator.build_btier_scores(frozen, candidate, fetcher,
                                            baseline_anchors=parent_anchors)
    if measured["unobserved"]:
        raise BaselineUnavailable("anchor_observation_unavailable", "Visible factual observations are incomplete")
    interval = int(params.get("holdout_K", 5))
    if interval <= 0:
        raise ValueError("holdout_K must be positive")
    holdout_base = holdout_with = None
    if params.get("_holdout_due", rnd > 0 and rnd % interval == 0):
        reference = prof.get("anchors_holdout_ref", {})
        if not isinstance(reference, dict):
            raise BaselineUnavailable("holdout_unavailable", "Sampled holdout reference is malformed")
        path = reference.get("path")
        digest = prof.get("anchors_holdout_sha256", reference.get("sha256"))
        if (not isinstance(path, str) or not path or not isinstance(digest, str)
                or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
                or type(reference.get("count")) is not int or reference["count"] <= 0):
            raise BaselineUnavailable("holdout_unavailable", "Sampled holdout has no frozen content identity")
        with open(path, "r", encoding="utf-8") as stream:
            holdout = json.load(stream)
        if (not isinstance(holdout, list) or not holdout
                or any(not isinstance(anchor, dict) for anchor in holdout)
                or len(holdout) != reference["count"]):
            raise BaselineUnavailable("holdout_unavailable", "Sampled holdout is empty or incomplete")
        actual_digest = hashlib.sha256(json.dumps(holdout, sort_keys=True,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
        if actual_digest != digest:
            raise BaselineUnavailable("holdout_unavailable", "Sampled holdout differs from its frozen identity")
        visible_keys = {evaluator._btier_match_key(anchor) for anchor in frozen}
        if any(evaluator._btier_match_key(anchor) in visible_keys for anchor in holdout):
            raise BaselineUnavailable("holdout_unavailable", "Holdout overlaps visible obligations")
        holdout_scores = evaluator.build_btier_scores(
            holdout, candidate, fetcher,
            baseline_anchors=holdout if parent == "base" else parent_anchors)
        if holdout_scores["unobserved"]:
            raise BaselineUnavailable("holdout_unavailable", "Sampled holdout observations are incomplete")
        holdout_base = sum(holdout_scores["base_scores"].values()) / len(holdout)
        holdout_with = sum(holdout_scores["with_scores"].values()) / len(holdout)
    return {"tier": prof["tier"], "round": rnd, "K": interval, **measured,
            "holdout_base": holdout_base, "holdout_with": holdout_with,
            "intended_accept": None, "fetcher": fetcher}

def run_loop(
    target: str,
    base_ref: str,
    run_id: str,
    max_rounds: int = 3,
    mode: str = "auto",
    _injected_fix: dict | None = None,
    fetcher=None,
    judge_codex_available: bool = True,
    judge_claude_available: bool = True,
    _extra_params: dict | None = None,  # test-only: 覆盖默认 params，生产勿传
    enforce_immutable: bool = False,    # M4.6: --self/--enforce-immutable 透传
    supervisor=None,                    # M4.6: 自举 Supervisor（None=非自举，行为完全不变）
    candidate_worktree: str | None = None,  # M4.6: 自举 candidate worktree 路径
    proposer: str = "builtin",          # propose 后端: "builtin"(默认,确定性) | "llm"(真 Claude)
    reflect_mode: str = "serial",       # 反思: "serial"(默认,M1a) | "parallel"(N=3 MARS, 真 Claude)
    dual: bool = True,                   # 每个 agent 阶段 codex&claude 双重校验(默认开; --single 关)
) -> dict:
    """Drive the M1a 10-state closed loop and return a summary dict.

    _injected_fix is an M1a scaffold parameter (not present in M3):
    it allows deterministic testing of the ACCEPT path without a real LLM.
    When provided it is merged into the reflect output so builtin.generate
    can produce a valid proposal (see builtin.py).

    fetcher: optional injected fetcher for B-tier anchor verification.
    None (default) uses real edgar/verify_anchor in production.
    Tests inject a fake fetcher to avoid network calls.

    judge_codex_available: inject judge availability for C-tier path (tests).
    judge_claude_available: inject claude availability for C-tier path (tests).
    _extra_params: optional dict to override/extend default params (tests).

    States:
      INIT -> PROFILE -> [REFLECT -> CHECK -> PROPOSE -> PATCH -> EVALUATE ->
                          ACCEPT|REJECT] * max_rounds -> done

    Returns:
      {"run_id": str, "accepted_versions": list[str],
       "final_phase": str, "run_dir": str}
    """
    run_dir = str(runtime_data.make_directory(_run_dir(target, run_id)))

    params: dict = {
        "alpha": 0.05,
        "continue_count_cap": 5,
        "no_progress_circuit_N": 8,
        "no_progress_release_M": 3,
        "static_reject_circuit": 6,
        "forced_review_circuit": 5,
        "drift_circuit": 4,
        "drift_circuit_N": 4,
    }
    if _extra_params:
        params.update(_extra_params)
    accepted: list[str] = []
    halt_reason = None

    # ------------------------------------------------------------------
    # 态0 INIT, worktree + initial event
    # ------------------------------------------------------------------
    if supervisor is not None:
        if not candidate_worktree:
            raise ValueError("Selfboot requires its isolated candidate worktree")
        sandbox_root = os.path.realpath(candidate_worktree)
    else:
        if candidate_worktree is not None:
            raise ValueError("A supplied candidate worktree requires a selfboot supervisor")
        sandbox_root = make_worktree(target, base_ref, run_id)
    st = replay(run_dir)
    if st.run_id and st.run_id != run_id:
        raise ValueError("Persisted run identity differs from requested run")
    if not st.run_id:
        st = _step(run_dir, {
            "type": "INIT", "run_id": run_id, "phase": "INIT",
            "parent_vid": None, "tier": "", "round": 0,
        })

    # ------------------------------------------------------------------
    # 态1 PROFILE, freeze tier; idempotent on resume
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

    if "A" in str(prof["tier"]) and "B" in str(prof["tier"]):
        raise ValueError("Composite A+B execution is not supported; both acceptance components are required")

    # ------------------------------------------------------------------
    # Main loop: max_rounds iterations over states 2-9
    # ------------------------------------------------------------------
    recovered_history, last_holdout_round = _resume_records(run_dir)
    history = _RunHistory(run_dir, recovered_history)
    first_round = st.round + 1
    base_snapshot = os.path.join(run_dir, 'base-snapshot')
    if not os.path.exists(base_snapshot) and not archive.lineage(os.path.join(run_dir, 'archive')):
        business_tree.snapshot(sandbox_root, base_snapshot)

    for rnd in range(first_round, first_round + max_rounds):

        params["_holdout_due"] = rnd - last_holdout_round >= int(params.get("holdout_K", 5))
        # 态2 SELECT_PARENT
        parent = select_parent(run_dir, st)
        parent_snapshot = (base_snapshot if parent == 'base' else
                           os.path.join(run_dir, 'archive', 'versions', parent, 'snapshot'))
        st = _step(run_dir, {
            "type": "ROUND_BEGIN",
            "phase": "REFLECT",
            "round": rnd,
            "parent_vid": parent,
        })

        # A resumed or differently selected parent must be the tree reflection sees.
        try:
            if business_tree.manifest(sandbox_root) != business_tree.manifest(parent_snapshot):
                with business_tree.selected_snapshot(parent_snapshot):
                    _discard_rejected_changes(sandbox_root)
        except Exception as exc:
            st = _restore_failed(run_dir, parent, exc)
            halt_reason = 'restore_failed'
            break

        # 态3 REFLECT, serial(M1a 默认) 或 parallel(MARS fanout)
        # dual 开 → 反思阶段 codex&claude 双家族异质并跑; 关 → 仅 claude。
        reflector_outcomes = []
        if reflect_mode == "parallel":
            from tools.sie.reflect import run_reflections_parallel, meta_aggregate
            _fams = ["claude", "codex"] if dual else ["claude"]
            reflector_outcomes = run_reflections_parallel(
                run_dir, history, n_reflectors=len(_fams), families=_fams)
            _record_model_stage(run_dir, 'reflector-outcomes.jsonl',
                                {'round': rnd, 'backend_outcomes': reflector_outcomes})
            agg = meta_aggregate(reflector_outcomes)
            # merged_findings(list[str]) 经统一 reflection dict 传给 propose(llm 提取 findings)
            refs = [{"merged_findings": agg.get("merged_findings", [])}]
            if not agg.get("merged_findings"):
                # 首轮/无历史 → 退回串行静态审查, 给 proposer 一点上下文
                refs = reflect(sandbox_root, history, n=1)
        else:
            refs = reflect(sandbox_root, history, n=1)
        # M1a scaffold: merge _injected_fix into first reflection for ACCEPT path testing.
        # (This parameter is removed in M3 when real LLM fanout is wired.)
        if _injected_fix:
            # Defensive: if refs is empty, use empty dict to avoid IndexError on refs[0]
            refs = [dict(refs[0] if refs else {}, **_injected_fix)]

        # Persist what reflect produced, BEFORE the gate sees it.
        #
        # Nothing reflect ever produced was written anywhere. When nine of ten barren rounds turned
        # out to be gate rejections rather than empty reflections, the reflections themselves were
        # already gone, and the cause had to be established by elimination from the source instead of
        # read off an artifact. This file is append-only and sits beside events.jsonl; it is what
        # makes a future "the reflectors said nothing" claim checkable rather than assumed.
        _record_model_stage(run_dir, 'reflections.jsonl',
            {'round': rnd, 'mode': reflect_mode, 'reflections': refs,
             'backend_outcomes': reflector_outcomes})

        # 态3b CHECK_REFLECTION, weak validation gate
        _before_gate = list(refs)
        refs = [r for r in refs if check(r, 0.5)]
        if not refs:
            # SAY WHAT WAS REJECTED. This branch was silent, and it was the loop's single most
            # frequent outcome: nine of ten barren rounds in one calibration, six of six in another.
            # The whole run's captured output was 622 characters and contained not one word about
            # reflect, so the dominant failure mode was unreconstructable after the fact. Naming the
            # keys present against the keys looked for is what turns "reflection had nothing to say"
            # (innocent) into "the reflection was full and the gate could not see it" (a defect).
            from tools.sie.check_reflection import _REFLECTION_CONTENT_KEYS
            for _i, _r in enumerate(_before_gate):
                _keys = sorted(_r) if isinstance(_r, dict) else ["<not a dict: %s>" % type(_r).__name__]
                print("sie: reflection %d rejected by the gate; keys present=%s, keys it looks "
                      "for=%s" % (_i, _keys, list(_REFLECTION_CONTENT_KEYS)), file=sys.stderr)
            if not _before_gate:
                print("sie: the reflect stage returned no reflections at all", file=sys.stderr)
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "REFLECT",
                "static_reject_delta": 1,
            })
            history.append(_round_record(rnd, "no reflection cleared the evidence gate", False, phase="REFLECT"))
            # circuit_check after static_reject
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            # TODO(M3): no_progress_release should upgrade human review frequency (spec §5.4),
            # currently only logged but takes no action.
            continue

        # 态4 PROPOSE, backend: builtin(确定性,默认) 或 llm(真 Claude proposer)
        props = propose(sandbox_root, refs, backend=proposer)
        _record_model_stage(run_dir, 'proposals.jsonl',
            {'round': rnd, 'backend': proposer, 'proposals': list(props),
             'backend_outcomes': getattr(props, 'backend_outcomes', []),
             'diagnostics': getattr(props, 'diagnostics', [])})
        if not props:
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PROPOSE",
                "static_reject_delta": 1,
            })
            history.append(_round_record(rnd, "the proposer produced no admissible proposal", False, phase="PROPOSE"))
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            continue

        # 态4b REVIEW(dual), 双家族(codex&claude)异质评审提议; 仅 live 路径(proposer=="llm")触发,
        # builtin/测试路径不调外部 agent。仅当两家族**一致 reject** 才拦(skip patch/evaluate, 省成本);
        # 否则放行交由确定性 acceptor 终裁(铁律1: 评审仅参考信号)。
        if dual and proposer == "llm" and props:
            import json as _json
            from tools.sie import agents as _agents
            _rprompt = ("Review this proposed change in a self-improvement loop. Is it a genuine "
                        "improvement (not a regression/reward-hack)? Return ONLY JSON "
                        '{"verdict":"accept"|"reject"|"abstain","notes":[]}.\n\nPROPOSAL:\n'
                        + _json.dumps(props[0], ensure_ascii=False)[:4000])
            _rv = _agents.cross_check_verdicts(_rprompt, families=("claude", "codex"))
            st = _step(run_dir, {
                "type": "DUAL_REVIEW", "phase": "REVIEW",
                "verdicts": _rv.get("verdicts"), "agree": _rv.get("agree"),
                "status": _rv.get("status"), "raw": _rv.get("raw"),
            })
            if _rv.get('status') != 'independent' or _rv.get('agree') is None:
                halt_reason = 'insufficient_independence'
                st = _step(run_dir, {'type': 'INSUFFICIENT_INDEPENDENCE', 'phase': 'REVIEW',
                                    'reason': halt_reason})
                history.append(_round_record(rnd, 'insufficient_independence', False, phase='REVIEW'))
                break
            _got = [v for v in (_rv.get("verdicts") or {}).values() if v]
            if _got and all(v == "reject" for v in _got) and len(_got) >= 2:
                note_static_reject(st)
                st = _step(run_dir, {"type": "STATIC_REJECT", "phase": "REVIEW",
                                     "static_reject_delta": 1})
                history.append(_round_record(rnd, "both reviewers rejected", False, phase="REVIEW"))
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break
                continue

        # 态5 PATCH, apply each proposal; AST + boundary gates enforced by apply_patch
        # M4.6: enforce_immutable 由 --self/--enforce-immutable 透传，默认 False（非自举不变）
        applied = False
        # apply_patch returns a precise reason for every refusal (immutable_hit, boundary, AST
        # import gate, AST danger gate). Those reasons used to be discarded and the round recorded
        # only a counter, so a run that rejected every proposal for eight rounds said WHAT happened
        # and never WHY. Diagnosing it meant re-deriving the gate by hand. The reasons are evidence;
        # they belong in the append-only log next to the decision they explain.
        rejections: list[dict] = []
        for p in props:
            res = apply_patch(sandbox_root, p["file_rel"], p["new_content"],
                              enforce_immutable=enforce_immutable)
            if res["status"] == "APPLIED":
                applied = True
            else:
                rejections.append({"file_rel": p.get("file_rel"),
                                   "status": res.get("status"),
                                   "reason": str(res.get("reason") or "")[:300]})

        if not applied:
            note_static_reject(st)   # in-memory counter update
            st = _step(run_dir, {
                "type": "STATIC_REJECT",
                "phase": "PATCH",
                "static_reject_delta": 1,
                "proposals": len(props),
                # rejections[:10] caps what the trace carries. Without the total, a trace
                # holding exactly 10 rejection records is indistinguishable from a complete
                # one, and the reasons this block exists to preserve go missing unannounced.
                "rejections_total": len(rejections),
                "rejections": rejections[:10],
            })
            history.append(_round_record(rnd, "the patch gate refused every proposal", False, phase="PATCH"))
            cc = circuit_check(st, params)
            if cc in ("no_progress_circuit", "static_reject_circuit",
                      "forced_review_circuit", "drift_circuit"):
                break
            continue

        # 态6 EVALUATE, verifiable grader (A-tier: pytest; B-tier: anchor ctx; C-tier: judge)
        _tier_str = str(prof["tier"])

        # M4.7 纵深防御：自举限 A 档。自举时若 tier 含 B 或 C → 明确拒绝。
        # B/C 路径的 evaluate 调 LLM judge / anchor 验证，无 supervisor 隔离保护，
        # candidate 可通过伪造锚得分自评,自举场景下不安全。
        # 自举（supervisor is not None）仅走 A 档（frozen pytest grader），
        # 若目标 tier 为 B/C，操作员应使用非自举流程（supervisor=None）。
        if supervisor is not None and ("B" in _tier_str or "C" in _tier_str):
            raise ValueError(
                f"自举（supervisor 注入）仅支持 A 档：tier={_tier_str!r} 含 B/C，"
                "B/C 路径无 supervisor 保护（candidate 可自评），自举被拒绝。"
                "请用非自举流程（supervisor=None）处理 B/C 档目标。"
            )

        baseline = None
        if 'A' in _tier_str and 'B' not in _tier_str:
            try:
                baseline = (_parent_baseline(run_dir, parent, supervisor) if supervisor is not None
                            else _parent_baseline(run_dir, parent))
                if baseline is None:
                    raise BaselineUnavailable('missing_base_probe' if parent == 'base' else 'unknown_parent')
                _usable_baseline(baseline)
            except Exception as exc:
                st, halt_reason = _pause_for_baseline(
                    run_dir, sandbox_root, parent, parent_snapshot,
                    getattr(exc, 'status', 'reader_failed'), str(exc))
                break

        if "B" in _tier_str:
            try:
                ev_ctx = _btier_round_context(
                    prof, parent_snapshot, sandbox_root, rnd, params, fetcher, parent)
            except (BaselineUnavailable, OSError, ValueError, TypeError) as exc:
                st, halt_reason = _pause_for_baseline(
                    run_dir, sandbox_root, parent, parent_snapshot,
                    getattr(exc, "status", "anchor_reader_failed"), str(exc))
                break
            if ev_ctx.get("holdout_base") is not None and ev_ctx.get("holdout_with") is not None:
                append_event(run_dir, {"type": "HOLDOUT_MEASURED", "holdout_round": rnd})
                last_holdout_round = rnd
            ev_result = evaluate(ev_ctx)
        elif "C" in _tier_str:
            # ---- M3.11 C 档评测接线 ----
            # 态6 C 档: inject_judge_scores(独立进程,测试可注入 mock) +
            #           evaluate_c_tier(no_regression/consistency)
            from tools.sie import evaluate as _ev_mod
            _c_artifact = sandbox_root  # artifact 路径 (信息性)

            # History records decisions, not candidate replay measurements. No replay or
            # paired-consistency provider exists here yet; report both as unavailable.
            _c_regression_replay: list[dict] = []
            _c_internal_consistency: list[tuple] = []

            # judge 主观分注入 (独立进程, 测试可 monkeypatch)
            _c_anchors_visible = prof.get("anchors_visible", [])
            _c_holdout: list[dict] = []  # holdout 锚列表 (生产由 prof 提供)
            _judge_scores = _ev_mod.inject_judge_scores(
                artifact_path=_c_artifact,
                anchors_visible=_c_anchors_visible,
                holdout=_c_holdout,
            )
            _cj_gain = float(_judge_scores.get("judge_gain", 0.0))

            _c_ev = _ev_mod.evaluate_c_tier(
                artifact_path=_c_artifact,
                regression_replay=_c_regression_replay,
                internal_consistency=_c_internal_consistency,
            )
            ev_result = {
                **_c_ev,
                "tier": "C",
                "judge_scores": _judge_scores,
                "judge_gain": _cj_gain,
                "alpha": _judge_scores.get("alpha"),
                "regression_unverified": _c_ev.get("regression_evidence") != "available",
            }
        else:
            # M4.6: 自举时跳过 evaluate（grade 由 supervisor.grade 在态7 内替代）
            if supervisor is None:
                ev_result = evaluate(sandbox_root, prof["tier"],
                                     base_result=baseline)
            else:
                ev_result = {}  # 自举：ev_result 未使用（supervisor.grade 直接在决策块中调）

        # 态7 DECIDE, B 档走 resolve_accept; C 档走 route_accept_with_gates; A 档走旧路径
        if "B" in _tier_str:
            # ---- B 档生产路径: resolve_accept 含 selfdeception 多闸 ----
            ra = resolve_accept(st, ev_result, params, run_dir=run_dir)
            ra_sd = ra.get("selfdeception", {})
            ra_next = ra["next_state"]   # "8" | "9" | "9.5" | "6"

            # Critical 2: judge_anchor_divergence → 写 DRIFT_SIGNAL 事件 (replay 持久化)
            if "judge_anchor_divergence" in ra_sd.get("alerts", []):
                st = _step(run_dir, {
                    "type": "DRIFT_SIGNAL",
                    "phase": "EVALUATE",
                    "round": rnd,
                    "drift_count_delta": 1,
                })

            if ra_next == "8":
                # 态8 ACCEPT
                vid = archive.next_version_id(run_dir)
                arch_dir = os.path.join(run_dir, "archive")
                archive.snapshot_version(arch_dir, vid, sandbox_root)
                archive.add_version(run_dir, vid, ev_result.get("archive_scores", {}), parent)
                accepted.append(vid)
                st = _step(run_dir, {
                    "type": "ACCEPT",
                    "phase": "ARCHIVE",
                    "parent_vid": vid,
                })
                history.append(_round_record(rnd, "B ACCEPT", True, props=props))

            elif ra_next == "9.5":
                # 态9.5 PAUSE_FOR_HUMAN, resolve_accept 已 forced_review++ + enqueue
                # 写事件持久化 forced_review_delta
                st = _step(run_dir, {
                    "type": "PAUSE_FOR_HUMAN",
                    "phase": "PAUSE_FOR_HUMAN",
                    "forced_review_delta": 1,
                })
                history.append({
                    "round": rnd,
                    "summary": ra.get("reason", "B forced human review"),
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break

            elif ra_next == "6":
                # CONTINUE, resolve_accept 已 no_progress++
                st = _step(run_dir, {
                    "type": "CONTINUE",
                    "phase": "REFLECT",
                    "no_progress_delta": 1,
                    "continue_count_delta": 1,
                })
                history.append({
                    "round": rnd,
                    "summary": ra.get("reason", "B CONTINUE"),
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break

            else:
                # 态9 REJECT, resolve_accept 已 no_progress++
                try:
                    with business_tree.selected_snapshot(parent_snapshot):
                        _discard_rejected_changes(sandbox_root)
                except Exception as exc:
                    st = _restore_failed(run_dir, parent, exc)
                    halt_reason = 'restore_failed'
                    break
                st = _step(run_dir, {
                    "type": "REJECT",
                    "phase": "REFLECT",
                    "no_progress_delta": 1,
                })
                history.append({
                    "round": rnd,
                    "summary": ra.get("reason", "B REJECT"),
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break

        elif "C" in _tier_str:
            # ---- M3.11 C 档决策接线 ----
            # 态7 C 档: acceptor.decide(C) + selfdeception.index +
            #           acceptor.alpha_gate(alpha) + acceptor.judge_degrade +
            #           route_accept_with_gates → ARCHIVE/PAUSE_FOR_HUMAN/REJECT
            from . import selfdeception as _selfdeception
            from . import gate_human as _gate_human
            from .acceptor import alpha_gate as _alpha_gate, judge_degrade as _judge_degrade

            if ev_result.get("available") is False:
                # Missing measurements are not an observed regression or a score of zero.
                # Stop this run with an inspectable review request and no accepted version.
                try:
                    with business_tree.selected_snapshot(parent_snapshot):
                        _discard_rejected_changes(sandbox_root)
                except Exception as exc:
                    st = _restore_failed(run_dir, parent, exc)
                    halt_reason = 'restore_failed'
                    break
                _gate_human.enqueue(run_dir, {
                    "run_id": run_id, "round": rnd, "action_type": "human_review",
                    "payload": {"reason": "C tier measurements unavailable",
                                "evaluation": ev_result},
                })
                st = _step(run_dir, {
                    "type": "PAUSE_FOR_HUMAN", "phase": "PAUSE_FOR_HUMAN",
                    "forced_review_delta": 1, "reason": "C tier measurements unavailable",
                    "available": False,
                    "regression_evidence": ev_result.get("regression_evidence"),
                    "consistency_evidence": ev_result.get("consistency_evidence"),
                    "scenario_eval": ev_result.get("scenario_eval"),
                })
                history.append({"round": rnd, "summary": "C tier measurements unavailable",
                                "passed": False})
                break

            # no_regression 硬门: 退化直接 REJECT, 跳过后续多闸
            if not ev_result.get("no_regression", True):
                st.no_progress += 1
                try:
                    with business_tree.selected_snapshot(parent_snapshot):
                        _discard_rejected_changes(sandbox_root)
                except Exception as exc:
                    st = _restore_failed(run_dir, parent, exc)
                    halt_reason = 'restore_failed'
                    break
                st = _step(run_dir, {
                    "type": "REJECT",
                    "phase": "REFLECT",
                    "no_progress_delta": 1,
                    "reason": "C no_regression hard gate",
                })
                history.append({
                    "round": rnd,
                    "summary": "C no_regression hard gate",
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break
                # 态9: no_progress 释放阀检查
                elif cc == "no_progress_release":
                    _rf = release_valve(st, params)  # 升人审频率; 不降阈; 不自动采纳
                    # freq 仅供日志/未来入队用; 当前轮继续
                continue

            # acceptor.decide(C): consistency_paired → e-process 决策
            _c_paired = ev_result.get("consistency_paired", [])
            _c_coverage = float(ev_result.get("coverage", 0.0))
            _c_dec = decide(
                _c_paired, "C", st,
                {**params, "coverage": _c_coverage},
            )

            # selfdeception 多闸
            # C 档无可见锚 (visible_anchor_gain=0.0 是结构性特征, 非统计不可靠信号):
            # 为避免 visible_anchor_gain<eps 误触 block_accept (C 档无锚是设计如此, 非失效),
            # 构造 selfdeception 后覆盖 block_accept=False.
            # 闸④ judge_anchor_divergence 仍有效: |judge_gain - 0.0| > band → 发散报警.
            _c_judge_gain = float(ev_result.get("judge_gain", 0.0))
            _c_sd = _selfdeception.index(
                judge_gain=_c_judge_gain,
                visible_anchor_gain=0.0,   # C 档无可见锚 → visible_gain=0
                holdout_gain=None,          # C 档无 holdout → 跳过闸③
                st=st,
                params=params,
            )
            # 纯 C 无锚: block_accept=True 是假阳性 (无锚而非锚增益不足), 覆盖为 False.
            # ACCEPT 已由 route_accept_with_gates 的 force_review / single_claude_block /
            # 纯 C auto 门把守, block_accept 在此冗余且会遮蔽 PAUSE_FOR_HUMAN 路由.
            _c_sd = {**_c_sd, "block_accept": False}
            # judge_anchor_divergence → drift_count++ 经 DRIFT_SIGNAL 事件持久化
            # (与 B 档一致: 只靠 _step 的 drift_count_delta 持久, 无 in-memory st.drift_count += 1)
            if "judge_anchor_divergence" in _c_sd.get("alerts", []):
                st = _step(run_dir, {
                    "type": "DRIFT_SIGNAL",
                    "phase": "EVALUATE",
                    "round": rnd,
                    "drift_count_delta": 1,
                })

            # alpha_gate: alpha=None (judge 不可用) 或双向 α 门
            _c_alpha = ev_result.get("alpha")      # None 表示 judge 不可用
            _c_anchor_up = False                    # C 档无锚 → 锚不涨
            _c_alpha_gate_out = _alpha_gate(
                alpha=_c_alpha,
                anchor_up=_c_anchor_up,
                params=params,
            )

            # judge_degrade: Codex 不可用 → 禁单 Claude auto ACCEPT
            _c_degrade = _judge_degrade(
                codex_available=judge_codex_available,
                claude_available=judge_claude_available,
            )

            # C 档强制人审条件: 在 route_accept_with_gates 优先级① (decision != ACCEPT → REJECT)
            # 之前检查; 纯 C auto / force_review / Codex 不可用 → 强制 PAUSE_FOR_HUMAN,
            # 无论 acceptor 返回 ACCEPT/CONTINUE/REJECT.
            _c_force_human = (
                (_c_dec.get("force_review") or _c_sd.get("force_review")
                 or _c_alpha_gate_out.get("force_review") or _c_degrade.get("force_review"))
                or (_c_degrade.get("single_claude_block"))
                or (mode == "auto" and _c_coverage == 0.0)   # 纯 C auto 兜底
            )

            # 综合闸路由
            # 若强制人审, 直接路由 PAUSE_FOR_HUMAN (不经 route_accept_with_gates 优先级①拦截).
            # 仅当无强制条件时, 才经 route_accept_with_gates 判断 ARCHIVE vs REJECT.
            if _c_force_human:
                _c_route = "PAUSE_FOR_HUMAN"
            else:
                _c_route = route_accept_with_gates(
                    decision=_c_dec,
                    sd=_c_sd,
                    alpha_gate_out=_c_alpha_gate_out,
                    degrade=_c_degrade,
                    mode=mode,
                    tier="C",
                    coverage=_c_coverage,
                )

            if _c_route == "ARCHIVE":
                # 态8 ACCEPT (纯 C 在 auto 模式下不会到达此处: coverage=0 → PAUSE_FOR_HUMAN)
                vid = archive.next_version_id(run_dir)
                arch_dir = os.path.join(run_dir, "archive")
                archive.snapshot_version(arch_dir, vid, sandbox_root)
                archive.add_version(run_dir, vid, [], parent)
                accepted.append(vid)
                st.no_progress = 0
                st.forced_review = 0
                st.continue_count = 0
                st = _step(run_dir, {
                    "type": "ACCEPT",
                    "phase": "ARCHIVE",
                    "parent_vid": vid,
                })
                history.append(_round_record(rnd, "C ACCEPT", True, props=props))

            elif _c_route == "PAUSE_FOR_HUMAN":
                # 态9.5 PAUSE_FOR_HUMAN, C 档强制人审 (纯 C + auto, 或 Codex 不可用)
                note_forced_review(st)   # in-memory forced_review++
                _gate_human.enqueue(run_dir, {
                    "run_id": run_id,
                    "round": rnd,
                    "action_type": "human_review",
                    "payload": {
                        "reason": "C tier forced human review",
                        "coverage": _c_coverage,
                        "alpha": _c_alpha,
                        "degrade": _c_degrade,
                        "selfdeception": _c_sd,
                        "acceptor": _c_dec,
                    },
                })
                st = _step(run_dir, {
                    "type": "PAUSE_FOR_HUMAN",
                    "phase": "PAUSE_FOR_HUMAN",
                    "forced_review_delta": 1,
                })
                history.append({
                    "round": rnd,
                    "summary": "C forced human review",
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break
                elif cc == "no_progress_release":
                    _rf = release_valve(st, params)  # 升人审频率

            else:
                # 态9 REJECT, C 档拒绝
                st.no_progress += 1
                try:
                    with business_tree.selected_snapshot(parent_snapshot):
                        _discard_rejected_changes(sandbox_root)
                except Exception as exc:
                    st = _restore_failed(run_dir, parent, exc)
                    halt_reason = 'restore_failed'
                    break
                st = _step(run_dir, {
                    "type": "REJECT",
                    "phase": "REFLECT",
                    "no_progress_delta": 1,
                })
                history.append({
                    "round": rnd,
                    "summary": _c_dec.get("reason", "C REJECT"),
                    "passed": False,
                })
                cc = circuit_check(st, params)
                if cc in ("no_progress_circuit", "static_reject_circuit",
                          "forced_review_circuit", "drift_circuit"):
                    break
                elif cc == "no_progress_release":
                    _rf = release_valve(st, params)  # 升人审频率

        else:
            # ---- A 档路径 ----
            # M4.6: 自举（supervisor is not None）时用 frozen Supervisor 裁决；非自举完全不变。
            if supervisor is not None:
                # 自举: 用 frozen Supervisor.grade 取代 evaluate（candidate 不能给自己打分）
                if os.path.normcase(os.path.realpath(sandbox_root)) != os.path.normcase(
                        os.path.realpath(candidate_worktree)):
                    raise ValueError("Selfboot patch and grade candidate identities differ")
                _grade = supervisor.grade({}, sandbox_root, self_mode=True)
                _grade_error = candidate_grade_error(_grade, baseline["dimensions"])
                if _grade_error is None:
                    from tools.sie.evaluate import pair_parent_dimensions
                    _sv_paired = pair_parent_dimensions(baseline["dimensions"], _grade["dimensions"])
                    dec = supervisor.decide(_sv_paired, prof["tier"], st, params)
            else:
                _grade_error = candidate_grade_error(ev_result.get("result"), baseline["dimensions"])
                if _grade_error is None:
                    dec = decide(ev_result["paired"], prof["tier"], st, params)
            if _grade_error is not None:
                dec = {"decision": "REJECT", "evalue": 0.0, "force_review": False,
                       "reason": "unusable candidate grade: " + _grade_error}
            nxt = apply_acceptor_outcome(st, dec, params)

            if nxt == "ARCHIVE":
                # 态8 ACCEPT: add lineage entry + snapshot
                vid = archive.next_version_id(run_dir)
                # NOTE: add_version receives run_dir (internally joins "archive"),
                #       snapshot_version receives arch_dir (pre-joined).
                # M4.6: 自举时 ev_result={}, 用 _grade（supervisor.grade 返回值）的 dimensions
                _a_dims = (_grade.get("dimensions", []) if supervisor is not None
                           else ev_result["result"]["dimensions"])
                arch_dir = os.path.join(run_dir, "archive")
                archive.snapshot_version(arch_dir, vid, sandbox_root)
                archive.add_version(run_dir, vid, _a_dims, parent)
                accepted.append(vid)

                st = _step(run_dir, {
                    "type": "ACCEPT",
                    "phase": "ARCHIVE",
                    "parent_vid": vid,
                    # ACCEPT semantics in _apply: clears no_progress / forced_review / continue_count
                })
                history.append(_round_record(rnd, "accepted", True, props=props, dec=dec))

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
                # 态9.5 PAUSE_FOR_HUMAN, non-blocking; record & increment forced_review
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
                try:
                    with business_tree.selected_snapshot(parent_snapshot):
                        _discard_rejected_changes(sandbox_root)
                except Exception as exc:
                    st = _restore_failed(run_dir, parent, exc)
                    halt_reason = 'restore_failed'
                    break
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
        **({'halt_reason': halt_reason} if halt_reason else {}),
        "final_phase": st.phase,
        "run_dir": run_dir,
    }
