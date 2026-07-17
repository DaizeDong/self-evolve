# self-evolve：以不可博弈的提交门保证「被采纳即真改进」的智能体自迭代框架

## 摘要

智能体自我改进的核心风险不是「改不动」，而是**自欺**,系统学会让评测分数上升而非让能力
真正提升（reward hacking / overfitting to the metric / 让模型评判自己的产出）。self-evolve
提出一个「提议,裁决」分离的框架：**LLM 仅提议改动，确定性 harness 裁决采纳**，并以一组与
评测策略正交的反自欺不变量，把「被采纳」在数学与流程上等价于「真改进」。框架的普适性来自
一个观察,*任何意图可抽取、可操作化的「更好」都能被转化为可重复的评测*，因此提出统一的
**评测信号 provider** 框架（程序裁决 / 锚核验 / 生成评测），使方法论可施加于任意仓库、不
存在「不可进化的目标」。我们在真实 SEC/EDGAR 数据上 live 验证了端到端采纳，并以本框架自身
的方法论升级了一个 16-skill 的真实应用，期间异质核验拦截了多个单模型会自信写错的 LIVE 错误。

## 1. 引言与动机

设 *T* 为待改进目标，π 为一次候选改动。朴素的自迭代循环 `propose → score → accept if score↑`
存在三条自欺通路：(1) **自评污染**,用产出改动的同一模型评判该改动；(2) **可见指标过拟合**
,只在被观测的评测点上变好，泛化未提升；(3) **多看即偶得**,反复重评直到分数偶然越线
（破坏 type-I 错误率）。self-evolve 的设计目标是：在**全自动**循环内关闭这三条通路。

## 2. 设计理念

**核心命题：方法论恒定，信号来源自适应。** 迭代算子 reflect → propose → evaluate → judge
→ accept 对一切目标不变；唯一随目标变化的是**评测信号 s(π) 从何处获得**。框架由两组正交
承诺支撑：**评测策略（provider）** 决定信号*来源*（可换）；**反自欺不变量** 决定信号能否被
*信任*（不可动）。五条工程铁律编码不变量边界：

| # | 铁律 | 防的自欺 |
|---|---|---|
| L1 | LLM 提议，代码裁决 | 自评污染 |
| L2 | 原始证据只读（`events.jsonl` 唯一真相源，可 replay） | 篡改历史 |
| L3 | 真值隔离（holdout 对 reflect/propose/patch 物理不可读） | 可见指标过拟合 |
| L4 | 信号源一次冻结（PROFILE 后不重选） | 中途换有利评测 |
| L5 | 沙箱内全自动，出沙箱走人审 | 自动循环造成不可逆后果 |

## 3. 方法

### 3.1 进化循环

一次迭代为六步认知循环加一道升级闸：
PROFILE → REFLECT → PROPOSE → PATCH → EVALUATE → JUDGE →(accept/reject/rollback)→ LOOP；
命中自欺判据或熔断时旁路至 PAUSE_FOR_HUMAN。（底层为 10 态门控状态机，是实现真相；六动词
为其面向使用者的收敛映射。）各步关键约束见 [`pipeline.md`](pipeline.md) 与 [`modules/`](modules/)。

### 3.2 统一评测框架（信号 provider）

三 provider 共享同一 `evaluate` 契约，按可核验强度排序、可叠加：

| Provider | 信号 s(π) | 强度 |
|---|---|---|
| **A 程序裁决** | 可执行测试 pass/fail（自带或可生成） | 最高：确定、可重放 |
| **B 锚核验** | 改进主张拆为可独立核验事实锚，逐锚 verify 的 marginal gain | 高：独立源、可抽 holdout |
| **C 生成评测** | harness 生成场景 + rubric，异质判官盲评（prompt 无真值） | 较低：异质 + 防合谋闸补强 |

**普适性命题（非形式）**：C 是一条可*主动构造*的信号通道,对任何意图可操作化的目标都能
生成场景与 rubric 并交异质模型盲评,故 evaluate 对任意 *T* 恒有输出，**不存在不可进化的
目标**。纯 C 默认走人审落地，是信号最弱时把终判交回人的*审慎*，非「目标不可用」。
（落地状态：C 的真 coverage 与 accept 端平权由 scenario-eval 模块承载，当前代码对纯主观 C
仍保守处理，见 [`../reference/signal-providers.md`](../reference/signal-providers.md)。）

### 3.3 采纳判据：anytime-valid e-process

设第 *k* 轮观测改进差 δ_k = s_after^k − s_before^k。acceptor 维护非负鞅式财富过程
（e-process）W_k，使「无真改进」零假设下 E[W_k] ≤ 1，由 Ville 不等式得任意时刻
Pr(∃k: W_k ≥ 1/α) ≤ α。采纳条件：

> W_k ≥ 1/α ∧ no-regression ∧ provider 专属门 ∧ ¬自欺多闸

anytime-valid 性质允许多轮重评而不抬高 type-I（关闭「多看即偶得」），置信序列不可用时回退
ONS。no-regression 硬门：任一历史成功项退化即硬 REJECT，凌驾统计证据。B 专属门：锚数下限、
有效独立锚 ≥12（同源去相关 eff=⌊1+log₂|cluster|⌋）、单步增益总量钳。C 专属门：双向 α 门
+ judge 降级门（缺独立 judge 禁单模型 auto-accept）。

### 3.4 反自欺不变量（与 provider 正交）

(1) 异质核验,评判者必与提议者异质；(2) holdout 隔离,留存信号物理隔离、每 K 轮抽检；
(3) e-process（§3.3）；(4) no-regression 硬门；(5) 背离即升级,可见与 holdout / judge 与锚
背离、或 lineage 累计漂移超预算 → 人审或熔断；释放阀只升人审频率，绝不降阈自动采纳。

### 3.5 自举隔离

当 *T* 即框架自身：14 个 IMMUTABLE 决策码从 frozen base ref 物化并记 sha256，启动哈希
fail-closed 校验，patch 写 IMMUTABLE 硬拒，**supervisor 双进程**用 frozen 代码裁决（candidate
worktree 永不进 sys.path、不能自评 / 自打分）。见 [`modules/self-boot.md`](modules/self-boot.md)。

## 4. 实现要点

事件溯源（`events.jsonl` 唯一真相源、计数器经 delta、崩溃可 replay）；生成式接缝走本机
`cc`/`codex exec`（默认确定性 builtin 不调外部、供测试）；三正交计数器 + drift 熔断防空转。

## 5. 实证

- **B 档真采纳（live, 真 EDGAR）**：proposer 修正研究产物可核验断言 → 逐锚 EDGAR 核验 →
  e-process 跨阈（W≈3.96×10⁵ ≫ 1/α=20）→ 连续采纳 v1/v2/v3，无可改进时正确收手。
- **方法论 dogfood**：以本框架方法论对 16-skill 真实应用做 6 轮迭代（50 州数据 / 16 CPO
  品牌 / 多语言 / 评测 harness），客观回归门全程绿、异质双审通过。
- **异质核验实证价值**：单模型把某法定费用写成两个互相矛盾错值，异质判官（不同家族 + 独立
  联网）独立核出真值并拦截,「自评污染」被关闭的直接证据。

## 6. 局限与未来

scenario-eval 的代码平权（C 携带场景对意图覆盖率、与 A/B 同形平权裁决）；核验诚实性
（异质未确认事实诚实降级 verified:false）；事实新鲜度（周期再核验抗漂移）。

## 7. 结论

self-evolve 把「真改进」从主观判断重构为**可证伪、anytime-valid、由异质独立证据支撑的统计
判定**，并以「方法论恒定、信号来源自适应」使之普适于任意仓库。核心贡献不在让智能体更会改
代码，而在**让「改得更好」这一承诺变得不可博弈**。
