# reflect — 并行反思去重

## 职责

reflect 是 self-evolve 一轮自进化的**第一个阶段**。整条 pipeline 恒定为：

```
reflect → propose → evaluate → judge → accept   （全程反自欺）
```

它的工作只有一件：从**历史 trace**（上一轮/历轮跑出来的失败证据）里诊断出「哪里坏了、该往哪个方向修」，产出一组**findings（诊断结论）**交给下游 propose 去生成具体改动。

关键边界——reflect **只诊断、不写码**：

- 它**只读历史 trace**，绝不向 trace 追加任何东西（这是「铁律 2」：历史是 append-only 的只读证据，反思阶段不允许污染它）。
- 它**不提改动方案**，那是 propose 的活。reflect 越界去"顺手把代码也改了"正是本模块要防的自欺形态之一。

在状态机里，它对应 `态3 REFLECT`，紧跟在 `态2 SELECT_PARENT`（选定本轮基于哪个版本去改）之后，产出的 findings 经 `态3b CHECK_REFLECTION` 这道闸门过滤后才进 `态4 PROPOSE`。

两种运行模式，由 `reflect_mode` 参数切换：

- `serial`（默认，脚手架态）：单次串行反思。首轮无历史时做一次静态源码审查，有历史时读上一轮失败摘要。逻辑确定、不调模型，主要服务于把管线跑通和测试。
- `parallel`（真 agent 闭环）：本文档的主角——N=3 个**相互独立的反思** fanout，各自只读历史 trace 独立诊断，最后做 **meta 去重** 合并。CLI 的 `--live` 开关会自动把模式拉到 `parallel`（同时把 proposer 切到真 Claude）。

## method

### 为什么要 N 个独立反思

单个反思 agent 容易陷进单一视角：盯着最显眼的那个报错，给一个"看起来对"的诊断就收手。**并行反思去重**的思路是——同一份历史，让 N（默认 3）个互不通信的反思者各看一遍，每人独立给出自己认为的失败点与修复方向，再把结果合并去重。多个独立视角能覆盖到单视角漏掉的失败面，去重又能压掉重复结论，最后交给 propose 的是一份**更全、更不冗余**的诊断清单。

这里"独立"是硬要求，不是口号：

- **各自一份历史快照**：`run_reflections_parallel` 给每个反思者传的是 `list(history)`（拷贝），而不是共享同一个引用。
- **并发启动、互不可见**：N 个反思者通过线程池同时 spawn，谁也读不到别人的中间产物或草稿——避免后启动的去抄先出结果的，那样 N 个反思会塌缩成 1 个。
- **trace 只读**：整个 fanout 过程不碰 trace 的写。

### 一次 parallel 反思的完整流程

1. **fanout（`run_reflections_parallel`）**：用 `ThreadPoolExecutor(max_workers=3)` 提交 3 个 `_reflect_one` 任务，每个带自己的 history 拷贝和编号 `idx`，并发执行后收齐 3 份结果。

2. **单个反思者（`_reflect_one` → `reflect-fanout.js`）**：Python 侧的 `_reflect_one` 并不自己做诊断，而是 spawn 一个 Node 子进程 `workflows/reflect-fanout.js`，把 `{history}` 作为 JSON 经 **stdin** 传入（不进命令行，无注入面），子进程把诊断结果以 JSON 写回 **stdout**。
   - 编码上有个 Windows 中文坑：subprocess 显式用 `encoding="utf-8"` 解码 Node 的输出，绝不能让它退回系统 locale（GBK）去解，否则中文 trace 会乱码。
   - 子进程**首轮无历史**直接返回空 findings——没有失败信号就没有可反思的东西，保持管线能跑通而不是报错。
   - 有历史时，`reflect-fanout.js` 组装一段 prompt 喂给**真 Claude**（经 `_claude_launch` 的 `launchClaude`，模型 `sonnet`，只放开 `WebSearch` 工具）。prompt 里把这个反思者定位成"独立多 agent 反思中的第 #idx 号"，明确要求：历史是只读证据、**此刻不准提代码、只准诊断**、要具体并引用真实失败、最多给 0–5 条 findings、只返回 `{"findings":[...]}` 这样的纯 JSON。
   - 任何失败都**降级为空 findings**而非抛错：Claude 启动失败、返回非预期内容、JSON 解析不出来——都让这一个反思者安静地交白卷，绝不让单个反思者的故障拖垮整个 fanout。这是 fanout 的容错设计：N 选其有效的即可。

3. **meta 去重（`meta_aggregate`）**：把 N 份反思的 findings 平铺成一条流，用一个 `seen` 集合做**保序去重**——按出现顺序保留首次见到的每条 finding，重复的丢掉。产出 `{"merged_findings": [...], "n_reflectors": N}`。

4. **交接给 propose**：在状态机里，`merged_findings`（一个字符串列表）被包进统一的 reflection dict——`refs = [{"merged_findings": [...]}]`——传给 propose，由真 Claude proposer 从中提取并落成具体改动。若 `merged_findings` 为空（首轮/无历史），则**退回串行静态审查** `reflect(sandbox_root, history, n=1)`，至少给 proposer 一点上下文，不让它空手上阵。

### serial 模式（脚手架）

`reflect()` 函数是早期串行实现，`parallel` 模式在无历史时也会借用它兜底：

- **有历史**：取 `history[-1]`，产出 `{"target_failure": <上轮 summary>, "round": <轮次>}`。
- **无历史（首轮）**：glob 出 sandbox 里所有非 `test_` 开头的 `.py` 源文件，产出 `{"static_review": "...", "files": [...]}` 作为静态审查起点。

它确定、不调模型，是 N=1 的退化形态。

## 契约

### `run_reflections_parallel(run_dir, history, n_reflectors=3) -> list[dict]`

| 项 | 类型 | 说明 |
|---|---|---|
| in `run_dir` | str | 本轮运行目录；仅作契约占位下传给子进程，**反思阶段不写它**。 |
| in `history` | list[dict] | 历史 trace（只读）；内部对每个反思者各拷贝一份。 |
| in `n_reflectors` | int | 并行反思数，默认 3。 |
| out | list[dict] | N 份反思，每份形如 `{"reflector": <idx>, "findings": [<str>, ...]}`。 |

### `meta_aggregate(reflections) -> dict`

| 项 | 类型 | 说明 |
|---|---|---|
| in `reflections` | list[dict] | `run_reflections_parallel` 的输出。 |
| out | dict | `{"merged_findings": [<str>, ...], "n_reflectors": <int>}`，findings 保序去重。 |

### `reflect-fanout.js` 子进程接口

- **args**：`--run <dir> --idx <n>`
- **stdin**：`{"history": [...]}`（JSON，只读）
- **stdout**：`{"reflector": <idx>, "findings": [<string>, ...]}`（JSON）
- **exit**：0 成功；非 0 失败（上游对应空 findings）

### 相邻模块接口

- **上游 `select_parent`（态2）**：选定本轮基版本后进入 reflect；reflect 不消费它的产物，只是时序上排在其后。
- **下游闸门 `check_reflection.check`（态3b）**：弱校验——reflection 非空且含 `target_failure`/`static_review`/`fix_content`/`files` 任一有意义字段即过；不过则记 `STATIC_REJECT` 并触发熔断检查。`check_benchtrace`（**trace 证据门**）是更强的接地校验：要求每条 finding 的 `trace_refs` 至少命中一个真实存在的 trace ID，按 `grounded_ratio >= threshold` 判过，并回报未接地的 findings。
- **下游 `propose`（态4）**：接收 reflection 列表（`parallel` 下即 `[{"merged_findings": [...]}]`），由 proposer 从 findings 生成具体改动。
- **`_claude_launch.launchClaude(extraArgs, promptText)`**：所有调 Claude 的接缝共用；`cc` 优先（走 split-billing 网关）、`claude` 兜底，返回 `{ok, result}`。

## 反自欺点

reflect 是诊断环节，它特有的自欺形态与对应闸门：

- **空洞反思冒充诊断**：返回"代码需要改进"这类无信息量的套话，看着像诊断其实啥也没说。→ 闸门：`check`（弱校验，必须含有意义字段）+ prompt 强约束"必须具体、引用真实失败"。
- **凭空捏造失败（幻觉接地）**：findings 引用了根本不存在的失败或 trace，诊断悬空。→ 闸门：**trace 证据门** `check_benchtrace`，每条 finding 必须能引到真实 trace ID，未接地的被点名，接地率不达标整轮判不过。
- **越界提前改码**：反思者忍不住直接给代码方案，侵蚀 propose 的职责、也容易绕过后续评测。→ 闸门：prompt 里硬性"此刻只准诊断、不准提代码"；职责切分由 propose 独占改动生成来兜。
- **伪独立（视角塌缩）**：N 个反思共享状态或互相偷看，结论高度雷同，"并行"名存实亡，去重后约等于 1 条。→ 闸门：各发历史快照拷贝 + 并发 spawn + 反思者间零通信，结构上保证独立。
- **污染历史证据**：反思时顺手往 trace 写东西，让后续轮次"看到"自己编的证据。→ 闸门：铁律 2，trace 全程只读，`run_dir` 仅作占位下传不写。

## 代码锚

- `tools/sie/reflect.py:reflect` — serial 模式（N=1，静态审查 / 读上轮失败摘要）
- `tools/sie/reflect.py:_reflect_one` — 单个独立反思者，spawn `reflect-fanout.js` 子进程
- `tools/sie/reflect.py:run_reflections_parallel` — N=3 并发 fanout，各发历史快照
- `tools/sie/reflect.py:meta_aggregate` — meta 保序去重合并 findings
- `workflows/reflect-fanout.js` — 单个反思 subagent（真 Claude，只读历史、只诊断）
- `workflows/_claude_launch.js:launchClaude` — 共享 Claude 启动器（cc 优先，claude 兜底）
- `tools/sie/check_reflection.py:check` — 态3b 弱校验闸门
- `tools/sie/check_reflection.py:check_benchtrace` — trace 证据门（findings 接地校验）
- `tools/sie/statemachine.py` (态3 REFLECT，约 L514–532) — pipeline 中调用 reflect 与去重、闸门过滤的位置
