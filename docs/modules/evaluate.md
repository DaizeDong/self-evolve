# evaluate — 信号枢纽

## 职责

evaluate 是 self-evolve 闭环里 `reflect → propose → **evaluate** → judge → accept` 的第三段。它的任务只有一句话：**把一份候选改动变成一串可比的 (before, after) 配对，交给 acceptor 去裁决**。

它本身不做"接不接受"的决定——那是 acceptor 的事；它也不凭空给候选打主观分——那是 judge 进程的事。evaluate 是中间的**信号枢纽**：

- 按当前任务的 **profile** 选一个**信号 provider**（可验证执行 / 事实锚 / 兜底场景）；
- 用这个 provider 把"改动有没有变好"量化成统一格式的 **paired 配对**；
- 同时算出一个 **coverage**（覆盖度），其含义随 provider 而变，供下游门控和反自欺使用。

下游 acceptor 不关心配对是怎么来的——无论来自 pytest、EDGAR 核验还是回放，都长成同一种 `[(before, after), ...]`，acceptor 一律用 e-process 鞅去判。这就是"信号枢纽"的价值：**把异构的证据收口成同构的接口**。

> 关于 A/B/C：本文里的 A/B/C 是**评测策略 / 信号 provider 的代号**，不是"任务难度等级"也不是"目标分级"。A=有客观执行结果可验证（跑测试拿通过/失败），B=有外部事实可逐条核验（财报数字对不对），C=两者都没有的兜底（只能保证不退化 + 自洽）。权威定义见 `reference/signal-providers.md`。

## method

evaluate 对外只暴露三个入口函数（`evaluate.py`），靠**第一个参数的类型**来分流到不同 provider。

### A 路：可验证执行 provider

入口是 `evaluate(sandbox_root: str, tier="A", base_result=None)`，第一个参数是字符串路径时走这条。

它在**沙箱子进程**里跑 pytest，把每个测试项的通过/失败映射成 0/1 分，再和父代基线对齐成逐任务配对：

1. `_grade_pytest_per_task(sandbox_root)` 跑 `pytest -v --tb=no --no-header`，用 `_parse_per_test` 逐行解析输出。映射规则很关键：
   - `PASSED` / `XPASS`（意外通过，说明修复让一个预期失败的测试过了）→ **1.0**；
   - `FAILED` / `ERROR` / `XFAIL`（仍在失败）→ **0.0**。
   - 解析不出逐项行时退回整体一档：退出码 0 → 1.0，否则 0.0。
   - 注意 `task_passed` 用的是**退出码**，不是逐项分之和——因为有 XFAIL 时退出码可能为 0 但逐项分为 0，两者口径有意分开。
2. 配对构建：
   - 有 `base_result`（父代逐项分）时，**按测试顺序逐项对齐**取 `(base_score, after_score)`，长度不齐则多出来的 after 项配 0.0 基线；
   - 没有 base_result（冷启动）时，所有 before 一律 0.0（视作"全失败基线"）；
   - 实在一对都凑不出来，兜一个聚合单配对。
3. coverage 取 `verifiable_coverage`，A 路恒为 **1.0**——因为执行结果是完全可验证的，没有"没核到"的灰色地带。

A 路的隔离由 `verifiable.py` 提供，这是它最不显眼但最要命的部分：

- `minimal_env()`：白名单环境变量（只留 PATH/SYSTEMROOT 等必需项），凡名字含 `TOKEN/KEY/SECRET/ANTHROPIC/OPENAI/DISCORD` 等标记的变量一律剔除；注入 `SIE_NO_NETWORK=1`；把 `HOME`/`USERPROFILE` 指向一个新建的**空临时目录**，让候选代码里的 `expanduser("~")` 落到空牢笼，够不到 `~/.credentials.json`。
- `_grader_env()` 往子进程的 `PYTHONPATH` 最前面塞一个临时 `sitecustomize.py`（`_SITE` 字符串），它在任何候选代码运行**之前**就：把 `socket.create_connection` 换成抛错函数、把 `socket.socket` 换成连接即抛错的子类（先强制 import ssl 再换，保住 `SSLSocket` 继承链），并 hook `__import__` 禁止 import `discord_relay`/`discord` 防外泄。这就是"M1 no-network gate"。

`grade_pytest()` 是 A 路的聚合版（整体 0/1，给 profiler 做基线检查用）；`_grade_pytest_per_task` 是逐项版（给 evaluate 产配对用）。

`verifiable.py` 还附带两块给"测评质量"兜底的工具：

- `snapshot_hash(sandbox_root)`：对评测树内容做确定性 SHA-256（排序遍历、排除 `.git`/`__pycache__`/`.sie`），用于证明评测对象没被偷换。
- 变异测试 `inject_mutants` + `mutation_validity_gate`：往源码里注入单点变异（`+`↔`-`、比较符翻转、`True`↔`False`），看测试套能不能"杀掉"这些 bug。杀不掉的变异（survivor）说明 grader 太弱——这是防"测试是摆设"型自欺的闸门，要求默认 kill_ratio=1.0 才算 valid。

### B 路：事实锚 provider

入口是 `evaluate(round_ctx: dict)` 且 dict 的 `tier` 含 "B" 时，分流到 `_evaluate_btier(ctx)`。

B 路面对的是"研报型"产物：里面有一条条事实声明（claim），每条带一个文本片段 span、来源 URL、以及要核的财务指标。**信号 = 每条锚是否经外部真值核验通过**。

`_evaluate_btier` 做三件事：

1. **逐锚边际增益配对**。先 `_verify_visible` 把还没核验的锚送 `anchors.verify_anchor` 核一遍。然后对每条锚算两个边际增益（`anchors.marginal_gain`，下文契约详述）：
   - `bg` = 不带本提案时该锚的增益（基于 baseline 核验分）；
   - `wg` = 带本提案时该锚的增益（基于 candidate 核验分）；
   - 配对 `(bg, wg)` 进 `b_paired`；`wg - bg` 累计算 `visible_anchor_gain`（所有锚均值，未核验锚贡献 0）。
2. **coverage 门**。`coverage = anchors.coverage(vis)` = 已核验 span 字符数 / 总 span 字符数。低于 `coverage_floor`（默认 0.5）即"覆盖不足"。这里有一个 spec 门控：如果 ctx 给了 `intended_accept`，则 `coverage_floor_violation` 只在**覆盖不足 且 acceptor 打算接受**时才为真（避免对一个本就要拒的候选额外报违规）；没给 `intended_accept` 时退回原始信号（仅看覆盖是否不足），留给状态机后续用 acceptor 决策再门控一次。
3. **holdout 抽检**。每 K 轮（`round % K == 0`，默认 K=5）算一次 `holdout_gain = max(0, holdout_with - holdout_base)`，非抽检轮为 None。holdout 是从锚集里**确定性切出、平时不参与评分**的一份留出集（切分见 `anchors.split_visible_holdout`），它的作用是抓"只对可见锚过拟合"——可见锚涨了但留出集不涨，就是过拟合信号，喂给反自欺。

构造 B 路 ctx 的辅助函数是 `build_btier_scores`：它拿"baseline 冻结的可见锚集"和"候选改后的锚"，用 `(cik, metric, period)` 这个**跨编辑稳定的键**做匹配（不能用 anchor_id，因为 proposer 改正一个错值会改 claim，进而改 id）。匹配上后两边都真核验，产出喂给 `_evaluate_btier` 的 `anchors_visible` / `base_scores` / `with_scores`。两条保守原则：候选**删掉**的锚不计（不奖励删锚），候选修正了某个错锚则 base=0/with=1 计正增益。

事实核验本身在 `anchors.verify_anchor`：默认走 edgartools 取 `cik/period` 下的 `metric` 数值，和锚里的 `expected` 比（`_within_tol`：|expected|≥1 用 1% 相对容差，否则用绝对容差兜近零值）。取不到数 / 没配 identity / 任何异常 → 一律 `verified=False`——**绝不把"取不到"当成"对"**。

防相关锚刷分由 `anchors.effective_independent_count` 负责：按 `(host, cik, period)` 同源聚类，每簇只折算 `floor(1 + log2(簇大小))` 条有效独立锚（8 条同源只算 4 条），这个数被 acceptor 的 B 档门用作"有效独立锚下限"。

### C 路：兜底场景 provider

A、B 都不适用时（既无可执行测试、又无可核外部事实），走 `evaluate_c_tier`。它只给两道极弱的信号：

- `no_regression`：把历史成功任务回放，任一 `before=True 且 after=False`（曾经过、现在挂）→ False，这是**硬门**（委托 `acceptor.c_tier_no_regression`）。
- `consistency_paired`：调用方提供的内部自洽配对，原样透传。
- `coverage` 恒 **0.0**——C 路没有可验证锚，覆盖度本就为零。

C 路在 acceptor 里权重极低（`c_tier_weight=0.05`），绝不单独触发 ACCEPT，且 coverage=0 会强制人审。

### judge 主观分的唯一入口

`inject_judge_scores(artifact_path, anchors_visible, holdout)` 是 judge 主观分进入评测系统的**唯一合法入口**（spec §8）。设计要点：**候选不能自报 judge 分**——产物里任何 judge 字段都被忽略。judge 由 harness 在 evaluate 之外独立调用联网进程（codex / claude）：

- `judges.score(...)` 分别拿 codex、claude 两家打分；
- `judges.pairwise_agreement(codex, claude)` 算两家一致度 alpha（任一家不可用 → None，交给下游 `alpha_gate` 处理）；
- 主 judge 取 codex（不可用退 claude，双不可用退 0 分 degenerate），`calibrate_judge_anchor` 用 holdout 校准 judge 与锚是否对得上；
- 返回 `judge_gain`（主 judge 聚合分）、`alpha`、`calibration`。

alpha 是反"两家 judge 合谋"的关键量：异常高但锚不涨，会被 `acceptor.alpha_gate` 判为合谋并计自欺。

## 契约

### A 路 I/O

输入：`evaluate(sandbox_root: str, tier="A", base_result: dict|None)`，`base_result` 形如 `{"dimensions": [{"score": float, ...}, ...]}`（父代逐项分）。

输出：
```
{
  "result": {                          # grade_pytest 风格 A-grade 契约
    "task_passed": bool,
    "grader_exit_code": int,
    "dimensions": [{"name": str, "tier": "A", "score": 0.0|1.0, "weight": 1.0}, ...],
    "anchors": [],
    "verifiable_coverage": 1.0,
  },
  "paired": [(before: float, after: float), ...],   # 逐任务配对，喂 acceptor
  "coverage": float,                                 # A 路恒 1.0
}
```

### B 路 I/O

输入：`evaluate(ctx: dict)`，ctx 关键键：`tier`（含 "B"）、`round`、`K`(默认5)、`coverage_floor`(默认0.5)、`anchors_visible`、`base_scores`(anchor_id→分)、`with_scores`(anchor_id→分)、`holdout_base`/`holdout_with`(可选)、`intended_accept`(可选 bool|None)、`fetcher`(可选，测试注入)。

输出：
```
{
  "tier": "B",
  "b_paired": [(bg: float, wg: float), ...],   # 逐锚零均值化配对，喂 acceptor
  "visible_anchor_gain": float,                 # mean(wg - bg)
  "holdout_gain": float | None,                 # 非抽检轮 None；抽检轮 max(0, hw-hb)
  "coverage": float,                            # 已核验 span / 总 span
  "coverage_floor_violation": bool,             # 覆盖不足(可选叠加 accept 意图门控)
  "anchors_visible_verified": [...],            # 核验后的锚列表
}
```

### C 路 I/O

输入：`evaluate_c_tier(artifact_path: str, regression_replay: list[dict], internal_consistency: list[tuple])`，`regression_replay` 元素 `{"task": str, "before": bool, "after": bool}`。

输出：`{"no_regression": bool, "consistency_paired": list[tuple], "coverage": 0.0}`。

### judge 注入 I/O

输入：`inject_judge_scores(artifact_path: str, anchors_visible: list[dict], holdout: list[dict])`。

输出：`{"codex": dict, "claude": dict, "alpha": float|None, "calibration": dict, "judge_gain": float}`。

### 相邻模块接口

**上游 propose / profiler**：给 evaluate 喂 `sandbox_root`（A 路）或装好锚分的 ctx（B 路）。A 路的父代基线 `base_result` 由 profiler 用 `grade_pytest` 同口径生成（保证 before/after 同标尺）。

**下游 acceptor（`acceptor.decide(paired, tier, st, params)`）**：吃 evaluate 吐出的 `paired`（A 路）/ `b_paired`（B 路）/ `consistency_paired`（C 路），跑 e-process 鞅返回 `{"decision": "ACCEPT"|"REJECT"|"CONTINUE", "evalue": float, ...}`。注意各档配对语义不同，acceptor 内部分档处理：
- A 档：配对是 0/1 二态分，acceptor 额外跑 no-regression 硬门（任一 b≥1>a 即 pass→fail 退化 → 硬 REJECT），二态裁决禁 CONTINUE；
- B 档：配对是 [-1,1] 边际增益浮点，acceptor 用锚数下限 `n_min`、有效独立锚下限（用本模块 `effective_independent_count`）、evalue 总量钳三道门，允许 CONTINUE 累积证据；
- C 档：配对极低权重缩放，绝不单独 ACCEPT，coverage=0 强制人审。

**judge 进程（`judges.*`）**：在 evaluate 之外独立联网；evaluate 仅通过 `inject_judge_scores` 这一入口收口其结果，候选无法干预。

**反自欺消费者**：`coverage` / `coverage_floor_violation` / `holdout_gain` / `alpha` 这几个量是反自欺闸门的输入（见下节）。

## 反自欺点

evaluate 是信号入口，正是各种"刷分"想钻的地方。本模块对应的自欺形态与闸门：

- **塞假锚刷分**（编一堆没核验的"锚"充数）→ `marginal_gain` 对 `verified=False` 的锚**恒返回 0**；`coverage` 只统计已核验 span。假锚既不加增益也不加覆盖。
- **把"取不到数"当"对"**（核验失败默默算通过）→ `verify_anchor` 任何 fetch 失败 / 缺 observed/expected → 一律 `verified=False`。绝不把不可用数据当真值。
- **堆同源相关锚虚高证据**（同一份财报拆 8 条锚冒充 8 个独立证据）→ `effective_independent_count` 按同源簇 `floor(1+log2(size))` 折算，喂 acceptor 的有效独立锚下限门。
- **只对可见锚过拟合**（专门把评分用到的可见锚做漂亮，泛化为零）→ 每 K 轮 `holdout_gain` 抽检留出集；可见涨而留出不涨即过拟合信号，喂反自欺。
- **覆盖太低就蒙混接受**（只核一小撮锚就想过）→ coverage 门：低于 `coverage_floor` 报 `coverage_floor_violation`；C 路 coverage=0 在 acceptor 端强制人审。
- **候选自报 judge 主观分 / 两家 judge 合谋**→ judge 分只能经 `inject_judge_scores` 由 harness 独立联网产出，候选自报字段被忽略；两家一致度 `alpha` 异常高但锚不涨 → `acceptor.alpha_gate` 判合谋并计自欺。
- **测试是摆设 / 偷换评测对象**（grader 太弱抓不到 bug，或评测时换了一套树）→ `mutation_validity_gate` 注入变异验证测试真能杀 bug（survivor 即弱 grader）；`snapshot_hash` 锁定评测树内容确定性哈希。
- **候选代码联网外泄 / 偷读密钥**（评测时偷连网、读 `~/.credentials.json`）→ A 路 `minimal_env` 剥密钥 + jail HOME，`_SITE` sitecustomize 在候选代码前封 socket/SSL + 禁 import discord_relay。

## 代码锚

- `tools/sie/evaluate.py:evaluate` — 三路总分流入口（按首参类型/tier 分流）
- `tools/sie/evaluate.py:_grade_pytest_per_task` — A 路逐测试项跑分
- `tools/sie/evaluate.py:_parse_per_test` — A 路 pytest 输出逐项解析（PASSED/XPASS→1，FAILED/ERROR/XFAIL→0）
- `tools/sie/evaluate.py:_evaluate_btier` — B 路编排（逐锚配对 + coverage 门 + holdout 抽检）
- `tools/sie/evaluate.py:build_btier_scores` — B 路 baseline↔candidate 锚匹配与计分构造
- `tools/sie/evaluate.py:_verify_visible` — B 路可见锚补核验
- `tools/sie/evaluate.py:_btier_match_key` — 跨编辑稳定的锚匹配键 (cik,metric,period)
- `tools/sie/evaluate.py:evaluate_c_tier` — C 路兜底评测（no_regression + 自洽配对）
- `tools/sie/evaluate.py:inject_judge_scores` — judge 主观分唯一合法入口
- `tools/sie/verifiable.py:grade_pytest` — A-grade 整体跑分（沙箱子进程）
- `tools/sie/verifiable.py:minimal_env` — 剥密钥 + jail HOME + 无网环境
- `tools/sie/verifiable.py:_grader_env` — 注入 sitecustomize 网络封锁的子进程 env
- `tools/sie/verifiable.py:snapshot_hash` — 评测树确定性 SHA-256
- `tools/sie/verifiable.py:inject_mutants` — 单点变异注入
- `tools/sie/verifiable.py:mutation_validity_gate` — 变异杀伤率闸门（防弱 grader）
- `tools/sie/anchors.py:verify_anchor` — 单锚外部真值核验（取不到即 unverified）
- `tools/sie/anchors.py:coverage` — 已核验 span / 总 span
- `tools/sie/anchors.py:marginal_gain` — EVE 边际增益（未核验锚恒 0）
- `tools/sie/anchors.py:effective_independent_count` — 同源聚类折算有效独立锚数
- `tools/sie/anchors.py:split_visible_holdout` — 确定性 visible/holdout 切分
- `tools/sie/acceptor.py:decide` — 下游裁决（消费 paired，分档 e-process）
- `tools/sie/acceptor.py:c_tier_no_regression` — C 路 no-regression 硬门
- `tools/sie/acceptor.py:alpha_gate` — judge 一致度双向门（防合谋）
- `tools/sie/judges.py:score` / `pairwise_agreement` / `calibrate_judge_anchor` — judge 联网打分与校准
