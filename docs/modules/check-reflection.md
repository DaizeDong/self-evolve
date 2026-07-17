# check-reflection（反思校验 / trace 证据门）

## 职责

`check_reflection` 是 self-evolve 闭环里**反思阶段的守门人**。方法论的恒定主干是 `reflect → propose → evaluate → judge → accept`，并在全程贴反自欺闸门。本模块卡在 `reflect`（产出反思 finding）与 `propose`（把 finding 翻成改进提案）之间，决定哪些反思有资格往下走。

在状态机里的确切位置（见 `statemachine.py` 的状态串）：

```
INIT → PROFILE → [REFLECT → CHECK → PROPOSE → PATCH → EVALUATE → ACCEPT|REJECT] * max_rounds
```

`CHECK` 这一态就是本模块。它接 `reflect()` 的输出，逐条过校验；**全部不通过则该轮直接判 STATIC_REJECT**（记一次静态拒绝计数，喂给熔断器），连 `propose` 都不进。也就是说，反思质量不达标的轮次不会浪费下游的 patch/评测算力，更重要的是,**它把"凭空想象的改进点"挡在系统演化之外**。

模块本身只做一件事：判断一条反思是否站得住脚。它有两档强度：

- **弱校验 `check`（M1a，当前 live 接线）**：只要反思非空、含有意义字段就放行。这是早期脚手架阶段的最低门槛，目的是先让端到端闭环跑通。
- **trace 证据门 `check_benchtrace`（M3）**：升级版强校验。要求反思的**每一条 finding 都必须引用至少一条真实存在的历史 trace ID**，否则视为臆造、不予 grounded。这是本模块的核心反自欺机制。

> 当前 `statemachine.py` 第 33 行导入并调用的是弱校验 `check`（`refs = [r for r in refs if check(r, 0.5)]`，约 532 行）。`check_benchtrace` 是 M3 阶段在同一模块内提供的更强门，按 SDD 计划将替换弱校验接线。两者共存于本文件，本文档同时记述。

## method

### 弱校验 `check`

判据极简：反思 dict 非空，且在四个"有意义字段",`target_failure` / `static_review` / `fix_content` / `files`,中**任意一个**有非空值，即通过。

```python
keys = ("target_failure", "static_review", "fix_content", "files")
return any(reflection.get(k) for k in keys)
```

这对应 `reflect()` 在 M1a 串行模式下的两种产出形态：有历史时产 `{target_failure, round}`（读上一轮失败摘要），首轮无历史时产 `{static_review, files}`（对 target 当前源码做静态审查）。弱校验只确认"反思不是空壳"，不验证内容真伪,所以它**不是**反自欺门，只是脚手架阶段的占位。真正的证据约束在下面。

### trace 证据门 `check_benchtrace`

核心思想（反自欺）：**反思必须可追溯到真实的历史 trace 证据，杜绝凭空臆造的"改进方向"**。一条 finding 如果引用了不存在的 trace ID，或者根本没引用，就是"无根据"（ungrounded）,它可能是模型自己幻想出来的问题、或为了显得在工作而硬编的改进点。

算法是**基于集合的引用核对**，分三步：

1. **建立可信证据集**。把调用方传入的 `available_traces`（真实发生过的历史 trace ID 列表）转成 set `avail`。这是唯一的"真相来源",只有这里面的 ID 才算数。

2. **逐条 finding 核对引用**。对 `reflection["findings"]` 里每条 finding，取它的 `trace_refs`，筛出确实落在 `avail` 里的引用：

   ```python
   refs = [r for r in f.get("trace_refs", []) if r in avail]
   ```

   - 只要 `refs` 非空（至少命中一条真实 trace），该 finding 记为 **grounded**。一条 finding 可以引多个 trace，**有一个真实就够**（容忍它顺带提了别的）。
   - 否则收进 `ungrounded`，并记下它的原文 `text` 与不合格的 `bad_refs`，供调用方诊断到底是哪条凭空捏造。

3. **算 grounded 比例并比阈值**。`grounded_ratio = grounded / len(findings)`。当且仅当 `ratio >= threshold`（默认 0.5，即 `reflection_correctness_threshold`）时 `pass=True`。

   边界：`findings` 为空直接 `{"pass": False, "grounded_ratio": 0.0, "ungrounded": []}`,空反思没有任何证据，不放行；`ungrounded` 为空是因为压根没东西可判（区别于"有 finding 但全臆造"）。

阈值取比例而非"全部 grounded"，是刻意留的容错带：允许一小部分探索性 finding 暂时无 trace 支撑，但**多数必须有据**。比例低于阈值即整体不通过,意味着这轮反思整体不可信。

设计上它**只读不写**（Iron Law 2：历史 trace append-only，本模块绝不改动它，只把它当只读证据来核对），是纯函数式判定，无副作用。

## 契约

### `check(reflection, threshold=0.5) -> bool`

| 项 | 内容 |
|----|------|
| 入参 `reflection` | `dict`，单条反思。识别字段 `target_failure` / `static_review` / `fix_content` / `files` |
| 入参 `threshold` | `float`，当前实现未使用（保留位，与下游签名对齐） |
| 返回 | `bool`，True=有意义可放行 |

### `check_benchtrace(reflection, available_traces, threshold=0.5) -> dict`

| 项 | 内容 |
|----|------|
| 入参 `reflection` | `dict`，须含 `findings: list[dict]`；每条 finding 形如 `{"text": str, "trace_refs": list[str]}` |
| 入参 `available_traces` | `list[str]`，真实历史 trace ID 全集（唯一真相来源，只读） |
| 入参 `threshold` | `float`，grounded 比例下限，默认 0.5 |
| 返回 | `dict`：`{"pass": bool, "grounded_ratio": float, "ungrounded": list[dict]}`；`ungrounded` 每项 `{"text": str, "bad_refs": list[str]}` |

### 相邻模块接口

- **上游 `reflect.py`**：
  - 串行 `reflect(sandbox_root, history, n=1) -> list[dict]`（M1a），产出 `target_failure` / `static_review` 形态的反思，喂给弱校验 `check`。
  - 并行 `run_reflections_parallel(run_dir, history, n_reflectors=3)` + `meta_aggregate(...) -> {"merged_findings": [...], ...}`（M3 的并行反思去重：N 个互不可见的反思器各自跑、合并去重）。聚合出的 `findings` 是 `check_benchtrace` 的判定对象。
- **证据源 `events.py`**：历史 trace 来自 `events.jsonl`（append-only，`append_event` 写、`replay` 读）。`available_traces` 即从中导出的真实事件 ID 集合。
- **下游 `propose.py`**：只有过门的反思才进入 `propose()` 生成提案。
- **调用方 `statemachine.py`**：在 `CHECK` 态执行过滤（`refs = [r for r in refs if check(r, 0.5)]`）；全空则调 `note_static_reject` 记一次静态拒绝并发 `STATIC_REJECT` 事件，随后 `circuit_check` 可能因 `static_reject_circuit` 熔断。

## 反自欺点

本模块要防的自欺形态，以及对应闸门：

| 自欺形态 | 表现 | 闸门 |
|----------|------|------|
| **凭空臆造改进点** | 反思列出一堆"问题/改进方向"，但没有任何真实历史 trace 支撑,模型幻想或为显得勤奋而硬编 | `check_benchtrace`：每条 finding 必须引用 `available_traces` 内的真实 ID 才算 grounded |
| **引用不存在的 trace** | finding 编造一个看似合理的 trace ID（如 `tr_999`）来伪装"有据" | 集合核对 `r in avail`：不在真相集里的引用一律剔除，该 finding 落入 ungrounded |
| **空壳反思骗过下游** | 交一个空 / 无意义的反思占位，骗系统认为"反思过了" | 空 `findings` → 直接 `pass=False`；弱校验也要求至少一个有意义字段非空 |
| **少数真实掺大量臆造** | 引一两条真 trace，夹带一堆无根据 finding 来撑提案 | `grounded_ratio >= threshold` 比例门：多数 finding 必须有据，否则整轮不通过 |

闸门触发后的系统后果：反思被拒 → 该轮 `STATIC_REJECT` → 计入静态拒绝计数 → 累积可触发熔断（`static_reject_circuit`），从机制上让"持续产出无根据反思"的演化路径自我终止，而非污染下游提案与采纳。

> 关于 A/B/C：它们是评测策略 / 信号 provider（怎么取信号、取什么信号），不是"目标等级"，与本门的判定无关,无论用哪种信号策略，反思都得先过 trace 证据门。权威定义见 `docs/reference/signal-providers.md`。

## 代码锚

- `tools/sie/check_reflection.py:check`, 弱校验（M1a，当前 live 接线）
- `tools/sie/check_reflection.py:check_benchtrace`, trace 证据门（M3 反自欺核心）
- `tools/sie/reflect.py:reflect`, 上游串行反思（M1a）
- `tools/sie/reflect.py:run_reflections_parallel` / `tools/sie/reflect.py:meta_aggregate`, 上游并行反思去重 + 聚合（M3）
- `tools/sie/statemachine.py:run`（约 514 to 544 行 CHECK 态过滤 + STATIC_REJECT 分支）, 调用方接线
- `tools/sie/statemachine.py:note_static_reject` / `tools/sie/statemachine.py:circuit_check`, 拒绝计数与熔断
- `tools/sie/events.py:append_event` / `tools/sie/events.py:replay`, 历史 trace（证据源，append-only 只读）
