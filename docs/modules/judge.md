# judge, 异质判官

## 职责

self-evolve 的方法论恒定为 reflect → propose → evaluate → judge → accept，全程反自欺。本模块是其中 **judge** 这一段：当评测对象没有现成的程序化真值（不像 A 策略那样有 pytest 通过/不通过），需要由模型给出主观打分时，judge 模块负责把这份主观信号生成出来，并立刻给它套上信任度的校验。

它在 pipeline 里的位置是 evaluate 之后、accept 之前的一个**信号 provider**：evaluate 已经从产物里抽出了"可核验跨度"（anchors，即一句话+一个可去核对的来源），judge 模块拿这些跨度去问两个不同来源的模型,Claude 和 Codex,"产物里和这些跨度绑定的论断，质量到底如何"。这是评测策略里靠主观判断打分的那一类（白话叫"判官评分"，在框架里属于评测信号 provider 的一种，权威清单见 `reference/signal-providers.md`），区别于另两类：一类靠跑测试拿确定真值，一类靠把论断对照外部来源做事实核对。三类是平行的信号来源，不是难度等级。

判官信号天生不可信,模型可能编、可能两个模型一起编（异质合谋）、可能打分跟真实核验脱节。所以本模块的真正职责不是"打分"，而是**给主观分配上信任闸**：用两判官的**配对一致性**（pairwise_agreement）检测它们是不是步调一致或异常合谋，用 **judge↔锚校准**（calibrate_judge_anchor）检测判官打的分跟独立人审/holdout 的真值到底相不相关。打分谁都会，本模块的价值在这两道闸。

## method

### 1. 异质：两个不同来源的判官，物理隔离

判官有两家，分别由独立子进程调用，与被评测的候选物理隔离（候选进程拿不到判官、也改不了判官的打分）：

- **Codex 判官**（`judge_codex.invoke_codex_judge`）：走 `workflows/codex-judge.js`，内部用当下最强的 codex 模型（具体型号 pin 在 `tools/sie/judge_codex.py` 的 `_CODEX_MODEL`/`_CODEX_EFFORT`，2026-07 = `gpt-5.6-sol` + `max`），**关掉 browser/playwright，只留 web_search**。
- **Claude 判官**（`judge_claude.invoke_claude_judge`）：走 `workflows/claude-judge.js`，同样**只开 web_search**。

两家用的是不同公司、不同训练的模型,这就是"异质"的含义。同质判官会犯一样的错、一起被同一个漂亮但空洞的产物骗过去；异质判官各自的盲区不一样，它们之间的**分歧**本身就是一个有用的信号。

两个适配函数行为完全镜像，且都**绝不抛异常**：超时、找不到 node、OSError、退出码非 0、输出为空,任何一种失败都降级成 `{"available": False, "raw": ""}`。这是关键设计：判官不可用是常态（限速、网络），不可用必须被显式表达成一个状态值往下传，让下游做"不可信处理"，而不是炸掉整条流水线，更不能被悄悄当成低分混进去。子进程统一用 `encoding="utf-8"` 解码（在 Windows 上不能让 locale 的 GBK 去解 UTF-8 输出）。

### 2. prompt 无真值（铁律 5）

`build_judge_prompt(artifact_text, spans)` 构造发给判官的提示词，它有一条不可变的铁律：**提示词里只能带跨度的文本本身，绝不能带任何真值字段**,不带 claim、不带 verified、不带 marginal_gain、不带 expected、不带 source_url、不带任何数值容差。

道理很直白：判官的工作是独立判断"这些论断好不好"，如果提示词里已经告诉它"这条已经核验为真、那条增益是 0.8"，判官就会照抄答案，校准就成了自己跟自己对。所以提示词里只放产物全文 + 一串纯文本跨度，外加指令："只给和可核验跨度绑定的论断打分；没有可核验跨度的论断给零分或负权重；不要奖励长度；返回 JSON `{"span_scores":[{"span":..., "score":0..1}]}`"。这条铁律由 `test_prompt_carries_no_truth` 守。

### 3. 打分与优雅降级

`score(artifact_path, anchors_visible, family)` 是单家判官的打分入口：读产物全文，从可见锚里抽 span 文本，构造提示词，按 `family`（"codex" / "claude"）路由到对应判官子进程。

判官返回的原始 JSON 由 `_parse_span_scores` 解析，同样**绝不抛**：解析失败或缺 `span_scores` 时返回空列表、aggregate=0.0，并把所有跨度都计入"未被打分而受罚"。只接受结构合法（含 span + 数值 score）的条目，aggregate 是这些有效分的均值。

这里有个反加水的细节：**未被判官打分的跨度不会被补默认分**。`unspanned_penalized` 记录"有多少跨度判官没给分"（`len(spans) - len(valid)`）。判官漏掉跨度 = 这些跨度拿不到信用，而不是被填一个中间值蒙混过去。

判官不可用时 `score` 直接返回 `available=False`、aggregate=0.0、所有跨度计罚。

### 4. 去偏

`debias_order(scores)` 做**位置去偏**：把 span_scores 按 span 文本升序重排，消除"呈现顺序影响打分"这种位置偏差，返回浅拷贝。**长度去偏**不在这里做数值缩放（缩放会引入新的偏差），而是委托给提示词,提示词里已经明写"不要奖励长度"。

### 5. 配对一致性（α）,异质合谋检测

`pairwise_agreement(scores_a, scores_b)` 是本模块第一道信任闸，算两家判官的一致程度，返回 α ∈ [0,1]：

1. **任一判官不可用 → 返回 None**。这是 None 哨兵，下游必须先判 None 再用值,绝不能把"判官不可用"误当成"真实的低一致性分"。
2. 两家打分各自先过 `debias_order`，再按 span 文本对齐。
3. 取两家**共同覆盖**的 span（内连接）；没有共同 span → 0.0。
4. α = 1 − MAD（平均绝对差）。分值都在 [0,1]，故 MAD ∈ [0,1]，α ∈ [0,1]。

α=1 是完全一致，α→0 是高度不一致。这个值的用法是**双向**的（在 acceptor 的 `alpha_gate` 里）：α 太低说明两判官打架、信号不可信，要人审；α 异常高**且锚没涨**则可疑,两个异质判官同时给出高分、可外部核验的锚却没改善，这正是异质合谋的形态，既要人审，还要记一次自欺。

一方有、另一方没有的跨度不纳入计算（保守处理）；共同覆盖少时 α 置信度低，下游可结合覆盖率再降权。

### 6. judge↔锚校准,判官跟真值相不相关

`calibrate_judge_anchor(judge_scores, holdout_anchors)` 是第二道信任闸，回答"判官打的分跟独立真值到底有没有关系"，用 Pearson 相关：

铁律：`holdout_anchors` 必须是**不进 e-process 计分的独立 holdout / 人审标注集**。如果把 visible（参与 e-process 计分的）锚传进来，判官和计分锚同源，相关性会虚高、合谋检测失效,隔离是调用方的责任。

算法：
1. 按 span 把判官分与 holdout 锚对齐（内连接）。
2. 对配对后的 holdout 子集调 `anchors.effective_independent_count` 做**同源去相关**,8 个来自同一来源（同 host + cik + period）的锚不算 8 个独立证据，按 `floor(1 + log2(簇内规模))` 次线性折算，得到有效独立锚数 indep。
3. 配对数 < 2 或 indep < 4（`_CALIB_MIN_INDEP`）→ `degenerate=True`，校准不可信。
4. 算判官分 vs holdout 的 verified（0/1）的 Pearson 相关；任一方差为 0 → `degenerate=True`。
5. 返回 `{"corr", "n_used", "degenerate"}`。

degenerate 的存在是核心：校准在样本太少或退化时**老实承认不可信**，而不是给一个看着漂亮的相关系数。

## 契约

### build_judge_prompt
- 入：`artifact_text: str`，`spans: list[str]`
- 出：`str`（提示词，只含产物全文 + 纯文本跨度，无任何真值字段）

### score
- 入：`artifact_path: str`，`anchors_visible: list[dict]`（只用 `span` 字段），`family: "codex"|"claude"`
- 出：
  ```
  {
    "family": str,
    "available": bool,
    "span_scores": [{"span": str, "score": float}, ...],
    "aggregate": float,            # 有效分均值，无则 0.0
    "unspanned_penalized": int,    # 判官未打分的跨度数，不补默认分
  }
  ```
- `family` 非法 → 抛 `ValueError`（唯一会抛的路径；判官不可用不抛，走 `available=False`）

### invoke_codex_judge / invoke_claude_judge
- 入：`prompt: str`，`timeout_s: int = 600`
- 出：成功 `{"available": True, "raw": stdout}`；任何失败 `{"available": False, "raw": ""}`（绝不抛）

### debias_order
- 入：`scores: dict`（含 span_scores）
- 出：浅拷贝，span_scores 按 span 文本升序

### pairwise_agreement
- 入：`scores_a: dict`，`scores_b: dict`（各为 score() 返回结构）
- 出：`float ∈ [0,1]`，或 `None`（任一判官不可用）

### calibrate_judge_anchor
- 入：`judge_scores: dict`，`holdout_anchors: list[dict]`（每项含 span / verified / source_url，与 anchors.py 同构；**必须独立 holdout**）
- 出：`{"corr": float, "n_used": int, "degenerate": bool}`

### 相邻模块接口

- **上游 evaluate**：`evaluate.inject_judge_scores(artifact_path, anchors_visible, holdout)` 是判官分进入评测系统的**唯一入口**（候选无法自报 judge 分）。它对同一产物分别调 `score(..., "codex")` 和 `score(..., "claude")`，调 `pairwise_agreement` 得 α，按"codex 优先、否则 claude、否则零分 degenerate"选主判官调 `calibrate_judge_anchor`，最后输出 `{codex, claude, alpha, calibration, judge_gain}`。
- **同源去相关依赖**：`calibrate_judge_anchor` 依赖 `anchors.effective_independent_count`。
- **下游 acceptor**：`acceptor.alpha_gate(alpha, anchor_up, params)` 消费 α,α=None 直接 `force_review=True`；α < `alpha_low`(0.4) 人审；α > `alpha_high`(0.85) 且锚不涨 → 人审 + 计自欺。`acceptor.judge_degrade(codex_available, claude_available)` 处理判官可用性,codex 不可用即禁止"单 Claude 自动 ACCEPT"，降级为程序化锚唯一裁决并升人审。
- **下游 selfdeception / statemachine**：当判官声称的增益高于锚的真实核验（`judge_gain > visible`，合谋方向），`selfdeception.index` 出 `judge_anchor_divergence` alert，statemachine 据此 `drift_count += 1`，累计触发漂移熔断停机人审。

## 反自欺点

本模块要防的是**主观打分被用来自我安慰**,这是 judge 段特有的自欺形态，对应的闸列在后面：

- **判官编造高分**：模型为了让产物"看起来好"而虚高打分。
  闸：判官不参与计分锚的核验（核验是 evaluate 干的事），判官分只能经 `inject_judge_scores` 单一入口进入、候选自报的任何 judge 字段被忽略；且 judge_gain 高于锚真值会触发 `judge_anchor_divergence`。

- **异质合谋**：两个判官同时给高分，制造"两家都认可"的假象。
  闸：`pairwise_agreement` 的 α 上向门,α 异常高且锚没涨，记自欺 + 人审。异质（不同公司模型）本身降低合谋概率，分歧被当信号而非噪声。

- **提示词泄真值导致自校准**：把真值喂给判官，判官照抄，校准失去意义。
  闸：铁律 5（`build_judge_prompt` 只带跨度文本），`test_prompt_carries_no_truth` 守。

- **校准同源虚高**：用参与计分的 visible 锚去校准判官，相关性虚高。
  闸：`calibrate_judge_anchor` 只接独立 holdout；`effective_independent_count` 对同源锚次线性折算；indep < 4 或方差为 0 → `degenerate=True` 老实认怂。

- **加水/补默认分**：给判官漏判的跨度填中间分蒙混。
  闸：`_parse_span_scores` 不补分，`unspanned_penalized` 显式记录漏判数。

- **不可用被当低分**：判官限速/故障时，若把空结果当成"真实的低一致性/低分"会误判。
  闸：判官失败一律 `available=False`，α 用 None 哨兵，下游 `alpha_gate`/`judge_degrade` 做不可信处理而非当真分。

## 代码锚

- `tools/sie/judges.py:build_judge_prompt`, 提示词构造（铁律 5：无真值）
- `tools/sie/judges.py:_parse_span_scores`, 解析判官输出 + 不补分降级
- `tools/sie/judges.py:score`, 单家判官打分入口 + 路由
- `tools/sie/judges.py:debias_order`, 位置去偏
- `tools/sie/judges.py:pairwise_agreement`, 配对一致性 α + None 哨兵
- `tools/sie/judges.py:calibrate_judge_anchor`, judge↔锚 Pearson 校准 + degenerate 闸
- `tools/sie/judge_codex.py:invoke_codex_judge`, Codex 判官子进程（只 web_search，绝不抛）
- `tools/sie/judge_claude.py:invoke_claude_judge`, Claude 判官子进程（镜像范式，绝不抛）
- `tools/sie/anchors.py:effective_independent_count`, 同源去相关（校准所依赖）
- `tools/sie/evaluate.py:inject_judge_scores`, 判官分进入评测的唯一入口（上游接线）
- `tools/sie/acceptor.py:alpha_gate`, α 双向门（下游消费）
- `tools/sie/acceptor.py:judge_degrade`, 判官不可用降级（下游消费）
