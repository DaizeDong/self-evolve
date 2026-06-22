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
        run_dir:  run 目录 (用于 gate_human.enqueue 写文件); None 时用临时目录兜底.

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
    dec = decide(
        eval_out.get("b_paired", []),
        "B",
        st,
        {**params, "anchors": eval_out.get("anchors_visible_verified", [])},
    )

    # selfdeception 多闸
    visible_gain = eval_out.get("visible_anchor_gain", 0.0)
    holdout_gain = eval_out.get("holdout_gain")   # None 表示非抽检轮，直接传 None 跳过闸③
    # judge_gain: LLM judge 的主观判定增益 (M3 接线后由 reflect/judge 填充).
    # 当前 B evaluate 不产 judge_gain → 默认 0.0.
    # selfdeception 语义: value = judge_gain - visible_anchor_gain;
    # |value| <= band (0.15) 时无 judge_anchor_divergence 告警 → drift 不计入.
    # 置 0.0 保守处理: 仅当 visible_anchor_gain > 0.15 时误报发散,
    # 不会因 judge_gain=0 大面积误触 drift_circuit (visible 增益通常远低于 0.15).
    judge_gain = eval_out.get("judge_gain", 0.0)
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
    # coverage_floor_violation 或 selfdeception.force_human 是全局拦截条件——
    # 无论 acceptor 返回 ACCEPT 还是 CONTINUE (有可能在下一轮变 ACCEPT),
    # 只要这些信号存在就必须提前走人审, 防止在次优数据上持续迭代积累。
    # REJECT 路径不需要额外拦截 (REJECT 已阻断进展)。
    not_rejected = dec["decision"] in ("ACCEPT", "CONTINUE")
    cov_violation = bool(eval_out.get("coverage_floor_violation", False))
    force = cov_violation or sd["force_human"] or ("low_anchor_gain" in sd.get("alerts", []))

    if not_rejected and force:
        import tempfile as _tempfile
        _enqueue_dir = run_dir or os.path.join(
            _tempfile.gettempdir(), "sie_gate_human_fallback"
        )
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
    fetcher=None,
    judge_codex_available: bool = True,
    judge_claude_available: bool = True,
    _extra_params: dict | None = None,  # test-only: 覆盖默认 params，生产勿传
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
        "drift_circuit_N": 4,
    }
    if _extra_params:
        params.update(_extra_params)
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
            # TODO(M3): no_progress_release should upgrade human review frequency (spec §5.4),
            # currently only logged but takes no action.
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

        # 态6 EVALUATE — verifiable grader (A-tier: pytest; B-tier: anchor ctx; C-tier: judge)
        _tier_str = str(prof["tier"])
        if "B" in _tier_str:
            # B 档: 构造 evaluate ctx dict (B-tier dispatch 要求首参为含 tier:"B" 的 dict)
            # holdout 抽检: round % K == 0 时从 holdout.json 读并算均值
            _K = int(params.get("holdout_K", 5))
            _holdout_base: float | None = None
            _holdout_with: float | None = None
            if rnd > 0 and rnd % _K == 0:
                _href = prof.get("anchors_holdout_ref", {})
                _holdout_path = _href.get("path", "")
                if _holdout_path and os.path.exists(_holdout_path):
                    import json as _json
                    with open(_holdout_path, "r", encoding="utf-8") as _fh:
                        _holdout_anchors = _json.load(_fh)
                    # holdout_base=0.0 (无 baseline 时全零);
                    # holdout_with=mean(expected) 用锚 expected 字段近似当前得分
                    if _holdout_anchors:
                        _holdout_base = 0.0
                        _holdout_with = sum(
                            float(a.get("expected", 0.0)) for a in _holdout_anchors
                        ) / len(_holdout_anchors)
                # 支持测试注入 holdout 数值覆盖 (via _extra_params)
                if params.get("holdout_base") is not None:
                    _holdout_base = float(params["holdout_base"])
                if params.get("holdout_with") is not None:
                    _holdout_with = float(params["holdout_with"])
            ev_ctx: dict = {
                "tier": prof["tier"],
                "round": rnd,
                "K": _K,
                "anchors_visible": prof.get("anchors_visible", []),
                # base_scores / with_scores: 无 LLM judge 时留空(全零基线);
                # M3 接线后由 grader 填充实际分值
                "base_scores": {},
                "with_scores": {},
                "holdout_base": _holdout_base,
                "holdout_with": _holdout_with,
                # intended_accept=None: 让 _evaluate_btier 回退到原始信号,
                # 由 resolve_accept 在 acceptor 决策后再做门控 (M2.13 spec 设计)
                "intended_accept": None,
                "fetcher": fetcher,  # None=真 edgar; 测试注入假 fetcher
            }
            ev_result = evaluate(ev_ctx)
        elif "C" in _tier_str:
            # ---- M3.11 C 档评测接线 ----
            # 态6 C 档: inject_judge_scores(独立进程,测试可注入 mock) +
            #           evaluate_c_tier(no_regression/consistency)
            from tools.sie import evaluate as _ev_mod
            _c_artifact = sandbox_root  # artifact 路径 (信息性)

            # M3.11 fix #1: 不退化门 fail-safe 构造
            # 正确比较需要"当前候选对历史任务的重评结果"(after)，
            # 但当前 infra 不对历史任务重新运行当前候选——history 中只有历史轮的 passed 字段，
            # 无法得到当前候选 per-task 结果，故 before==after 哑构造永远不触发退化。
            # Fail-safe 策略: 若存在历史 passed=True 的轮次（有退化风险），
            # 不能盲目判 no_regression=True；改为 no_regression=False（保守），
            # 强制走人审路径，并在 ev_result 中标记 regression_unverified=True。
            # 「完整 historical-replay-under-candidate 重评」是已知 infra 待补项。
            _c_regression_replay: list[dict] = []
            _c_has_prior_passed = any(h.get("passed") for h in history)
            for h in history:
                # before = 该轮历史结果(已知); after = 当前候选对同任务的结果(未知/无法重评)
                # 无法真比较时保守标记: before=True 的历史任务 after 设 False(强制触发退化检测)
                _h_passed = bool(h.get("passed", False))
                _c_regression_replay.append({
                    "task": h.get("summary", ""),
                    "before": _h_passed,
                    # after: 当前候选对历史任务的重评结果——infra 未实现，无法得知。
                    # 保守 fail-safe: 一律置 False。
                    # c_tier_no_regression 仅在 before=True AND after=False 时触发，
                    # 所以历史 passed=True 的任务会保守触发退化检测 → no_regression=False
                    # → 强制人审（不静默放行）。历史 passed=False 的任务不触发（正确）。
                    "after": False,
                })
            _c_internal_consistency: list[tuple] = []  # 内部一致性配对 (本轮由 judge 填充)

            # judge 主观分注入 (独立进程, 测试可 monkeypatch)
            _c_anchors_visible = prof.get("anchors_visible", [])
            _c_holdout: list[dict] = []  # holdout 锚列表 (生产由 prof 提供)
            _judge_scores = _ev_mod.inject_judge_scores(
                artifact_path=_c_artifact,
                anchors_visible=_c_anchors_visible,
                holdout=_c_holdout,
            )
            # 一致性配对: (before_judge_gain, after_judge_gain) 若两轮均有 judge 打分
            _cj_gain = float(_judge_scores.get("judge_gain", 0.0))
            _c_internal_consistency = [(_cj_gain, _cj_gain)]  # 单轮: 一致性配对退化为相同值

            _c_ev = _ev_mod.evaluate_c_tier(
                artifact_path=_c_artifact,
                regression_replay=_c_regression_replay,
                internal_consistency=_c_internal_consistency,
            )
            ev_result = {
                "tier": "C",
                "no_regression": _c_ev["no_regression"],
                "consistency_paired": _c_ev["consistency_paired"],
                "coverage": _c_ev["coverage"],   # 恒 0.0 (C 档无可验证锚)
                "judge_scores": _judge_scores,
                "judge_gain": _cj_gain,
                "alpha": _judge_scores.get("alpha"),
                # M3.11 fix #1: 若存在历史 passed=True 轮次，no_regression 由保守 fail-safe 判定
                # (不是真比较，而是「无法重评→强制不通过」)，标记供报告说明
                "regression_unverified": _c_has_prior_passed,
            }
        else:
            ev_result = evaluate(sandbox_root, prof["tier"], base_result=None)

        # 态7 DECIDE — B 档走 resolve_accept; C 档走 route_accept_with_gates; A 档走旧路径
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
                vid = f"v{len(accepted) + 1}"
                archive.add_version(run_dir, vid,
                                    ev_result.get("result", {}).get("dimensions", []),
                                    parent)
                arch_dir = os.path.join(run_dir, "archive")
                archive.snapshot_version(arch_dir, vid, sandbox_root)
                accepted.append(vid)
                st = _step(run_dir, {
                    "type": "ACCEPT",
                    "phase": "ARCHIVE",
                    "parent_vid": vid,
                })
                history.append({"round": rnd, "summary": "B ACCEPT", "passed": True})

            elif ra_next == "9.5":
                # 态9.5 PAUSE_FOR_HUMAN — resolve_accept 已 forced_review++ + enqueue
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
                # CONTINUE — resolve_accept 已 no_progress++
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
                # 态9 REJECT — resolve_accept 已 no_progress++
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

            # no_regression 硬门: 退化直接 REJECT, 跳过后续多闸
            if not ev_result.get("no_regression", True):
                st.no_progress += 1
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
                vid = f"v{len(accepted) + 1}"
                archive.add_version(run_dir, vid, [], parent)
                arch_dir = os.path.join(run_dir, "archive")
                archive.snapshot_version(arch_dir, vid, sandbox_root)
                accepted.append(vid)
                st.no_progress = 0
                st.forced_review = 0
                st.continue_count = 0
                st = _step(run_dir, {
                    "type": "ACCEPT",
                    "phase": "ARCHIVE",
                    "parent_vid": vid,
                })
                history.append({"round": rnd, "summary": "C ACCEPT", "passed": True})

            elif _c_route == "PAUSE_FOR_HUMAN":
                # 态9.5 PAUSE_FOR_HUMAN — C 档强制人审 (纯 C + auto, 或 Codex 不可用)
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
                # 态9 REJECT — C 档拒绝
                st.no_progress += 1
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
            # ---- A 档旧路径 (保持 M1 行为不变) ----
            dec = decide(ev_result["paired"], prof["tier"], st, params)
            nxt = apply_acceptor_outcome(st, dec, params)

            if nxt == "ARCHIVE":
                # 态8 ACCEPT: add lineage entry + snapshot
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
