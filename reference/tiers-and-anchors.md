# Tiers and Anchors Reference

## Tier Overview

Self-evolve assigns every target a **tier** at profile time (態1 PROFILE).
The tier determines which evaluator, acceptor path, and safety gates apply
throughout the run loop.

| Tier | Signal Source | Evaluator | Acceptor Path |
|------|--------------|-----------|---------------|
| **A** | Verifiable (pytest) | `evaluate(sandbox_root, "A")` | PACE e-process (二态: ACCEPT/REJECT) |
| **B** | Anchor-verified (Edgar/SEC) | `_evaluate_btier(ctx)` | PACE e-process + selfdeception 多闸 |
| **C** | Subjective only (LLM judge) | `evaluate_c_tier` + `inject_judge_scores` | C 兜底门 + selfdeception + alpha 门 + degrade 门 |

Composite tiers (e.g., `A+B`, `C+B`) use the **base_tier** (split on `+`)
to determine routing. `"B" in tier` takes priority over `"C" in tier` in the
run loop dispatcher.

---

## A Tier

**Signal**: `pytest` pass/fail per test item. Fully verifiable, deterministic.

**Evaluator**: `evaluate.evaluate(sandbox_root, "A")` → per-task `paired` list.

**Acceptor**: `decide(paired, "A", st, params)`
- no-regression hard gate: any `pass→fail` → hard REJECT (覆盖 e-process)
- PACE e-process: `evalue = max(wealth_path)`; `evalue ≥ 1/α` → ACCEPT
- Binary (二态): no CONTINUE for A tier

**Run loop states**: 態6 → pytest grader; 態7 → decide + apply_acceptor_outcome; 態8/9 per result.

---

## B Tier

**Signal**: Anchor-verified marginal gains from visible anchor set (Edgar/SEC filings).

**Evaluator**: `_evaluate_btier(ctx)` → `b_paired`, `visible_anchor_gain`, `holdout_gain`, `coverage`.

**Acceptor path** (`resolve_accept`):
1. `acceptor.decide(b_paired, "B", st, params)` — PACE e-process with anchor gates:
   - 門1: `n_anchor < n_min` → REJECT
   - 門2: `effective_independent < 12` → REJECT (同源锚去相关)
   - 門3: `evalue_max_step` 总量钳
2. `selfdeception.index(judge_gain, visible_anchor_gain, holdout_gain, st)` — 多闸:
   - 闸②: `visible_anchor_gain < ε` → `block_accept=True` (禁 ACCEPT)
   - 闸③: `visible > 0 && holdout ≤ 0` → `force_review=True` (过拟合主信号)
   - 闸④: `|judge_gain - visible_gain| > band` → `judge_anchor_divergence` alert
3. CONTINUE allowed: `1 < evalue < 1/α && continue_count < cap` → 态6 重评

**Run loop states**: 態6 B ctx dict → `_evaluate_btier`; 態7 → `resolve_accept`; 態8/9/9.5/6.

---

## C Tier — 兜底门 + 自欺多闸

**Signal**: Subjective LLM judge scores only. No verifiable program anchors (coverage=0).

**Evaluator** (態6):
- `evaluate.inject_judge_scores(artifact_path, anchors_visible, holdout)` — contract 外注入 judge 主观分 (独立进程; candidate 无法自报). 返回 `codex/claude/alpha/calibration/judge_gain`.
- `evaluate.evaluate_c_tier(artifact_path, regression_replay, internal_consistency)` — 返回 `no_regression/consistency_paired/coverage=0`.

**Acceptor path** (態7 C 档):
1. **no_regression 硬门** (优先级最高): 任一历史成功任务回退 → 硬 REJECT, 跳过后续多闸.
2. `acceptor.decide(consistency_paired, "C", st, params)` — e-process 决策 (coverage 注入). C 档权重 `c_tier_weight=0.05` 极低, 单档几乎不能独立触发 ACCEPT.
3. `selfdeception.index(judge_gain=..., visible_anchor_gain=0.0, holdout_gain=None, st)` — 自欺多闸:
   - 注: C 档无可见锚, `visible_anchor_gain=0.0` 是结构性特征 (非统计不可靠); `block_accept` 覆盖为 False (无锚不代表增益不足).
   - 闸④ 仍有效: `|judge_gain - 0.0| > band` → `judge_anchor_divergence` → `drift_count++`.
4. `acceptor.alpha_gate(alpha, anchor_up=False, params)` — 双向 α 门:
   - `alpha < α_low` → `force_review=True` (judge 一致性过低)
   - `alpha > α_high && not anchor_up` → `force_review=True + count_selfdeception=True` (合谋辅信号)
   - `alpha=None` (judge 不可用) → `force_review=True`
5. `acceptor.judge_degrade(codex_available, claude_available)` — 降级门:
   - `codex_available=False` → `single_claude_block=True + anchor_only=True + force_review=True`
   - 单 Claude 不能 auto ACCEPT (Codex 是独立 judge, 缺失则无法计算 α).

**C 档强制人审条件** (任一成立 → 強制 PAUSE_FOR_HUMAN, 不经 route_accept_with_gates 优先级①拦截):
- `decision.force_review` 或 `sd.force_review` 或 `alpha_gate.force_review` 或 `degrade.force_review`
- `degrade.single_claude_block` (Codex 不可用)
- `mode=="auto" && coverage==0.0` (纯 C auto 兜底: 不自动采纳)

**综合路由** (`route_accept_with_gates`):
- 无强制人审条件时: REJECT 或 ARCHIVE (仅 gated/人工核准后可达 ARCHIVE).
- 有强制人审条件时: 直接路由 PAUSE_FOR_HUMAN (enqueue 入队, 不 ACCEPT).

**Run loop states**: 態6 C 档评测; 態7 多闸决策; 態9.5 强制人审 (enqueue); 態9 reject + no_progress++; 態9 no_progress release_valve (仅升频率, 不降阈).

---

## 自欺多闸说明

自欺 (self-deception) 指系统在 visible 指标上表现良好, 但实际泛化能力
(holdout/全量回归) 未提升的情形. 多闸协同防御:

| 闸 | 触发条件 | 效果 |
|----|---------|------|
| 闸① | 调用方过滤新增锚 (只传留存锚的真实增益) | 防新锚虚高 visible_gain |
| 闸② | `visible_anchor_gain < ε=0.02` | `block_accept=True` — 禁 ACCEPT (统计基础不可靠) |
| 闸③ | `visible > 0 && holdout ≤ 0` | `force_review=True` — 过拟合主信号 |
| 闸④ | `|judge_gain - visible_gain| > 0.15` | `judge_anchor_divergence` alert → `drift_count++` |

**drift_count 持久化**: 每次 `judge_anchor_divergence` 触发后, run_loop 写入 `DRIFT_SIGNAL` 事件 (`drift_count_delta=1`), 经 `events.jsonl` replay 持久化. crash 重启后 replay 可重建 `drift_count`. `drift_count ≥ N_drift(=4)` → `circuit_check` 返回 `"drift_circuit"` → 停机人审.

**累计漂移预算**: `selfdeception.cumulative_drift(lineage_visible_cum, lineage_holdout_cum, tolerance=1.5)` 检测 lineage 级别累计漂移. `lineage_visible_cum > lineage_holdout_cum * 1.5` → True (过拟合漂移超预算).

**alpha 门 (合谋辅信号)**: `alpha > α_high(=0.85) && not anchor_up` → judge 间一致性异常高且锚不涨 → 合谋嫌疑 → `count_selfdeception=True`. 此为辅信号, 主信号仍为 holdout 背离 (闸③).

---

## Anchor Concepts

**Visible anchors**: Used in e-process scoring; frozen留存锚 between rounds.
Caller responsibility: filter out newly-added anchors (only pass retained anchors
so new anchors do not inflate `visible_anchor_gain` in the current round).

**Holdout anchors**: Independent set not used in e-process scoring.
Sampled every `K` rounds (holdout_K=5 by default) to detect over-fitting.
Caller responsibility: holdout anchors must be strictly disjoint from visible
anchors (iron rule; mixing invalidates calibration).

**Effective independent count** (`anchors.effective_independent_count`):
De-correlates anchors sharing the same source URL cluster.
`eff = floor(1 + log2(cluster_size))` per cluster; sum across clusters.
Minimum 12 required for B tier ACCEPT (門2).

**Coverage** (`anchors.coverage`): Fraction of verified span / total span.
- A tier: verifiable_coverage from pytest (≈1.0 for full suites).
- B tier: verified span coverage; `< 0.5` triggers `coverage_floor_violation`.
- C tier: always 0.0 (no verifiable anchors; pure subjective signal).

---

## Circuit Breakers

| Breaker | Condition | Action |
|---------|-----------|--------|
| `no_progress_circuit` | `no_progress ≥ 8` | Stop loop |
| `static_reject_circuit` | `static_reject ≥ 6` | Stop loop |
| `forced_review_circuit` | `forced_review ≥ 5` | Stop loop |
| `drift_circuit` | `drift_count ≥ 4` | Stop loop |
| `no_progress_release` | `no_progress ≥ 3 (M)` | Non-breaking; `release_valve` upgrades human review frequency only — never lowers acceptor threshold, never auto-accepts |
