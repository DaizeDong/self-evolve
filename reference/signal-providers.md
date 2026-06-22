# Signal Providers Reference（评测信号 provider）

> 旧称 "Tiers and Anchors"。**A/B/C 是同一个 `evaluate` 契约的三个信号 provider（评测
> 策略），不是目标等级。** 方法论与反自欺内核对三者不变；provider 决定信号**来源**，
> acceptor 决定信号能否被**信任**。哲学见 [`../docs/philosophy.md`](../docs/philosophy.md)。

## Provider Overview

PROFILE（態1）为目标装配一个或多个 provider（可叠加 `A+B`、`C+B`），首次冻结。
provider 决定用哪个 evaluator、acceptor 路径与安全门。

| Provider | 信号来源 | Evaluator | Acceptor 路径 |
|------|--------------|-----------|---------------|
| **A 程序裁决** | 可执行测试 pass/fail（自带或可生成） | `evaluate(sandbox_root, "A")` | e-process（二态 ACCEPT/REJECT）+ no-regression 硬门 |
| **B 锚核验** | 外部可核验事实锚（Edgar/SEC/URL/可复现命令） | `_evaluate_btier(ctx)` | e-process + 锚三门 + selfdeception 多闸 |
| **C 生成评测** | 生成场景 + rubric，异质判官（Claude×Codex）盲评 | `evaluate_c_tier` + `inject_judge_scores`；见 [scenario-eval](../docs/modules/scenario-eval.md) | no-regression + e-process + α 门 + degrade 门 + selfdeception |

复合 provider（如 `A+B`）用 `base_tier`（按 `+` 拆分）路由；run loop dispatcher 中
`"B" in tier` 优先于 `"C" in tier`。三者在 accept 端**平权**——能否采纳由统计强度（e-process
+ 多闸）决定，信号弱者自然更难达阈，但不被「它属于哪一档」结构性歧视。

---

## A — 程序裁决

**信号**：`pytest` 逐项 pass/fail。完全可验证、确定、可重放。
**Evaluator**：`evaluate.evaluate(sandbox_root, "A")` → 逐任务 `paired` 列表。
**Acceptor**：`decide(paired, "A", st, params)`
- no-regression 硬门：任一 `pass→fail` → 硬 REJECT（覆盖 e-process）
- e-process：`evalue = max(wealth_path)`；`evalue ≥ 1/α` → ACCEPT
- 二态：A 无 CONTINUE

**Run loop**：態6 pytest grader；態7 decide + apply_acceptor_outcome；態8/9 per result。

---

## B — 锚核验

**信号**：visible 锚集的逐锚核验 marginal gain（Edgar/SEC filings 等）。
**Evaluator**：`_evaluate_btier(ctx)` → `b_paired`、`visible_anchor_gain`、`holdout_gain`、`coverage`。

**Acceptor 路径**（`resolve_accept`）：
1. `acceptor.decide(b_paired, "B", st, params)` — e-process + 锚门：
   - 門1：`n_anchor < n_min` → REJECT
   - 門2：`effective_independent < 12` → REJECT（同源锚去相关）
   - 門3：`evalue_max_step` 总量钳
2. `selfdeception.index(judge_gain, visible_anchor_gain, holdout_gain, st)` — 多闸（见下）
3. CONTINUE：`1 < evalue < 1/α && continue_count < cap` → 態6 重评

**Run loop**：態6 B ctx → `_evaluate_btier`；態7 → `resolve_accept`；態8/9/9.5/6。

---

## C — 生成评测（scenario-eval）

**信号**：harness **生成**评测场景 + rubric，交异质判官盲评（prompt 无真值）。这是一条
**可主动构造**的信号通道——对任何目标都成立，故无不可评目标。完整方法见
[`../docs/modules/scenario-eval.md`](../docs/modules/scenario-eval.md)。

**Evaluator**（態6）：
- `evaluate.inject_judge_scores(artifact_path, anchors_visible, holdout)` — 契约外注入 judge
  主观分（独立进程，candidate 无法自报）。返回 `codex/claude/alpha/calibration/judge_gain`。
- `evaluate.evaluate_c_tier(artifact_path, regression_replay, internal_consistency)` — 返回
  `no_regression/consistency_paired/coverage`。

**Acceptor 路径**（態7 C 档）：
1. **no_regression 硬门**（最高优先）：任一历史成功任务回退 → 硬 REJECT。
2. `acceptor.decide(consistency_paired, "C", st, params)` — e-process 决策（coverage 注入）。
3. `selfdeception.index(judge_gain=…, visible_anchor_gain=…, holdout_gain=…, st)` — 自欺多闸；
   闸④ `|judge_gain - visible_gain| > band` → `judge_anchor_divergence` → `drift_count++`。
4. `acceptor.alpha_gate(alpha, anchor_up, params)` — 双向 α 门：
   - `alpha < α_low` → `force_review`（judge 一致性过低）
   - `alpha > α_high && not anchor_up` → `force_review + count_selfdeception`（合谋辅信号）
   - `alpha=None`（judge 不可用）→ `force_review`
5. `acceptor.judge_degrade(codex_available, claude_available)` — 降级门：Codex 不可用 →
   `single_claude_block`（单 Claude 不能 auto ACCEPT，缺独立 judge 则无法算 α）。

**纯 C 走人审条件**（任一成立 → PAUSE_FOR_HUMAN）：任一 `force_review` / `single_claude_block`
/ `mode=="auto" && 信号最弱（无可核验 coverage）`。**这不是「目标不可用」，而是信号最弱时把
终判交回人的审慎**。

> **当前实现 vs scenario-eval 目标（诚实标注）**：今日代码对「纯主观、无生成场景」的 C
> 取 `coverage=0.0` 且 `c_tier_weight` 偏低，故纯 C 难独立 auto-ACCEPT。scenario-eval 模块
> 给 C 一个**真 coverage（场景对意图的覆盖率，非恒 0）** 并使其在 accept 端与 A/B 同形
> `paired`、平权裁决——这是让 C 成为一等 provider 的设计方向，见 scenario-eval 文档。

---

## 自欺多闸

自欺指系统在 visible 指标上变好、但实际泛化（holdout/全量回归）未提升。多闸协同：

| 闸 | 触发条件 | 效果 |
|----|---------|------|
| 闸① | 调用方过滤新增锚（只传留存锚真实增益） | 防新锚虚高 visible_gain |
| 闸② | `visible_anchor_gain < ε=0.02` | `block_accept` — 禁 ACCEPT（统计基础不可靠） |
| 闸③ | `visible > 0 && holdout ≤ 0` | `force_review` — 过拟合主信号 |
| 闸④ | `|judge_gain - visible_gain| > 0.15` | `judge_anchor_divergence` → `drift_count++` |

**drift_count 持久化**：每次闸④触发写 `DRIFT_SIGNAL` 事件（`drift_count_delta=1`），经
`events.jsonl` replay 重建。`drift_count ≥ N_drift(=4)` → `drift_circuit` → 停机人审。

**累计漂移预算**：`selfdeception.cumulative_drift(...)` 检测 lineage 级累计漂移；
`lineage_visible_cum > lineage_holdout_cum * 1.5` → 过拟合漂移超预算。

**alpha 合谋辅信号**：`alpha > α_high(=0.85) && not anchor_up` → judge 间一致性异常高且锚
不涨 → 合谋嫌疑 → `count_selfdeception`。辅信号，主信号仍是 holdout 背离（闸③）。

---

## 锚概念

**Visible 锚**：用于 e-process 计分；轮间冻结留存锚。调用方须过滤新增锚（只传留存锚，
防新锚虚高当轮 `visible_anchor_gain`）。

**Holdout 锚**：不参与 e-process 计分的独立集，每 `K` 轮（默认 5）抽检查过拟合。**铁律**：
holdout 与 visible 严格不相交（混入即破坏校准）。

**Effective independent count**（`anchors.effective_independent_count`）：对同源 URL 簇去相关，
`eff = floor(1 + log2(cluster_size))` 逐簇求和。B 档 ACCEPT 需 ≥12（門2）。

**Coverage**（`anchors.coverage`）：
- A：pytest verifiable_coverage（全套 ≈1.0）。
- B：verified span 覆盖；`< 0.5` 触发 `coverage_floor_violation`。
- C：当前纯主观取 0.0；scenario-eval 下为「场景对意图的覆盖率」（见上「当前 vs 目标」注）。

---

## 熔断

| Breaker | 条件 | 动作 |
|---------|-----------|--------|
| `no_progress_circuit` | `no_progress ≥ 8` | 停 |
| `static_reject_circuit` | `static_reject ≥ 6` | 停 |
| `forced_review_circuit` | `forced_review ≥ 5` | 停 |
| `drift_circuit` | `drift_count ≥ 4` | 停 |
| `no_progress_release` | `no_progress ≥ 3` | 非熔断；`release_valve` 仅升人审频率——绝不降阈、绝不 auto-accept |
