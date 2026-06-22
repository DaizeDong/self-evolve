# profile —— 探测信号源、装配 evaluator 组合、首次冻结

## 职责（含在 pipeline 的位置）

profile 是 self-evolve 状态机进入主循环前的**第二个状态**（紧跟 INIT 建沙箱之后）：

```
INIT(建 worktree) -> PROFILE -> [REFLECT -> CHECK -> PROPOSE -> PATCH -> EVALUATE -> ACCEPT|REJECT] * max_rounds
```

它做一件事：拿到一个**目标**（target，可能是个代码仓库，也可能是一份调研产物目录），
回答「这个目标能用哪些方式衡量改动好不好」，然后把答案**一次性冻结**成 `target.json`，
供后面每一轮 evaluate 反复读取。

这里要先说清楚框架里一个容易被代号误导的点（权威见 `docs/reference/signal-providers.md`）：

- self-evolve 的方法论本身是**恒定**的——永远是 reflect → propose → evaluate → judge → accept，全程反自欺。
- 代码里出现的 **A / B / C 不是"目标难度等级"，而是三种"用什么信号来判分"的评测策略 / 信号 provider**：
  - **A = 可执行信号**：跑测试，看红绿。
  - **B = 事实锚信号**：核对调研产物里的结构化事实是否经得起外部数据源验证。
  - **C = 兜底**：既没有能跑的测试、又没有足够的事实锚，只能退回到无回归 + 评审。

profile 的核心任务，就是**探测目标到底提供得起哪几路信号**，并把它们**装配成一个组合**
（而不是从 A/B/C 里挑一档）。一个目标完全可以**同时**提供可执行信号和事实锚信号，
此时它的组合就是 `"A+B"`——两路 evaluator 都会在后续轮次里并用。只有当两路都探测不到时，
才落到 `"C"`。

profile 还承担了一个反自欺的关键动作：在判定"A 路信号可用"之前，
**先用变异测试做二次校验**——故意往源码里注入一个必然失败的 bug，确认测试**真的会变红**。
如果注入 bug 后测试仍全绿，说明这套测试是个橡皮图章（grader 无效），那么 A 路信号就不予采信。

## method

### 1. 探测可执行信号（A 路）

入口 `run_profile` 先调 `_exec_signal(target, base_ref)`：

1. 用 `sandbox.make_worktree` 给目标在 `<target>/.sie/worktrees/profile_probe` 开一个 git worktree——
   探测在隔离副本里做，不碰目标本体。
2. 调 `probes/exec_probe.run_exec_probe(sandbox_root)`，返回三件套：
   `has_tests` / `exit_code` / `mutation_killed`。

`run_exec_probe` 内部是一条**三段闸门**，前一段不过后一段不做：

- **有没有测试**：用 glob 找 `test_*.py` 或 `*_test.py`。没有 → 直接返回，A 路不成立。
- **基线红绿**：`pytest -q --no-header` 跑一遍（60 秒超时，超时按失败算）。
  退出码必须是 `0` 才有资格继续。退出码 `5`（一个测试都没收集到）和 `1`（有失败）都**不算**有效 grader——
  尤其退出码 5 是个常见陷阱：有"测试文件"不等于真有可跑的测试。
- **变异二次校验**：从源码里挑一个文件（排除 `test_*` / `__init__.py` / `setup.py` / `conftest.py`，
  排序后取第一个，保证确定性），往**文件尾部追加** `raise RuntimeError('SIE_MUTANT')`，
  重跑测试。期望退出码非 0（mutant 被"杀死"）。跑完无论成败都用 `try/finally` 把源文件**还原**回原始内容。
  - `mutation_killed == True` → 这套测试对真实缺陷有杀伤力，grader 可信。
  - `mutation_killed == False` → 注入了必然炸的 bug 测试居然还全绿 → 这套测试是装饰品，A 路信号作废。

只有 **`has_tests` 且 `exit_code == 0` 且 `mutation_killed`** 三者同时为真，才把 `"A"` 加进 `tiers` 集合。
注意 `_exec_signal` 对任何异常（目标不是 git 仓库、git 命令失败等）都**吞掉返回 None**——
这是有意的优雅降级：不是所有目标都是仓库，探不到 A 路不应该让整个 profile 崩。

### 2. 探测事实锚信号（B 路）

调 `probes/fact_probe.probe(target, base_ref)`。它的反自欺立场是：**不信 prose 自称**。
一份调研产物在 docstring 或正文里写得再漂亮，都不给信号；只认**代码可判定的结构化锚**。

判定流程：

1. `_find_artifacts` 收集产物 JSON（target 是文件则取该 `.json`；是目录则递归 glob 所有 `.json`，排序保确定性）。
2. 对每个文件调 `anchors.extract_anchors`，抽出真正合格的锚。
   一个锚要合格，必须**同时**带齐三件套字段且非空：`claim`（断言）、`span`（原文片段）、`source_url`（来源）。
   缺任何一件就不算锚——这是用代码堵死"塑造 docstring 放水刷信号"的口子。抽取时还按 `anchor_id`（三件套的 sha256）去重。
3. 合格锚总数 `>= anchor_set_min`（当前 = **24**）才给出 `tier_signal == "B"`，否则为 `None`。

只要给出 B 信号，`run_profile` 就把 `"B"` 加进 `tiers`，并做后面的 visible/holdout 拆分。

### 3. visible / holdout 拆分（B 路专属，反作弊隔离）

事实锚一旦全公开给 proposer，它就能"对着答案改"。所以 profile 把锚集切成两半：

- 用 `anchors.split_visible_holdout(all_anchors, frac=0.3, seed=...)` 做**确定性**拆分——
  seed 取 `run_dir` 的 basename（没有 run_dir 时退回 `base_ref`），
  对每个锚算 `sha256(seed | anchor_id)` 排序，前 30% 进 holdout。
  确定性的意义：同一批锚 + 同一 seed 永远切出同一个 holdout，
  proposer 没法靠"反复重试碰运气"刷过隐藏集。
- **visible 锚**写进 `target.json` 的 `anchors_visible`，供后续 evaluate 计分。
- **holdout 锚的真值**被**物理隔离**到一个独立目录的文件里：
  有 run_dir 时落 `<run_dir>/_holdout/holdout.json`，否则落 `<target>/_run/_holdout/holdout.json`。
- `target.json` 里**只存一个指针** `anchors_holdout_ref = {path, count, ref: "isolated"}`——
  **绝不存 holdout 真值本身**。proposer 读 `target.json` 永远看不到隐藏答案。

### 4. 装配组合 + 算分 + 冻结

- **组合**：`tier_str = "+".join(sorted(tiers))`，集合为空则 `"C"`。
  所以可能取值是 `"A"`、`"B"`、`"A+B"`、`"C"`——再次强调这是 evaluator 组合，不是难度档。
- **可验证分**：`verifiability_score = 1.0 if "A" in tiers else 0.0`（有可执行信号才算"可验证"）。
- **冻结**：如果传了 `run_dir`，`run_profile` 末尾自动调 `freeze_target` 把整个 prof 写进 `target.json`。
  `freeze_target` 用 `临时文件 + os.replace` **原子写**，避免半截文件。
- **首次冻结、resume 不重跑**：这是铁律。状态机里 PROFILE 态先看 `target.json` 在不在——
  在就 `load_target` 直接读回（resume 不重新探测），不在才 `run_profile` + 冻结。
  tier 一旦定下整轮 run 不变，杜绝"中途换评测口径"的自欺。

## 契约

### 输入

| 参数 | 类型 | 说明 |
|---|---|---|
| `target` | `str` | 目标仓库路径，或调研产物目录/文件路径 |
| `base_ref` | `str` | git 基线引用，给 exec 探针开 worktree 用 |
| `run_dir` | `str \| None` | 给了就自动冻结 `target.json`；不给只返回 prof 不落盘 |

### 输出（prof dict / `target.json` schema）

```jsonc
{
  "tier": "A+B",                       // evaluator 组合: "A"|"B"|"A+B"|"C"
  "verifiability_score": 1.0,          // "A" in tiers ? 1.0 : 0.0
  "anchors_visible": [ /* 锚 dict 列表, 含 anchor_id/claim/span/source_url/... */ ],
  "anchors_holdout_ref": {             // 只有指针, 绝无真值
    "path": "<run_dir>/_holdout/holdout.json",
    "count": 7,
    "ref": "isolated"
  },
  "probe_evidence": {
    "fact": { "scanned_files": [...], "anchor_set_min": 24 },
    "anchor_count": 31
  },
  "probes": { "exec": { "has_tests": true, "exit_code": 0, "mutation_killed": true } },
  "base_ref": "<base_ref>",
  "visible": [],                       // 旧字段, 向后兼容保留, 现为空
  "holdout": []                        // 旧字段, 向后兼容保留, 现为空
}
```

单个锚的 schema（`anchors.extract_anchors` 产出）：
`anchor_id`（三件套 sha256 前 16 位）、`claim`、`span`、`source_url`、`metric`、`expected`、
`cik`、`period`、`fetched_at`(=None)、`verified`(=False)、`marginal_gain`(=0.0)。

### 相邻模块接口

- **上游 `sandbox.make_worktree(target, base_ref, run_id)`**：给探针开隔离 worktree（idempotent，已存在直接返回）。
- **上游 `probes/exec_probe.run_exec_probe(sandbox_root)`**：产 A 路三件套信号。
- **上游 `probes/fact_probe.probe(target, base_ref)`**：产 B 路 `{tier_signal, anchor_count, verifiable_coverage, evidence}`。
- **上游 `anchors.extract_anchors / split_visible_holdout`**：抽锚 + 确定性拆隐藏集。
- **下游 `statemachine`（PROFILE 态）**：调 `run_profile`/`load_target`/`freeze_target`，把 `prof["tier"]` 写进事件流。
- **下游 `evaluate`**：每轮读 `target.json`——A 路读 `probes.exec` 决定跑测试，
  B 路读 `anchors_visible` 喂 `build_btier_scores` / `_evaluate_btier`，
  并按 `anchors_holdout_ref.path` 在评测末尾核 holdout 增益。

## 反自欺点

profile 是反自欺的第一道关，本模块自身也有特有的自欺形态，每种都配了对应闸门：

| 自欺形态 | 表现 | 对应闸门 |
|---|---|---|
| **橡皮图章测试** | 目标自带的测试永远绿，根本测不出真缺陷，A 路"看着可验证"实则没杀伤力 | 变异二次校验：注入 `SIE_MUTANT` 必炸 bug，测试不变红就**不采信 A 路**（`exec_probe.run_exec_probe`） |
| **空壳测试目录** | 有 `test_*.py` 文件但收集不到用例（退出码 5），冒充"有测试" | 基线必须退出码 `==0` 才进变异环节；5/1 一律不算有效 grader |
| **prose 放水刷锚** | 在 docstring / 正文写满"已核实""有来源"等自称，骗 B 路信号 | 只认带齐 `claim+span+source_url` 三件套的**结构化**锚，缺字段不计数（`anchors.extract_anchors`） |
| **对着答案改** | proposer 拿到全部事实锚后照着改，evaluate 失去鉴别力 | holdout 真值**物理隔离**到独立文件，`target.json` 只存指针，proposer 读不到（铁律5） |
| **重试碰运气过隐藏集** | 反复重跑，赌某次 holdout 拆分对自己有利 | holdout 拆分**确定性**（seed = run_dir basename），同输入恒切同一隐藏集（`anchors.split_visible_holdout`） |
| **中途换评测口径** | run 跑到一半改 tier，让难判的改动"换个尺子"显得通过 | tier **首次 PROFILE 冻结**、resume 只 `load_target` 不重跑（铁律4，`freeze_target` 原子写） |

## 代码锚

- `tools/sie/profile.py:run_profile` —— 探测 A/B 信号、装配 tier 组合、拆 visible/holdout、隔离 holdout、自动冻结
- `tools/sie/profile.py:_exec_signal` —— 开 worktree + 跑 exec 探针，异常吞掉降级为 None
- `tools/sie/profile.py:freeze_target` —— 原子写 `target.json`（铁律4 首次冻结）
- `tools/sie/profile.py:load_target` —— resume 读回冻结结果，不重新探测
- `tools/sie/probes/exec_probe.py:run_exec_probe` —— A 路三段闸门 + 变异二次校验
- `tools/sie/probes/exec_probe.py:_run_pytest` / `_pick_src` / `_has_tests` —— 跑测试 / 选注入源文件 / 探测试存在
- `tools/sie/probes/fact_probe.py:probe` —— B 路结构化锚计数（阈值 24）
- `tools/sie/probes/fact_probe.py:_find_artifacts` —— 定位产物 JSON
- `tools/sie/anchors.py:extract_anchors` —— 三件套合格锚抽取 + 去重
- `tools/sie/anchors.py:split_visible_holdout` —— 确定性 visible/holdout 拆分
- `tools/sie/sandbox.py:make_worktree` —— 给探针开隔离 git worktree
- `tools/sie/statemachine.py`（PROFILE 态，约 483–496 行）—— pipeline 中调度 profile + 冻结/resume
