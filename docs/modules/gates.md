# 闸门（gates）

## 职责（含在 pipeline 的位置）

self-evolve 的主循环是 `reflect → propose → evaluate → judge → accept`，每一轮跑完后落在「接受态」。闸门是这一接受态之后、真正动手把候选写回主线（archive）之前的最后一道关卡，再叠加一层跨轮次的「整段 run 健康度」监控。

闸门做两件互相独立的事：

1. **三正交计数器 + 漂移熔断**：四个跨轮累计的计数器，分别盯住四种「这条 run 已经走不动 / 正在变坏」的形态。任何一个先撞到阈值，就把整段 run 熔断停机，交给人。
2. **落地走人审子流程**：当某一轮被判定「不能自动采纳，但也不该直接拒」时，不是阻塞等人，而是把这次决策写成一条待办记录、立刻返回继续跑别的，人事后异步处理。

在 pipeline 里的位置：

```
            ┌─────────────────────────────────────────────┐
 一轮内 →   │ accept 态:                                    │
            │   acceptor.decide  ──┐                        │
            │   selfdeception.index ┤→ route_accept_with_gates → ARCHIVE / REJECT / PAUSE_FOR_HUMAN
            │                       │     (单轮闸: 是否能落地这一个候选)
            └───────────────────────┴──────────────────────┘
                         │ 每轮各自给计数器 +1
                         ▼
 跨轮 →     circuit_check(三计数器 + drift_count)  → 命中阈值则熔断整段 run
                         │
                         ▼
 落地走人审 → PAUSE_FOR_HUMAN ⇒ gate_human.enqueue(写一条待办, 非阻塞返回)
                                  人异步 resolve ⇒ approved / skipped / expired
```

需要分清两层：**单轮闸**（selfdeception 那几道闸 + route_accept_with_gates）决定「这一个候选这一轮怎么处置」；**计数器熔断**决定「这整段 run 是不是该停了」。单轮闸的处置结果会喂给计数器，计数器攒够了才熔断。

> 关于 A/B/C：这里的「档位（tier）」是**评测策略 / 信号 provider**（用什么信号来核验一个候选是否真的变好了），不是「目标难度等级」。闸门对不同档位的接线略有差异（比如纯 C 档无程序化锚、B 档无 judge），下文相应处会点明。档位的权威定义见 `reference/signal-providers.md`。

---

## method

### 一、三正交计数器 + drift 漂移，共四个

状态挂在 `RunState`（`state.py`）上，跟着 events.jsonl 一起 replay，所以崩溃重放后计数器值完全一致：

```python
no_progress:    int = 0   # 无进展轮次
static_reject:  int = 0   # 静态空拒轮次
forced_review:  int = 0   # 进过人审的次数
drift_count:    int = 0   # 累计漂移
```

为什么叫「正交」：四个计数器各盯一种**互不重叠**的失败形态，谁也不蹭谁的计数。同一轮里可能只动其中一个，绝不会一件事被两个计数器同时记账。逐个说清各自的语义和「在什么时刻 +1」：

**1) `no_progress` —— 这一轮真的尝试了改动，但没换来进展。**
acceptor 这一轮判 REJECT 或 CONTINUE，都算「跑了一轮却没把候选落地」，各 +1（`apply_acceptor_outcome` / `resolve_accept` 里 REJECT、CONTINUE 分支都 `st.no_progress += 1`）。一旦判 ACCEPT，立即清零（连带把 `forced_review`、`continue_count` 一起清零）—— 因为「真的进展了」就把所有「卡住」的账一笔勾销。

**2) `static_reject` —— 连方案都没产出，空转。**
当 propose 阶段交白卷（态4 候选集为空）或评测阶段全军覆没（态5 全部被拒）时，由 `note_static_reject` 让它 +1。它**故意不碰** `no_progress`：「没产出任何东西」和「产出了但没用」是两种不同的病，得分开计，否则没法区分「proposer 哑火」与「proposer 在原地打转」。

**3) `forced_review` —— 这一轮被推进了人审子流程。**
每次进入 PAUSE_FOR_HUMAN（态9.5）时由 `note_forced_review`（或 resolve_accept / 各档路径里直接 `st.forced_review += 1`）+1。它衡量的是「这条 run 多频繁地需要人来兜底」。频繁触发人审本身就是一种「自动化已经撑不住」的信号，所以它独立成阈。

**4) `drift_count` —— 连续采纳了，可大盘却不涨，疑似在偷偷过拟合。**
这是漂移熔断的累计器。它不由前三个那种「单轮事件」直接驱动，而是由两条来源喂：
- `selfdeception.index` 报出 `judge_anchor_divergence`（judge 自评增益显著超出锚真实增益，疑似 judge 与提案合谋虚报）时，调用方 `st.drift_count += 1`；
- `drift_circuit(st, holdout_up, params)`：若本轮 holdout / 全量回归**有**提升则 `drift_count` 清零，**没有**提升则 +1。

无论哪条来源，drift_count 的累加都必须随事件持久化（写 `drift_count_delta=1` 的事件），靠 replay 还原，绝不只停留在内存里 —— 这是保证「重放后熔断行为一致」的硬约束。

### 二、阈值与判定优先级（circuit_check）

`circuit_check(st, params)` 在每轮的计数器更新后被调用，按**固定优先级**自上而下检查，命中即返回原因 token、不再往下看（默认阈值见括号）：

| 顺序 | 条件 | 返回 token | 含义 |
|---|---|---|---|
| 1 | `no_progress >= N` (8) | `no_progress_circuit` | 无进展太久 → 熔断 |
| 2 | `static_reject >= N_sr` (6) | `static_reject_circuit` | 空转太久 → 熔断 |
| 3 | `forced_review >= N_fr` (5) | `forced_review_circuit` | 太频繁求助人 → 熔断 |
| 4 | `drift_count >= N_drift` (4) | `drift_circuit` | 累计漂移 → 熔断 |
| 5 | `no_progress >= M` (3, M<N) | `no_progress_release` | **不是熔断**，升人审频率的释放阀 |

前四条都是「熔断（停机）」，第五条 `no_progress_release` 是**释放阀**，性质完全不同：它在 `no_progress` 还没到熔断阈、但已经有点卡的中间地带触发，作用仅仅是**提高人审触发频率**（`release_valve` 把 review_frequency 从 base 抬到 boost）。

释放阀有一条铁律：**它绝不降低 acceptor 的接受阈值、绝不自动把当前提案标成 ACCEPT**。它只让人更频繁地介入，不让机器更轻易地放行 —— 这是反自欺的关键设计，详见下文。

注意优先级里的一个刻意安排：熔断阈（N）必须排在释放阀（M）**前面**判。因为 M < N，当 `no_progress` 同时 ≥ M 又 ≥ N 时，必须优先报熔断而不是报释放阀，否则一条早该停机的 run 会被误判成「只是升一下人审频率」继续跑。

`circuit_check` 返回任一以 `_circuit` 结尾的 token 时，run_loop 即终止整段 run（人接手）；返回 `no_progress_release` 则不终止，只调整人审频率继续跑。

### 三、单轮闸：selfdeception 四道闸

`selfdeception.index(...)`（`selfdeception.py`，标注 IMMUTABLE）是单轮内核验「这次自评到底可不可信」的多闸函数。核心指标是**自欺指数**：

```
value = judge_gain − visible_anchor_gain
```

即「judge 嘴上说涨了多少」减去「frozen 留存锚真实核验出来涨了多少」。这个差越大，越像 judge 在自夸。四道闸（编号沿用代码注释，闸①由上游保证不在本函数内）：

- **闸①（上游保证）**：传入的 `visible_anchor_gain` 必须**只含 frozen 留存锚**（前后两轮 span 都在的锚）的增益，当轮新增的锚不算进当轮增益。这一过滤由 anchors/evaluate 在调用前完成；`retained_visible_gain(prev, cur)` 是它的参考实现 —— 只对前后两轮都出现的 span 取平均增益变化，新锚不计入分子分母。意义：不许「这轮新塞个对自己有利的锚，就声称涨了」。

- **闸②`block_accept`**：`visible_anchor_gain < ε`（默认 0.02）时置位。留存锚真实增益过低 → 统计基础不可靠 → **禁止 ACCEPT**（在路由里直接降级为硬 REJECT）。

- **闸③`force_review` / `force_human`（主信号）**：`visible_anchor_gain > 0` 且 `holdout_gain <= 0` 时置位 —— 可见锚涨了、留出来不给优化的 holdout 却没涨，典型的**过拟合背离**，强制人审。若 `holdout_gain` 为 `None`（本轮非抽检、没有 holdout 数据），此闸跳过。

- **闸④`judge_anchor_divergence`**：`|value| > band`（默认 0.15）时报警 —— judge 自评与锚核验显著背离，疑似合谋虚报。它**不直接**改 `drift_count`，而是把 alert 回传，由 statemachine 读到后执行 `drift_count += 1`（单向数据流，避免在本函数里产生副作用）。这是把「单轮的可疑信号」累积成「跨轮的漂移熔断」的桥。

`index` 返回 `{value, alerts, block_accept, force_review, force_human}`。这里有个**向后兼容的坑**：每道闸触发时会往 `alerts` 追加「旧名 + 新名」两条字符串，所以下游**绝不能用 `len(alerts)` 当触发闸数**，drift 的累计也**只能**靠专门检测 `judge_anchor_divergence` 子串来 +1。

### 四、单轮综合路由（route_accept_with_gates）

把 acceptor 决策、selfdeception、alpha_gate、judge_degrade 四路信号汇总，按固定优先级给出这一个候选的最终去向：

1. acceptor 决策 != ACCEPT → `REJECT`
2. `sd.block_accept`（闸②，留存增益 < ε）→ `REJECT`（硬拒，统计基础不可靠）
3. 任一 `force_review`（sd / alpha_gate / judge_degrade / decision 任一为真）→ `PAUSE_FOR_HUMAN`
4. `degrade.single_claude_block`（Codex 不可用 → 禁单 Claude 自动采纳）→ `PAUSE_FOR_HUMAN`
5. 纯 C 档 + auto 模式 + coverage==0（无程序化锚覆盖）→ `PAUSE_FOR_HUMAN`（纯 C auto 强制 gated，不许无锚自动落地）
6. 否则 → `ARCHIVE`（放行落地）

B 档的实际接线在 `resolve_accept` 里：它把强制人审条件归一为 `coverage_floor_violation OR sd.force_human OR ("low_anchor_gain" in alerts)`，且只要 acceptor 不是 REJECT（ACCEPT 或 CONTINUE 都算），命中即提前转 9.5 —— 防止在「次优但还没被拒」的数据上持续迭代积累自欺。B 档**无 judge**，所以缺 `judge_gain` 时令 `judge_gain = visible_gain` 使 `value=0`，避免误触闸④把正在改进的 run 误熔断。纯 C 档**无锚**，会把 `block_accept` 显式覆盖为 `False`（无锚是设计如此、不是锚增益不足，不能当假阳性硬拒）。

### 五、落地走人审子流程（非阻塞）

被判 `PAUSE_FOR_HUMAN`（态9.5）时，**不阻塞**等人。`gate_human.py` 把人审做成一个 append-only 的待办队列（`pending_actions.jsonl`），分三步：

1. **入队 `enqueue(run_dir, action)`**：写一条 `kind="request"`、`status="pending"` 的记录，带上 aid（12 位 hex）、run_id、round、action_type、payload（含触发原因、selfdeception、acceptor 决策等）、created_at、ttl（默认 86400 秒）。**立即返回 aid，不等人** —— 这是非阻塞的核心。同时 `note_forced_review`/`forced_review += 1`，并写 `forced_review_delta=1` 事件持久化。

2. **查询 `pending(run_dir)`**：扫整个 jsonl，对每个 aid 取「最新状态」（request 与 resolution 行都带 status），只返回那些最新状态仍是 `pending`、且未超 ttl 的请求。超 ttl 的视为过期、不再返回。cli `status` 命令直接把这个列表暴露给用户（连同三计数器一起）。

3. **裁决 `resolve(run_dir, aid, status)`**：人处理后追加一条 `kind="resolution"` 行，status 只能是 `approved` / `skipped` / `expired`（终态白名单，越界抛 ValueError）。**append-only，永不改写历史** —— 旧的 request 行原样保留，靠「最新状态覆盖」语义生效。

这套设计的几个要点：
- **崩溃安全**：`_read_all` 对半写坏的行静默跳过，不让一条坏行打断整个 pending 查询。
- **幂等可重放**：纯追加 + 「最新状态优先」，重复读不会算错。
- **TTL 兜底**：人长期不处理的请求会自然过期，不会无限堆积成 pending。

---

## 契约

### gate_human（人审队列 I/O）

`enqueue(run_dir: str, action: dict) -> str`
- 入参 `action`：`{run_id, round, action_type, payload, ttl?}`（ttl 缺省 86400）
- 写盘记录 schema：`{aid, kind:"request", run_id, round, action_type, payload, created_at, status:"pending", ttl}`
- 返回：aid（12 位 hex），**非阻塞**

`pending(run_dir: str) -> list[dict]`
- 返回：最新状态仍为 `pending` 且未过 ttl 的 request 记录列表

`resolve(run_dir: str, aid: str, status: str) -> None`
- `status ∈ {approved, skipped, expired}`，越界抛 `ValueError`
- 追加 schema：`{aid, kind:"resolution", status, resolved_at}`，append-only

### selfdeception（单轮自欺多闸 I/O）

`index(judge_gain, visible_anchor_gain, holdout_gain, st, params) -> dict`
- `holdout_gain=None` → 跳过闸③
- `params` 可覆盖：`frozen_anchor_effective_gain_eps`(0.02)、`selfdeception_alert_band`(0.15)
- 返回：`{value:float, alerts:list[str], block_accept:bool, force_review:bool, force_human:bool}`
- 约束：`alerts` 每闸含「旧名+新名」两条，**勿用 `len(alerts)` 判触发数**；drift 累加只认 `judge_anchor_divergence` 子串
- `index` 只读 `st.drift_count`，**不写**（写由 statemachine 负责）

`retained_visible_gain(prev_anchors, cur_anchors) -> float`：留存锚平均增益变化，新锚不计；无留存锚返回 0.0
`cumulative_drift(lineage_visible_cum, lineage_holdout_cum, tolerance=1.5) -> bool`：visible 累计 > holdout 累计 × 容差

### 相邻模块接口（statemachine 侧）

`circuit_check(st, params) -> str | None`：返回 `no_progress_circuit` / `static_reject_circuit` / `forced_review_circuit` / `drift_circuit`（任一 `_circuit` 即熔断）/ `no_progress_release`（释放阀，非熔断）/ `None`
`release_valve(st, params) -> int`：返回当前 review_frequency（仅升人审频率，绝不改 acceptor 阈或自动 ACCEPT）
`drift_circuit(st, holdout_up, params) -> bool`：holdout 涨则 drift_count 清零返 False；否则 +1，达 N_drift 返 True
`route_accept_with_gates(decision, sd, alpha_gate_out, degrade, mode, tier, coverage) -> "ARCHIVE"|"PAUSE_FOR_HUMAN"|"REJECT"`
`apply_acceptor_outcome(st, decision, params) -> "EVALUATE"|"ARCHIVE"|"LOOP"|"PAUSE_FOR_HUMAN"`（维护 no_progress / continue_count / ACCEPT 清零语义）
`resolve_accept(st, eval_out, params, run_dir) -> {next_state, acceptor_decision, selfdeception, reason}`（B 档生产路径；非 B 档转 legacy）

默认阈值（params 缺省）：`no_progress_circuit_N=8, no_progress_release_M=3, static_reject_circuit=6, forced_review_circuit=5, drift_circuit=4, drift_circuit_N=4, continue_count_cap=5`。

**持久化硬约束**：所有计数器变更必须先 `append_event`（带对应 `*_delta`）再 `save_state`；删 state.json 后 `replay` 必须还原同一 RunState。drift_count 的累加**必须**走 `drift_count_delta` 事件，不能只改内存。

---

## 反自欺点

闸门这一层本身就是反自欺的主战场，它要防的是 self-evolve 系统「骗自己变好了」的几种典型形态：

| 自欺形态 | 对应闸门 |
|---|---|
| **judge 自夸**：judge 主观给高分，但锚核验根本没这么涨 | 闸④ `judge_anchor_divergence`（`|judge_gain − visible_anchor_gain| > band`）→ 喂 `drift_count` → drift 熔断 |
| **挑锚作弊**：这轮新塞一个对自己有利的锚来虚报增益 | 闸①（上游过滤 + `retained_visible_gain`）：只认前后两轮都在的留存锚，新锚不计当轮 |
| **统计基础太薄就放行**：留存锚真实增益接近 0 也宣称 ACCEPT | 闸② `block_accept`（`< ε`）→ 硬 REJECT |
| **过拟合可见集**：可见锚涨了但留出的 holdout 不涨 | 闸③ `overfit_holdout`（主信号）→ 强制人审 |
| **温水煮青蛙式漂移**：单轮都「合规」，但连续采纳后大盘 holdout/全量回归长期不涨 | `drift_circuit`（holdout 不涨则累加，达 N_drift 熔断停机） |
| **卡住却假装在干活**：长期 REJECT/CONTINUE 空耗 | `no_progress` 熔断；中段 `no_progress_release` 升人审频率 |
| **proposer 哑火被当成正常**：根本产不出方案还继续跑 | `static_reject` 独立计数 → 熔断（不与 no_progress 混账） |
| **靠频繁求人兜底掩盖自动化失效** | `forced_review` 独立熔断阈 |
| **无锚却自动落地**：纯 C 档 auto 模式没有程序化核验就放行 | route 第 5 条：纯 C + auto + coverage==0 → 强制人审（不许无锚自动 ACCEPT） |
| **judge 退化为单点**：Codex 不可用时只剩单 Claude 自评自采 | route 第 4 条：`single_claude_block` → 强制人审 |

贯穿全局的两条反自欺铁律：

1. **释放阀只加人、不松机**：`no_progress_release` / `release_valve` 在 run 卡住时只提高人审频率，**绝不降低 acceptor 阈值、绝不自动采纳**。系统越卡，越要把人拉进来，而不是「降低标准让候选更容易过」。
2. **漂移累加必须可重放**：`drift_count` 的每一次 +1 都随事件持久化，杜绝「内存里偷偷涨、replay 后归零、于是永远不熔断」的自欺路径。

---

## 代码锚

- `tools/sie/gate_human.py:enqueue` —— 非阻塞写入待办（返回 aid，不等人）
- `tools/sie/gate_human.py:pending` —— 取最新状态仍 pending 且未过 ttl 的请求
- `tools/sie/gate_human.py:resolve` —— append-only 写终态裁决（approved/skipped/expired）
- `tools/sie/gate_human.py:_read_all` —— 容错读 jsonl（坏行静默跳过）
- `tools/sie/selfdeception.py:index` —— 单轮自欺多闸主函数（IMMUTABLE）
- `tools/sie/selfdeception.py:retained_visible_gain` —— 闸①辅助，只算留存锚增益
- `tools/sie/selfdeception.py:cumulative_drift` —— 闸④辅助，累计漂移预算检测
- `tools/sie/statemachine.py:circuit_check` —— 三计数器 + drift 的熔断/释放阀判定（含优先级）
- `tools/sie/statemachine.py:release_valve` —— 释放阀（只升人审频率）
- `tools/sie/statemachine.py:drift_circuit` —— 漂移熔断累加器
- `tools/sie/statemachine.py:route_accept_with_gates` —— 单轮综合闸路由
- `tools/sie/statemachine.py:apply_acceptor_outcome` —— 计数器更新 + ACCEPT 清零语义
- `tools/sie/statemachine.py:note_static_reject` —— static_reject++（正交于 no_progress）
- `tools/sie/statemachine.py:note_forced_review` —— forced_review++（进 9.5 时）
- `tools/sie/statemachine.py:resolve_accept` —— B 档 ACCEPT 态接线（闸 + enqueue 路由）
- `tools/sie/state.py:RunState` —— 四计数器字段（no_progress/static_reject/forced_review/drift_count）
- `tools/sie/cli.py` (status 命令) —— 暴露三计数器 + `gate_human.pending` 给用户
