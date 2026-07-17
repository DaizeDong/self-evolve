# pipeline, 状态机全景与收敛契约

> 本文档描述 self-evolve 主循环的状态机骨架。它把 10 个门控态串成一个可崩溃重放的闭环，
> 解释它如何收敛成一份 `SKILL.md`，并定义三个熔断计数器与 drift 的语义。
> 内容扎根于 `tools/sie/statemachine.py` 与 `tools/sie/state.py`，与代码一致。

## 职责（含在 pipeline 的位置）

self-evolve 的方法论是恒定的一条链：**反思 → 提案 → 评测 → 裁决 → 采纳**，全程贴着反自欺闸门走。
pipeline（即状态机）是这条链的**编排骨架**,它本身不做反思、不打分、不裁决，而是把各个职责模块
（`reflect` / `propose` / `patch` / `evaluate` / `acceptor` / `selfdeception` / `archive`）按固定的态序串起来，
并在每个态之间维护计数器、写事件、判熔断、决定下一步走向。

它在整个系统里的位置：

```
profile(冻结档位) ──→ [pipeline 主循环] ──→ archive(谱系) ──→ 收敛成 SKILL.md
                          │
          每轮: reflect→check→propose→patch→evaluate→decide
```

一句话职责：**pipeline 是"决定下一态是什么"的那一层**，所有"做事"的逻辑都委托给职责模块；
pipeline 只持有计数器、熔断阈、门控路由这三类编排状态。

注意一个框架前提：A / B / C 不是"目标的难度等级"，而是**评测策略/信号 provider**,
A 档用冻结的 pytest grader（可验证），B 档用锚证据门（trace 证据），C 档用 judge 主观打分。
pipeline 在态6/态7 里按 `prof["tier"]` 分派到不同的评测与裁决路径，但方法论的五个动词对三档完全一致。
（信号 provider 的权威定义见将建的 `reference/signal-providers.md`。）

## method

### 10 态门控全景 + 态9.5

主循环在 `run_loop`（`statemachine.py:412`）里。它先跑两个一次性的态（INIT、PROFILE），
然后用 `for rnd in range(1, max_rounds+1)` 循环态2,态9（每轮一次反思-提案-评测-裁决）。

| 态 | 名字 | 代码落点 | 做什么 | 失败/异常走向 |
|----|------|---------|--------|--------------|
| 0 | INIT | `make_worktree` + 首个 INIT 事件 | 建沙箱 worktree，写 run 起点 |, |
| 1 | PROFILE | `run_profile` / `load_target` + freeze | 冻结档位 tier；resume 时幂等不重跑 |, |
| 2 | SELECT_PARENT | `select_parent` (`:399`) | 选父版本：谱系空→`"base"`；否则谱系末版 vid |, |
| 3 | REFLECT | `reflect` / `run_reflections_parallel`+`meta_aggregate` | 串行(默认)或 N=3 并行反思去重，产出 findings |, |
| 3b | CHECK_REFLECTION | `check(r, 0.5)` | 弱校验闸：过滤掉强度 < 0.5 的反思 | 全空 → `note_static_reject` → STATIC_REJECT 事件 → continue |
| 4 | PROPOSE | `propose(..., backend=proposer)` | 把 findings 变成补丁提案（builtin 确定性 / llm 真 Claude） | 空 → `note_static_reject` → STATIC_REJECT → continue |
| 5 | PATCH | `apply_patch`（AST + 边界 + immutable 闸） | 逐个落盘提案；任一 APPLIED 即 `applied=True` | 全拒 → `note_static_reject` → STATIC_REJECT → continue |
| 6 | EVALUATE | `evaluate(...)` 按档分派 | A:pytest / B:锚证据 / C:judge，产出 paired 增益与门控信号 |, |
| 7 | DECIDE | A:`apply_acceptor_outcome` / B:`resolve_accept` / C:`route_accept_with_gates` | 综合 acceptor + 反自欺多闸，路由到 8/9/9.5/6 |, |
| 8 | ACCEPT | `archive.add_version` + `snapshot_version` | 入谱系、快照沙箱、清零三计数器 |, |
| 9 | REJECT | REJECT 事件 (`no_progress_delta=1`) | 拒绝本轮，no_progress++ | 熔断 → break |
| 9.5 | PAUSE_FOR_HUMAN | `gate_human.enqueue` + `note_forced_review` | 强制人审：非阻塞入队、forced_review++ | 熔断 → break |

态9.5 不是顺序里的"第十一态"，而是任意档位在态7 触发强制人审条件时的**逃逸出口**：
它把当前轮的上下文写进人审队列（`gate_human.enqueue`），forced_review 计数加一，然后回到循环顶部
（除非熔断）。它是非阻塞的,pipeline 不会卡住等人，而是记录后继续，人审在带外消化。

### 态7 三档路由的差异

态7 是 pipeline 最厚的一块，因为反自欺闸都挂在这里。三档走三条路：

- **A 档**（`statemachine.py:994`）：最朴素。`decide(paired)` → `apply_acceptor_outcome` 返回
  `ARCHIVE/EVALUATE(=CONTINUE)/LOOP(=REJECT)/PAUSE_FOR_HUMAN` 四个 token，直接照走。
  自举（`supervisor is not None`）时改用 frozen Supervisor 打分裁决，candidate 不能给自己打分。
- **B 档**（`resolve_accept`，`:226`）：`decide` 之后叠加 `selfdeception.index` 多闸。
  覆盖率地板违规 / 反自欺要求人审 / 锚增益过低（`low_anchor_gain`）任一为真 → 即便 acceptor 想 ACCEPT
  也强制走态9.5。返回 `next_state ∈ {"8","9","9.5","6"}`。
- **C 档**（`:815`）：先过 `no_regression` 硬门（退化直接 REJECT），再叠 `selfdeception.index` +
  `alpha_gate` + `judge_degrade`，最后由 `route_accept_with_gates` 综合裁决。
  纯 C（coverage=0）在 auto 模式下被强制降级为人审,没有程序化锚覆盖时不允许自动采纳。

`route_accept_with_gates`（`:170`）是 C 档（及通用）的综合闸，优先级从高到低：
非 ACCEPT→REJECT；`block_accept`（可见增益 < ε）→REJECT；任一 force_review 信号→PAUSE_FOR_HUMAN；
Codex 不可用禁单 Claude auto→PAUSE_FOR_HUMAN；纯 C+auto→PAUSE_FOR_HUMAN；否则 ARCHIVE。

### 崩溃重放硬不变式

pipeline 的状态持久化遵循一条铁律（`_step`，`:382`）：**先 append 事件，再 replay 得状态，最后 save 快照**。
`events.jsonl` 是唯一真相源，`state.json` 只是派生侧信道。删掉 `state.json` 调 `replay(run_dir)`
必须重建出完全相同的 `RunState`。这意味着**计数器永远不能直接写进事件**,
`events._apply`（`events.py:21`）只认 `<counter>_delta` / `<counter>_reset` 后缀，
直接写 `no_progress: 3` 这种字段会被静默忽略。ACCEPT 事件有专门的清零语义（清 no_progress / forced_review / continue_count）。

### 收敛成 SKILL.md 的 5 步直觉动词

pipeline 把方法论压缩成五个可记忆的动词，对应一份最终交付的 `SKILL.md` 该怎么写：

1. **反思（reflect）**,看上一轮（或基线）哪里不对，列出可改的点。对应态3/3b。
2. **提案（propose）**,把反思变成一个具体的、可落盘的补丁。对应态4/5。
3. **评测（evaluate）**,用本档的信号 provider 给"改前 vs 改后"配对打分。对应态6。
4. **裁决（judge）**,综合打分 + 反自欺闸，判 ACCEPT / REJECT / CONTINUE / 人审。对应态7。
5. **采纳（accept）**,把通过裁决的版本入谱系、快照、清零计数。对应态8。

收敛逻辑：每次态8 采纳都往 `archive` 追加一个版本（`vid = v1, v2, ...`），父指针指向上一采纳版。
`select_parent` 下一轮从谱系末版继续，于是改进沿谱系单调累积。当循环结束（跑满 max_rounds 或熔断），
谱系末版就是收敛产物,把它的五动词轨迹固化成散文，就是 `SKILL.md`：
反思看什么、提案怎么落、用什么信号评、裁决卡哪些闸、采纳后留什么。
SKILL.md 不是代码导出，而是**这条链在某个目标上跑出来的、被反自欺闸验证过的直觉**。

### 熔断三计数器

`RunState`（`state.py:8`）持有五个计数器，其中三个是核心熔断器，语义**正交**,
各自独立增减，互不串扰：

- **no_progress**（无进展轮次）：acceptor 每次 REJECT 或 CONTINUE 各 +1（A 档禁 CONTINUE 时 CONTINUE 异常决策也按 REJECT +1）。
  衡量"裁决层连续没让步"。ACCEPT 清零。熔断阈 `no_progress_circuit_N`（默认 8）。
- **static_reject**（静态拒绝）：态3b/态4/态5 三个**进入评测之前**的闸全空/全拒时由 `note_static_reject` +1。
  它**不增 no_progress**,这是"连提案都没成形"，比"提了但被拒"更早一层。熔断阈 `static_reject_circuit`（默认 6）。
- **forced_review**（强制人审）：每次进入态9.5 由 `note_forced_review` +1。衡量"系统连续把球踢给人"。
  熔断阈 `forced_review_circuit`（默认 5）。

另有 `continue_count`（CONTINUE 专属，达 `continue_count_cap`=5 后强制降级为 REJECT 落点）和
`drift_count`（见下）。

`circuit_check`（`:105`）按固定优先级判断：no_progress 熔断 → static_reject 熔断 → forced_review 熔断 →
drift 熔断 → no_progress **释放阀**（`no_progress_release_M`=3，M<N）。
释放阀不是熔断,它只**升高人审触发频率**（`release_valve`，`:134`：返回 boosted review_frequency），
**绝不降低 acceptor 阈值、绝不自动采纳**。熔断阈必须在释放阀之前判，确保 no_progress 同时 ≥M 且 ≥N 时优先报熔断。

四个真熔断（no_progress / static_reject / forced_review / drift）触发即 `break` 主循环；释放阀不 break。

### drift 语义

drift（漂移）专指一种**自欺型假进展**：连续 ACCEPT，但保留集 / 全量回归并不真的涨,
模型在可见信号上"看起来在改进"，在隐藏信号上原地踏步甚至退步。

两个入口：
- `drift_circuit`（`:147`）：每轮拿 holdout/全量回归是否上涨判断。涨→`drift_count` 清零；
  不涨→`drift_count++`，达 `drift_circuit_N`（默认 4）→停机人审。
- judge 与锚发散（`judge_anchor_divergence`）：B/C 档在态7 检测到 judge 声称的增益显著高于锚真实核验
  （合谋方向），则写一条 `DRIFT_SIGNAL` 事件（`drift_count_delta=1`），靠 `_step` 持久化到 replay。

关键工程细节：`drift_count` 的累加**只能靠 DRIFT_SIGNAL 事件持久化**，不能只在内存 `st.drift_count += 1`,
否则崩溃重放后漂移计数丢失。这是崩溃重放硬不变式在 drift 上的具体体现。

## 契约

### run_loop I/O

```
run_loop(target, base_ref, run_id, max_rounds=3, mode="auto",
         _injected_fix=None, fetcher=None,
         judge_codex_available=True, judge_claude_available=True,
         _extra_params=None, enforce_immutable=False,
         supervisor=None, candidate_worktree=None,
         proposer="builtin", reflect_mode="serial")
  -> {"run_id": str,
      "accepted_versions": list[str],   # ["v1","v2",...] 谱系采纳序列
      "final_phase": str,               # 终态 RunState.phase
      "run_dir": str}                   # <target>/.sie/runs/<run_id>
```

- `mode`：`"auto"` | `"gated"`。auto 才触发纯 C 强制人审。
- `proposer`：`"builtin"`（确定性）| `"llm"`（真 Claude）。
- `reflect_mode`：`"serial"`（默认）| `"parallel"`（N=3 并行反思去重 + meta 聚合）。
- `supervisor`：非 None 即自举模式,**仅支持 A 档**，tier 含 B/C 时 `run_loop` 直接 `raise ValueError`
  （B/C 评测调 LLM judge/锚验证，无 supervisor 隔离，candidate 可伪造得分自评）。
- `_injected_fix` / `_extra_params`：测试脚手架，生产勿传。

### select_parent I/O

```
select_parent(run_dir, st) -> str   # "base"(冷启动) | 谱系末版 vid
```

### 契约函数（M1b.6，contract-locked）

```
apply_acceptor_outcome(st, decision, params) -> str
    # "EVALUATE"(CONTINUE) | "ARCHIVE"(ACCEPT) | "LOOP"(REJECT) | "PAUSE_FOR_HUMAN"
note_static_reject(st)   -> "LOOP"   # static_reject++（不增 no_progress）
note_forced_review(st)   -> None     # forced_review++
circuit_check(st, params)-> str | None
    # "no_progress_circuit"|"static_reject_circuit"|"forced_review_circuit"
    # |"drift_circuit"|"no_progress_release"|None
```

### RunState schema（state.py:8）

```
RunState(run_id, phase, round, parent_vid, tier,
         no_progress=0, static_reject=0, forced_review=0,
         continue_count=0, drift_count=0)
tier: "A"|"B"|"C"|叠加如 "A+B"
```

### 相邻模块接口

| 方向 | 模块 | pipeline 调用的入口 |
|------|------|--------------------|
| 上游 | `profile` | `run_profile` / `freeze_target` / `load_target`（冻结 tier）|
| 上游 | `sandbox` | `make_worktree`（建隔离沙箱）|
| 内部 | `reflect` | `reflect` / `run_reflections_parallel` / `meta_aggregate` |
| 内部 | `check_reflection` | `check(r, 0.5)` |
| 内部 | `propose` | `propose(sandbox_root, refs, backend=proposer)` |
| 内部 | `patch` | `apply_patch(..., enforce_immutable=)` |
| 内部 | `evaluate` | `evaluate(...)` / `build_btier_scores` / `evaluate_c_tier` / `inject_judge_scores` |
| 内部 | `acceptor` | `decide` / `alpha_gate` / `judge_degrade` |
| 闸 | `selfdeception` | `index(judge_gain, visible_anchor_gain, holdout_gain, st, params)` |
| 闸 | `gate_human` | `enqueue(run_dir, payload)` |
| 下游 | `archive` | `lineage` / `add_version` / `snapshot_version` |
| 持久 | `events` / `state` | `append_event` / `replay` / `save_state`（`_step` 内）|

## 反自欺点

pipeline 这一层自身的自欺形态，以及挡它的闸：

- **改计数器伪造进展**：直接往事件里写 `no_progress: 0` 想清零熔断。
  → 闸：`events._apply` 只认 `_delta`/`_reset` 后缀 + ACCEPT 语义，直写字段被忽略；崩溃重放校验 state≡replay。
- **自评放水**：自举时让 candidate 给自己打分/裁决。
  → 闸：A 档自举改用 **frozen Supervisor**（`supervisor.grade`/`supervisor.decide`），不从 candidate import acceptor；
  自举遇 B/C 档直接 `raise ValueError`（B/C 无隔离保护）。
- **借释放阀偷偷降标准**：no_progress 高了就放松 acceptor 阈值或自动采纳，把"卡住"伪装成"通过"。
  → 闸：`release_valve` 只升人审频率，注释明确"绝不降阈、绝不自动采纳"。
- **可见信号刷分 / judge 合谋**：在可见锚上堆分但隐藏集不动，或 judge 声称增益远超锚核验。
  → 闸：drift（holdout 不涨累计 + `judge_anchor_divergence` 写 DRIFT_SIGNAL），达 `drift_circuit_N` 停机人审；
  `route_accept_with_gates` 的 `block_accept`（可见增益 < ε 硬 REJECT）。
- **纯主观档静默自动采纳**：纯 C（无程序化锚）在 auto 模式下直接 ACCEPT。
  → 闸：纯 C + auto + coverage=0 强制 PAUSE_FOR_HUMAN（`route_accept_with_gates` 优先级⑤）。
- **次优数据上无限迭代**：覆盖率地板违规 / 锚增益过低却继续刷轮。
  → 闸：B 档 `resolve_accept` 在 ACCEPT 或 CONTINUE（非 REJECT）路径上检 `coverage_floor_violation` /
  `force_human` / `low_anchor_gain`，命中即提前走态9.5。
- **退化被当成新版采纳**：C 档历史已通过的任务在新候选下挂了却仍 ACCEPT。
  → 闸：C 档 `no_regression` 硬门（退化直接 REJECT，跳过后续多闸）；当前 infra 无法真重评历史任务时
  fail-safe 保守置 after=False 强制触发退化检测 → 人审（`regression_unverified` 标记）。

## 代码锚

- `tools/sie/statemachine.py:run_loop`, 10 态主循环（含态7 三档路由、态8/9/9.5）
- `tools/sie/statemachine.py:select_parent`, 态2 父版本选择（冷启动→base / 谱系末版）
- `tools/sie/statemachine.py:apply_acceptor_outcome`, A 档 acceptor 决策→下一态 token + 计数器
- `tools/sie/statemachine.py:note_static_reject`, static_reject++（态3b/4/5 空拒）
- `tools/sie/statemachine.py:note_forced_review`, forced_review++（态9.5 进入）
- `tools/sie/statemachine.py:circuit_check`, 三计数器 + drift 熔断 + 释放阀优先级判定
- `tools/sie/statemachine.py:release_valve`, 释放阀（只升人审频率，不降阈）
- `tools/sie/statemachine.py:drift_circuit`, holdout 不涨累计漂移熔断
- `tools/sie/statemachine.py:resolve_accept`, B 档态7 接线（acceptor + selfdeception 多闸）
- `tools/sie/statemachine.py:route_accept_with_gates`, C/通用综合闸路由
- `tools/sie/statemachine.py:_step`, 崩溃重放硬不变式（append→replay→save）
- `tools/sie/state.py:RunState`, 状态 + 五计数器 schema
- `tools/sie/state.py:save_state` / `load_state`, 原子快照侧信道
- `tools/sie/events.py:_apply`, 计数器 delta/reset/ACCEPT 语义（直写字段被忽略）
- `tools/sie/events.py:replay`, 从 events.jsonl 纯函数重建 RunState
