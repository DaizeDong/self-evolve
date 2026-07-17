# Module: scenario-eval（生成评测 · 普适性承重墙）

## 职责

目标无 exec 信号（A）、无 external-fact 锚（B）时**自造评测信号**：生成评测场景 + rubric，
交异质判官盲评，输出与 A/B **同形**的 `paired` 喂给同一 acceptor。让 `evaluate` 契约对任何
目标可满足,这是「没有不可用目标」在工程上的兑现。

pipeline 位置：EVALUATE 步的第三个 provider（前两者取不到时）。是 C 档的真正实现方式，
把「纯主观打分」升级为「可主动构造、可量化、可回归」的信号通道。

## method（四步数据流）

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

## 契约

- 输入：目标意图来源（描述 / README / 用例）、profile 冻结的 visible/holdout 场景集。
- 输出：`paired`（与 A/B 同形）、`coverage`（场景对意图的覆盖率）、`alpha`/`calibration`
  （判官一致性）、`holdout_gain`（每 K 轮抽检）。
- 场景 schema（见 [`../../reference/target_contract.md`](../../reference/target_contract.md)）：
  `scenarios:[{id, rubric, visible|holdout}]`。
- 相邻接口：PROFILE 决定启用本 provider 并冻结场景；JUDGE/accept 用同一 acceptor 路径。

## 一等模块硬标准

scenario 产出的 `paired` 在 accept 端与 pytest 信号**无差别对待**,能否 accept 由 e-process
+ 多闸的统计强度决定，**而非由「它是 C」结构性歧视**。信号弱时统计强度自然更难达阈，但
**通道平权**。（当前代码 vs 该目标的差异见
[`../../reference/signal-providers.md`](../../reference/signal-providers.md) 的「当前实现 vs
scenario-eval 目标」注。）

## 反自欺点（专属）

| 自欺形态 | 闸门 |
|---|---|
| 场景集偏袒（只生成 candidate 擅长场景） | 场景独立 agent 生成、proposer 不可见；holdout scenarios 每 K 轮抽检（visible 涨 / holdout 不涨 → force_review） |
| rubric 被 game | rubric 来自意图非 candidate；holdout 用未公开 rubric 校准 |
| 异质判官合谋 / 同源 | 判官跨家族（Claude+Codex）；pairwise_agreement 异常高且 coverage 不涨 → 合谋嫌疑闸（复用 `alpha_gate` α_high） |
| 判官 prompt 泄真值 | `build_judge_prompt` 铁律：仅含 scenario+rubric span，零真值（测试 `test_prompt_carries_no_truth` 守护） |
| 场景覆盖虚高 | coverage 按意图行为面计；新场景不计入 visible_gain（同 B 新锚闸） |

## 代码锚

- `tools/sie/judges.py`（`build_judge_prompt` / `score` / `pairwise_agreement` / `calibrate_judge_anchor`）
- `tools/sie/evaluate.py`（`evaluate_c_tier` / `inject_judge_scores`）
- `tools/sie/profile.py`（场景 provider 装配 + visible/holdout 冻结）
- `tools/sie/selfdeception.py`、`tools/sie/acceptor.py`（`alpha_gate` / `judge_degrade`）
- `workflows/{claude,codex}-judge.js`（异质判官执行点）
