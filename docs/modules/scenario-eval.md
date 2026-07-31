# scenario-eval 设计目标（生成评测 · 普适性承重墙）

> **状态：设计目标，尚未实现。本文档描述的是要建成什么，不是现在的行为。**
>
> 当前代码库里没有任何 scenario 实现：`tools/` 与 `tests/` 中不存在场景生成、rubric、
> 场景 coverage 的代码或测试。今天纯主观 C 走的是保守路径,`evaluate_c_tier` 里
> `coverage` 恒 `0.0`、`c_tier_weight=0.05`、`mode=auto` 下强制人审，见
> [`../../reference/signal-providers.md`](../../reference/signal-providers.md) 的
> 「当前实现 vs scenario-eval 目标」注。落地排期见
> [`../../ROADMAP.md`](../../ROADMAP.md) 的 Planned 第一条。
>
> 以下各节一律为**目标态**描述。读到「场景由独立 agent 生成」「coverage 按意图行为面计」
> 之类的陈述句时，请读作「建成后应当如此」，而非「现在如此」。

## 目标职责

目标无 exec 信号（A）、无 external-fact 锚（B）时**自造评测信号**：生成评测场景 + rubric，
交异质判官盲评，输出与 A/B **同形**的 `paired` 喂给同一 acceptor。让 `evaluate` 契约对任何
目标可满足,这是「没有不可用目标」在工程上的兑现。

pipeline 位置：EVALUATE 步的第三个 provider（前两者取不到时）。是 C 档的真正实现方式，
把「纯主观打分」升级为「可主动构造、可量化、可回归」的信号通道。

## 目标 method（四步数据流）

1. **SCENARIO-GEN**, 从目标声明意图（skill 描述 / README / 用例）派生场景集 S，多样性约束
   覆盖 happy-path / edge / 失败模式 / 反例。场景由**独立 agent 生成，proposer 不可见**；
   首次 PROFILE 部分冻结为 visible scenarios，另留 **holdout scenarios 隔离到 `_holdout/`**。
2. **RUBRIC**, 每场景配可判定 rubric（pass 条件 / 维度 / 权重），把主观质量降维成逐条
   二元 / 分档判定（抗 game 第一层：判的是「是否满足明确条件」而非「感觉好不好」）。
3. **COVERAGE**, `coverage := 场景触达的目标行为面 / 声明行为面`。**这是给 C 一个真
   coverage（替换纯主观时的恒 0.0）**：不是代码覆盖率，是「场景对意图的覆盖率」；
   `< floor → coverage_floor_violation`（与 B 同闸）。
4. **HETERO-JUDGE**, 对每 (candidate, scenario) 跑 Claude+Codex，prompt 仅含 scenario+rubric、
   **零真值**；逐 rubric 项打分 → scenario_score → before/after 配对成 `paired` →
   交 `acceptor.decide(paired, ...)`（与 A/B 完全同形）。

## 目标契约

- 输入：目标意图来源（描述 / README / 用例）、profile 冻结的 visible/holdout 场景集。
- 输出：`paired`（与 A/B 同形）、`coverage`（场景对意图的覆盖率）、`alpha`/`calibration`
  （判官一致性）、`holdout_gain`（每 K 轮抽检）。
- 场景 schema（见 [`../../reference/target_contract.md`](../../reference/target_contract.md)）：
  `scenarios:[{id, rubric, visible|holdout}]`。
- 相邻接口：PROFILE 决定启用本 provider 并冻结场景；JUDGE/accept 用同一 acceptor 路径。

## 一等模块硬标准（建成后的验收标准）

scenario 产出的 `paired` 在 accept 端与 pytest 信号**无差别对待**,能否 accept 由 e-process
+ 多闸的统计强度决定，**而非由「它是 C」结构性歧视**。信号弱时统计强度自然更难达阈，但
**通道平权**。（当前代码 vs 该目标的差异见
[`../../reference/signal-providers.md`](../../reference/signal-providers.md) 的「当前实现 vs
scenario-eval 目标」注。）

## 目标反自欺点（专属，随本模块一起建）

| 自欺形态 | 闸门 |
|---|---|
| 场景集偏袒（只生成 candidate 擅长场景） | 场景独立 agent 生成、proposer 不可见；holdout scenarios 每 K 轮抽检（visible 涨 / holdout 不涨 → force_review） |
| rubric 被 game | rubric 来自意图非 candidate；holdout 用未公开 rubric 校准 |
| 异质判官合谋 / 同源 | 判官跨家族（Claude+Codex）；pairwise_agreement 异常高且 coverage 不涨 → 合谋嫌疑闸（复用 `alpha_gate` α_high） |
| 判官 prompt 泄真值 | `build_judge_prompt` 铁律：仅含 scenario+rubric span，零真值（测试 `test_prompt_carries_no_truth` 守护） |
| 场景覆盖虚高 | coverage 按意图行为面计；新场景不计入 visible_gain（同 B 新锚闸） |

## 拟接入的代码锚

下面列的**不是 scenario-eval 的实现**,它们是今天已经存在的通用 C 档判官机件，本模块
建成时预计从这些点接入。分两类看：

**已存在，可直接复用：**

- `tools/sie/judges.py`（`build_judge_prompt` / `score` / `pairwise_agreement` / `calibrate_judge_anchor`）,
  异质判官打分与两道信任闸，现按 anchor span 工作，接入后改按 scenario+rubric 工作。
- `tools/sie/evaluate.py`（`evaluate_c_tier` / `inject_judge_scores`）,
  C 档评测入口。`evaluate_c_tier` 现在硬编码 `coverage=0.0`，本模块要替换的就是这一处。
- `tools/sie/selfdeception.py`、`tools/sie/acceptor.py`（`alpha_gate` / `judge_degrade`）,
  合谋闸与降级闸，与信号来源无关，接入后原样复用。
- `workflows/{claude,codex}-judge.js`,异质判官执行点。

**尚不存在，需新建：**

- 场景生成器与 rubric 生成器（对应 method 第 1、2 步）,无对应代码。
- `tools/sie/profile.py` 的**场景 provider 装配 + visible/holdout 场景冻结**,该文件当前
  只做 B 档**锚**的 visible/holdout 拆分（调 `anchors.split_visible_holdout`），没有场景概念。
- 按意图行为面计算的 coverage（对应 method 第 3 步）,无对应代码。
