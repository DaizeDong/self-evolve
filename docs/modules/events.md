# events 模块：事件日志与状态重建

## 职责（含在 pipeline 的位置）

self-evolve 的一轮自改进走五步：反思（reflect）→ 提案（propose）→ 评测（evaluate）→ 裁决（judge）→ 接纳（accept），全程贯穿反自欺。状态机（`statemachine.py`）把这五步落成一连串带编号的状态转移（PROFILE / REFLECT / PROPOSE / STATIC_GATE / EVALUATE / JUDGE / ACCEPT …）。**每一次状态转移都不能凭空改内存里的计数器，必须先落一条事件。**

本模块就是这套机制的底座，只干两件极窄的事：

1. **把事件追加进 `events.jsonl`**（`append_event`）——这是全流程**唯一的真相源**。
2. **把整个事件日志重放成当前运行状态**（`replay`）——给定一个 run 目录，从零状态开始逐行回放，得到一个 `RunState`。

它在 pipeline 里的位置是「最底下那一层」：上面所有阶段（反思去重、提案、评测信号 provider、裁决、接纳）做完决策后，都不直接写状态字段，而是把决策结果编码成一条事件 dict 交给本模块。状态机的 `_step()` 把三步拧成一个硬不变量：

```
append_event(run_dir, ev)   # ① 真相源先行（落盘 + fsync）
st = replay(run_dir)        # ② 纯粹由事件推导出新状态
save_state(st, run_dir)     # ③ 旁路快照（崩溃可丢，可由 ① 重建）
```

这个「先写事件、再重放、最后存快照」的顺序，是 crash-replay 能成立的根本原因：`state.json` 只是加速用的旁路缓存，任何时候删掉它再 `replay(run_dir)`，必须得到一模一样的 `RunState`。

## method

### 一、事件落盘：append-only + fsync

`append_event` 以追加模式打开 `events.jsonl`，写入一行 JSON（`ensure_ascii=False`，保留中文），随后 `flush()` + `os.fsync()` 强制刷到磁盘介质，再返回。

为什么要 fsync 而不是普通写：本模块对崩溃的容错完全建立在「已落盘的事件是可信的、未落盘的不算数」这一前提上。fsync 把「这条事件已提交」这件事变成磁盘上的物理事实——进程在 fsync 返回后崩溃，事件保留；在 fsync 之前崩溃，事件要么完全没写、要么只写了半行。半行的情况由重放侧兜底（见下）。

文件格式是 JSON Lines：一行一个事件，永不修改、永不删除已有行。这让事件日志天然就是一份按时间排序、可追加、可逐行重放的账本。

### 二、状态重建：从零回放，纯函数推导

`replay(run_dir)` 是本模块的核心。它**不读 `state.json`**，而是：

1. 构造一个零状态 `RunState(run_id="", phase="INIT", round=0, parent_vid=None, tier="")`，所有计数器默认 0。
2. 逐行读 `events.jsonl`，每行 `json.loads` 后交给内部纯函数 `_apply(rs, ev)`，把返回的新状态接力下去。
3. 文件不存在 → 直接返回零状态（一个全新的 run）。

`_apply` 决定「一条事件如何改变状态」，规则分三类：

**（1）直接覆盖的标量字段**——`_DIRECT = ("run_id", "phase", "round", "parent_vid", "tier")`。事件里带了这些 key 就直接覆写。例如 PROFILE 阶段写一条带 `phase` / `round` / `tier` 的事件，重放时就把这些字段定下来。`tier`（档位）一旦在 PROFILE 写定就不再变，可以是 `"A"` / `"B"` / `"C"` 或叠加形态如 `"A+B"`。

**（2）计数器：只认 `_delta` / `_reset` 后缀，不认裸字段。** 受管的五个计数器是：

| 计数器 | 含义（白话） |
| --- | --- |
| `no_progress` | 连续没拿到进展的轮数（评测没通过 / CONTINUE） |
| `static_reject` | 被静态闸门挡掉的次数 |
| `forced_review` | 被强制转人工复核的次数 |
| `continue_count` | CONTINUE 决策累计次数 |
| `drift_count` | 检测到漂移信号（如裁决与证据锚点背离）的累计次数 |

对每个计数器 `cnt`：

- 若事件带 `{cnt}_delta`，则 `new = old + delta`。**注意判定用的是 `d is not None`**，所以 `delta=0` 是合法的「显式零增量」事件，照样会被处理（而不是被当成「没写」忽略）。
- 若事件带 `{cnt}_reset` 为真**且事件 `type` 不是 `ACCEPT`**，则把该计数器清零。这是给非接纳场景留的显式清零口子。

**关键约束：事件里直接写裸计数器字段（如 `no_progress: 3`）会被完全忽略。** 计数器只能经 delta 增量或 reset/ACCEPT 语义修改。这是刻意的——它把「计数器的演化」约束成一串可累加、可重放的增量，杜绝了「某条事件偷偷把计数拍到一个绝对值」这种无法审计的跳变。

**（3）ACCEPT 语义清零。** 当事件 `type == "ACCEPT"`（一次提案被接纳）时，无条件清零 `no_progress` / `forced_review` / `continue_count` 三个计数器——一次成功的接纳意味着「卡住」的状态被解除，这几个「卡了多久」的计数自然归零。`static_reject` 与 `drift_count` **不**在 ACCEPT 时清零（它们记录的是历史累计的风险信号，跨接纳保留）。

### 三、崩溃容错：半行事件静默跳过

重放循环里，`json.loads` 抛 `JSONDecodeError` 时**静默 `continue`**，不报错、不中断。这一行专门对付「在 `append_event` 写到一半时进程崩溃」的场景——`events.jsonl` 末尾可能留下一行不完整的 JSON。

这么处理的依据正是真相源不变量：一条事件只有在 fsync 完整返回后才算「已提交」；写到一半的事件从未完整提交，因此**不应**影响状态重建。跳过它，等价于「这次崩溃前的最后一步没发生过」，状态回到上一条完整事件的位置——干净、确定、可恢复。重启后状态机从这个位置继续，最多重做一步（幂等设计保证重做安全）。

### 四、state.json 的角色：旁路快照，不是真相

`state.py` 提供 `RunState` 数据类与 `save_state` / `load_state`。务必明确它们的从属地位：

- `save_state` 用「写临时文件 + fsync + `os.replace` 原子 rename」三步写盘。`os.replace` 在 Windows 和 POSIX 上都是原子的，保证读者要么看到旧快照、要么看到新快照，绝不会看到写一半的 `state.json`。
- `load_state` 读 `state.json`，并且**只取 `RunState` 字段集合内的 key**（`{f.name for f in fields(RunState)}` 过滤），多余字段丢弃——容忍未来 schema 演进时旧快照里的陌生字段。

但 `state.json` 永远是可丢弃的派生物。`cli.py` 里 `status` 走 `load_state`（快），`replay` 走 `replay`（重建，权威）；二者若不一致，以 `replay` 为准。任何怀疑状态损坏的场合，删掉 `state.json` 重放即可自愈。

## 契约

### `append_event(run_dir: str, event: dict) -> None`

- **输入**：`run_dir`（run 目录，不存在会被 `makedirs`）；`event`（任意 JSON 可序列化 dict）。
- **副作用**：向 `{run_dir}/events.jsonl` 追加一行，flush + fsync。
- **返回**：无。
- **事件 dict 约定的可识别 key**：
  - 标量覆写：`run_id` / `phase` / `round` / `parent_vid` / `tier`
  - 计数器增量：`no_progress_delta` / `static_reject_delta` / `forced_review_delta` / `continue_count_delta` / `drift_count_delta`（值为整数，可正可负可为 0）
  - 计数器清零：上述五者对应的 `{cnt}_reset`（真值；ACCEPT 事件除外）
  - 语义触发：`type == "ACCEPT"`（触发三计数器清零）；`type == "DRIFT_SIGNAL"` 等由调用方约定，本模块只看上面这些 key
  - 其余 key（时间戳、reason、proposal id 等）本模块原样落盘但不参与状态推导，留给审计与人读。

### `replay(run_dir: str) -> RunState`

- **输入**：run 目录。
- **输出**：从零状态逐行回放 `events.jsonl` 得到的 `RunState`。文件不存在 → 零状态。损坏行静默跳过。
- **纯度**：不读 `state.json`，不写任何文件。同一份 `events.jsonl` 永远重建出同一个 `RunState`（确定性）。

### `RunState`（state.py，本模块状态载体）

```
run_id: str
phase: str
round: int
parent_vid: str | None
tier: str            # "A"|"B"|"C"|叠加如"A+B"
no_progress: int = 0
static_reject: int = 0
forced_review: int = 0
continue_count: int = 0
drift_count: int = 0
```

### `save_state(rs, run_dir)` / `load_state(run_dir)`

- `save_state`：原子写 `{run_dir}/state.json`（tmp + fsync + replace）。
- `load_state`：读回 `RunState`，过滤掉非字段 key。
- 二者是旁路快照接口，权威性低于 `replay`。

### 相邻模块接口

- **`statemachine.py`（上游主调用方）**：每次状态转移调 `_step(run_dir, ev)`，内部严格执行 `append_event → replay → save_state`。注释明文写出硬不变量：「Every state transition calls append_event BEFORE save_state」「删除 state.json 后 replay 必须产生相同 RunState」。所有计数器变更（如 `static_reject_delta=1`、`no_progress_delta=1`、`drift_count_delta=1`、`forced_review_delta=1`）都由它构造进事件 dict，本模块不主动累加任何东西。
- **`cli.py`**：`status` 子命令调 `load_state` 打印快照；`replay` 子命令调 `replay` 重建并打印——给运维一个「快照 vs 重放」的对照入口。

## 反自欺点

本模块是反自欺体系最底层的一道结构性防线。它要防的自欺形态，以及对应闸门：

- **自欺形态一：偷偷把计数器拍到想要的值。** 比如一条事件直接写 `no_progress: 0` 假装「没卡住」，或把 `drift_count` 抹平来掩盖漂移。
  **闸门**：`_apply` 只认 `_delta` / `_reset` / ACCEPT 语义，**裸计数器字段一律忽略**。计数器只能沿可累加、可逐条审计的增量演化，没有「无来由的绝对值跳变」这条路。

- **自欺形态二：拿一份被手改过的状态快照充当真相。** 直接编辑 `state.json` 让流程相信自己处在某个有利状态。
  **闸门**：`state.json` 是旁路派生物，权威源永远是 `events.jsonl`。`replay` 不读快照、从零重建；运维可随时 `cli replay` 对照，或删快照自愈。手改快照改不动账本。

- **自欺形态三：崩溃后用半截事件蒙混过关。** 把写到一半的事件当成「已发生」，让状态停在一个似是而非的中间态。
  **闸门**：append 侧 fsync 把「已提交」钉成磁盘事实；replay 侧对 `JSONDecodeError` 静默跳过，未完整提交的事件等同于没发生。崩溃恢复点永远落在上一条完整事件，确定且无歧义。

- **自欺形态四：先改内存状态、事后补（或不补）事件。** 让真相源滞后于真实状态，事件日志变得不可信。
  **闸门**：`_step` 的硬顺序是 append 先行、replay 推导、save 殿后。状态不是被「写」出来的，而是被事件「重放」出来的——绕过事件就改不了状态。

## 代码锚

- `tools/sie/events.py:append_event` — append-only + flush + fsync 落盘单条事件
- `tools/sie/events.py:_apply` — 单条事件如何改状态（标量覆写 / delta / reset / ACCEPT 清零）
- `tools/sie/events.py:replay` — 从零状态逐行重放，损坏行静默跳过
- `tools/sie/events.py:_DIRECT` — 允许直接覆写的标量字段白名单
- `tools/sie/state.py:RunState` — 状态数据类（字段 + 五个受管计数器）
- `tools/sie/state.py:save_state` — tmp + fsync + 原子 replace 写快照
- `tools/sie/state.py:load_state` — 读快照并按字段集合过滤
- `tools/sie/statemachine.py:_step` — 上游：append→replay→save 三步硬不变量的执行处
- `tools/sie/cli.py` — `status`（load_state）与 `replay`（replay）两个对照入口
