# accept(采纳决策)

## 职责(含在 pipeline 的位置)

self-evolve 一轮自我进化是固定的五步流水线:

```
reflect → propose → evaluate → judge → accept
```

前四步把一个候选改动「想出来、试出来、打过分」。**accept 是流水线的最后一道闸**,负责回答唯一一个问题:**这个候选改动到底要不要落地(归档进 lineage 成为新版),还是丢弃、还是叫人来看?**

它不重新评测、不重新打分,只消费上游 evaluate/judge 给出的成对证据(每个任务/每个锚的「改之前」和「改之后」),把证据汇总成一个统计决策。它的核心承诺是:

- **可信(type-I 受控)**:用 e-process 序贯检验,保证「实际没变好却被判为变好」的长期概率 ≤ α(默认 0.05),且这个保证在「随时停下来看」的情况下依然成立(anytime-valid),不会因为多看几轮而被偷偷放大假阳性。
- **不退化(硬门优先)**:任何会让已经能过的任务退回去失败的改动,直接硬 REJECT,统计再漂亮也不采纳。
- **抗自欺(多闸兜底)**:即使统计判 ACCEPT,还要再过一层「自欺检测」,judge 自夸的增益是否被真实可核验的锚增益兑现、是否只在「能看见的」锚上涨而「藏起来的」holdout 锚不涨。任一闸触发就降级为人审或硬拒。

它在 pipeline 里**不直接做最终落地动作**。accept 这层的两个函数(`acceptor.decide` 算统计决策、`selfdeception.index` 算自欺信号)各自吐出一个 dict,真正把它们汇成「归档 / 叫人 / 拒绝」三选一的是状态机里的路由(`statemachine.combine_route` / `resolve_accept`)。也就是说:

> acceptor 和 selfdeception 是**两个独立的判官**,accept 模块负责让它们各说各话;状态机是**最终拍板的庭长**,按固定优先级合议出结论。

这种「判官只报信号、庭长统一裁决」的单向数据流是有意的:两个判官都是纯函数、不改全局状态,所有副作用(漂移计数 +1、写人审队列、归档)都收敛到状态机一处,方便崩溃重放。

---

## method

### 一、评测策略(A/B/C)是什么,别误读成等级

accept 对三种**信号来源**(代码里叫 tier "A"/"B"/"C",可叠加如 "A+B")走不同的判定路径。要强调:**A/B/C 不是「目标难度等级」,而是「证据从哪来、有多硬」的分类**(权威定义见 `reference/signal-providers.md`):

- **A = 客观通过/失败信号**:每个任务有一个二值结果 `task_passed ∈ {0,1}`,配成 `(before, after)`。这是最硬的证据,程序化、可复现、零主观。
- **B = 可核验锚的边际增益信号**:每个「锚」(anchor,一个可被独立程序核验的证据点)给出一个浮点增益,配成 `(before_gain, after_gain) ∈ [0,1]²`。比 A 软,因为锚要靠核验、还可能彼此相关。
- **C = 主观打分信号**:judge(模型评审)给出的主观分。最软、权重压到极低,**绝不允许单独触发 ACCEPT**。

判定的「软硬」直接体现在三条路径的设计差异上,下面逐条讲。

### 二、e-process 序贯检验:为什么不用 p 值

传统假设检验给一个 p 值,但它**不允许你边看边停**,多看几次再决定,假阳性率会爆。self-evolve 是迭代的(可能跑很多轮、随时想停下来采纳),所以用 **e-value / e-process**(下注鞅,betting martingale)。

直觉:把「改动没用」当成零假设 H₀。开局赌本(wealth)= 1。每来一对证据就下一注:如果改动真有用,赌本会系统性地涨;如果 H₀ 为真(改动没用),赌本是个鞅(期望不增)。**Ville 不等式**保证:H₀ 为真时,赌本曾经冲到过 1/α 的概率 ≤ α。于是判停规则就是:

> **e-value = 路径历史最大值 ≥ 1/α → ACCEPT**(默认 α=0.05 即阈值 20)。

取「路径最大值」`max(path)` 而非「末值」,正是 anytime-valid 的关键:等价于「在最优停时点决策」,Ville 不等式照样兜底 type-I ≤ α。

**下注机制(`_ons_betting_wealth`)的细节**:把每对差 `d = after − before` 映射到 `u = 0.5·(d+1) ∈ [0,1]`,零假设中心 `m = 0.5`(即 `d=0` 是「没改进」)。每步 `wealth ×= (1 + λ·payoff)`,`payoff = u − 0.5 ∈ [−0.5, 0.5]`。下注比例 λ 用 **ONS(Online Newton Step)**自适应:`λ ← clip(b/(A+1), ±(2−1e-6))`,其中 A 是梯度平方累积、b 是梯度累积、`+1` 是正则项(避免 A=0 时初始大步)。

这里有两个被代码注释专门点名的工程坑:

1. **只 clip λ,不 clip factor**。把 λ 收紧到 `±(2−δ)` 就能保证 `factor = 1+λ·payoff` 恒 `> 0`(下界 ≈ 5e-7),从而 wealth 永远是正数。**绝不能直接截断 factor 本身**,那会破坏鞅恒等式、让 ONS 梯度爆炸,等于偷偷把 type-I 保证给毁了。
2. **优先用 confseq 库,缺失才回退自洽实现**。`_wealth_betting` 先尝试 `confseq.betting.betting_mart`(成熟实现),`import` 或运行失败才退回上面手写的 ONS 鞅。两条路同口径(同 u 映射、同 m=0.5、同取 max(path)),保证有没有装库结果一致。

### 三、A 档路径:硬门优先 + 二态决策

`decide(paired, "A", ...)` 的流程:

1. **空配对 → REJECT**(无证据不采纳)。
2. **no-regression 硬门(A 档专属)**:扫描所有配对,任一 `before ≥ 1.0 > after`(即原来能过、改完不过)→ 立刻硬 REJECT,**覆盖一切 e-process 结果**。理由很硬:进化不允许「平均涨但踩坏已有能力」。注意此门**只在 A 档执行**,B 档的 `before_gain=1.0` 是「满分增益」的合法值,不代表退化,在 B 档跑这门会误杀强增益锚。
3. **e-process(二态)**:跑下注鞅得 e-value。`≥ 1/α → ACCEPT`;否则 `REJECT`。**A 档禁 CONTINUE**,客观信号要么够了要么不够,不存在「再攒攒证据」。

### 四、B 档路径:三道门 + 去相关 + 允许 CONTINUE

B 档证据较软(锚要核验、会相关),所以在 e-process 之前先架三道**结构性门**:

- **门1 锚数下限**:`n_anchor < n_min`(默认 8)→ REJECT。样本太少不给过。
- **门2 有效独立锚下限**:把可见且已核验的锚按「同源聚类」折算成「有效独立数」(`anchors.effective_independent_count`:同源簇内信息次线性 `floor(1 + log2(簇大小))`,各簇求和)。`eff < eff_min`(默认 12)→ REJECT。这是防「拿一堆其实同源的锚冒充很多独立证据」。
- **门3 e-value 总量钳**:`evalue = min(evalue, evalue_max_step)`(默认 1e6 即实际不限,仅显式设小值时生效),防单次调用把累积 e-value 顶爆。

过门后跑 e-process,但输入先做**同源锚去相关降权**(`_decorrelate_downweight`):若调用方给了 `cluster_ids`,同一 cluster 的锚各按 `1/簇大小` 降权,使一簇相关锚的总贡献等价于一个独立锚,**防相关锚把 e-value 虚高**。再把 diff 钳到 `[−1,1]`(B 的增益差天然在此区间,钳只兜异常输入)。

决策三态:`≥ 1/α → ACCEPT`;`1 < e < 1/α` 且 `continue_count < continue_count_cap`(默认 5)→ **CONTINUE**(B 是随机档,允许再攒一轮证据);否则 REJECT。返回里还附带 `effective_independent` / `n_anchor` 供状态机用。

### 五、C 档路径:极低权重 + coverage=0 必经人审

C 是主观分,设计目标是「**永不让它单独说了算**」:

- 主观分先过 `_scale_subjective`(按历史方差缩放 + 单步截断到 `[−1,1]`),再乘 `c_tier_weight`(默认 **0.05**),权重压到极低,基本不可能单独把 e-value 推过阈值。
- 跑 e-process 得三态(同 B,含 CONTINUE)。
- 最后过 `_apply_c_tier_gates`:**纯 C(coverage=0,即完全没有程序化锚覆盖)无论 e-process 结果如何,都强制 `force_review=True`、`degrade_reason="pure_C_needs_human"`**,auto 模式下绝不自动落地,必须人来看。

### 六、几个 provider 专属的降级闸(C 档辅助)

accept 模块还提供几个状态机会用到的专门门函数:

- `c_tier_no_regression(replay_results)`:历史成功 replay 任一 `before=True 而 after=False` → False(C 档版本的不退化硬门)。
- `alpha_gate(alpha, anchor_up, params)`:双向一致性门。`alpha < alpha_low`(默认 0.4,一致性过低)→ 人审;`alpha > alpha_high`(默认 0.85)**且锚不涨** → 人审 **且计为一次自欺**(疑似 judge 与 proposal 合谋自夸)。哨兵 `alpha=None`(judge 不可用)→ 直接 `force_review=True`,按不可信处理。
- `judge_degrade(codex_available, claude_available)`:**Codex 不可用 → 禁止单 Claude 自动 ACCEPT**,降级为「只信程序化锚」+ 升人审。这是防「评审与提案是同一个模型、自己批自己」的关键降级。

### 七、自欺检测多闸(`selfdeception.index`)

即使 acceptor 判了 ACCEPT,还要再过这一层。它比较三路增益,**judge 自夸的增益 / 真实可见锚增益 / 藏起来的 holdout 锚增益**,算出自欺指数并触发多闸:

- **自欺指数** `value = judge_gain − visible_anchor_gain`:judge 说涨了多少 vs 真实核验锚涨了多少。
- **闸②(增益地基太薄)**:`visible_anchor_gain < ε`(默认 0.02)→ `block_accept=True`。留存锚几乎没真涨,统计地基不可靠,**禁 ACCEPT**。
- **闸③(过拟合背离,主信号)**:可见锚涨(`> 0`)但 holdout 锚不涨(`≤ 0`)→ `force_review=force_human=True`。这是典型的「只在能看见的题上过拟合、藏起来的题原形毕露」。`holdout_gain=None`(非抽检轮、本轮没 holdout 数据)时**跳过此闸**。
- **闸④(疑似合谋漂移)**:`|value| > band`(默认 0.15)→ 追加 `judge_anchor_divergence` alert。judge 自夸显著超出锚真实增益,疑似 judge/proposal 合谋。

两个关键约定:

1. **闸①由上游保证,不在本函数重做**:传进来的 `visible_anchor_gain` 必须已经只含 frozen 留存锚(span 在前后两轮都出现的锚)的真实增益,**当轮新增的锚不计入当轮增益**,否则可以「每轮新塞几个好看的锚」来刷增益。过滤由 anchors/evaluate 在调用前完成;本模块提供 `retained_visible_gain(prev, cur)` 工具算留存锚平均增益,但默认信任上游。
2. **单向数据流,不改 RunState**:本函数只读 `st.drift_count`(供日志),**绝不自己 +=**。闸④触发时只在返回的 alerts 里放 `judge_anchor_divergence` 这个信号串,由状态机读到后执行 `st.drift_count += 1`。累计漂移达到熔断阈(`_DRIFT_CIRCUIT = 4`)时由状态机停 run。另有 `cumulative_drift(visible_cum, holdout_cum, tolerance=1.5)` 工具检测同一 lineage 上「可见累计涨幅 > holdout 累计涨幅 × 1.5」的预算超支型过拟合。

> 别被 alert 数量误导:每个闸为向后兼容会同时追加「旧名 + 新名」两条 alert(如闸②吐 `low_anchor_gain` 和 `below_eps:...`),所以**统计触发次数绝不能用 `len(alerts)`**,漂移累计必须专门检测 `judge_anchor_divergence` 子串。

### 八、两个判官如何被庭长合议(状态机路由)

状态机把 `acceptor.decide` 的 `decision`、`selfdeception.index` 的 `sd`、外加 `alpha_gate` / `judge_degrade` 的输出,按**固定优先级**(`combine_route`)合成最终去向:

1. `decision != ACCEPT` → **REJECT**(acceptor 没点头,免谈)。
2. `sd.block_accept`(闸②,可见增益 < ε)→ **REJECT**。
3. 任一 `force_review`(sd / alpha_gate / degrade / decision 中任意一个)→ **PAUSE_FOR_HUMAN**(进人审队列)。
4. `degrade.single_claude_block`(Codex 不可用)→ **PAUSE_FOR_HUMAN**。
5. 纯 C + auto + coverage=0 → **PAUSE_FOR_HUMAN**。
6. 全过 → **ARCHIVE**(落地为新版)。

B 档的 `resolve_accept` 在此之上还会:把 `judge_anchor_divergence` 落成 `st.drift_count += 1`;把「想 ACCEPT/CONTINUE 但触发 coverage 违规 / force_human / low_anchor_gain」的情况提前抢救到态 9.5(人审),防止在次优数据上持续迭代。

可以记住一句话:**任何一个判官说「停」,庭长就停;只有所有判官都默许,才归档。** 这是「宁可错杀(降级人审),不可漏放(假阳性落地)」的非对称设计,与 type-I ≤ α 的保守精神一致。

---

## 契约(I/O schema + 相邻模块接口)

### `acceptor.decide(paired, tier, st, params) -> dict`

**入参**

| 字段 | 类型 | 含义 |
|---|---|---|
| `paired` | `list[tuple[float, float]]` | 每元素 `(before, after)`。A 档 ∈ {0,1}²;B 档为锚边际增益 ∈ [0,1]²。 |
| `tier` | `str` | `"A"|"B"|"C"`,叠加如 `"A+B"` 取 `+` 前主档。 |
| `st` | `RunState` | 当前运行状态(读 `continue_count`)。 |
| `params` | `dict` | 超参,见下表。 |

**`params` 常用键**:`α`/`alpha`(默认 0.05)、`n_min`(B,8)、`effective_independent_anchor_min`(B,12)、`continue_count_cap`(5)、`evalue_max_step`(B 1e6)、`c_tier_weight`(C 0.05)、`alpha_low`(0.4)、`alpha_high`(0.85)、`coverage`(C,1.0)、`cluster_ids`(B 去相关,可选)、`anchors`(B 门2 用的可见已核验锚列表)。

**返回**(所有路径保证含这些键)

```
{
  "decision":      "ACCEPT" | "REJECT" | "CONTINUE",  # A 档禁 CONTINUE
  "evalue":        float,                              # 路径最大 e-value
  "reason":        str,                                # 人读理由
  "force_review":  bool,                               # 是否强制人审
  "degrade_reason": str | None,                        # 降级原因(如 pure_C_needs_human)
  # B 档额外:
  "effective_independent": int,
  "n_anchor":              int,
}
```

### `selfdeception.index(judge_gain, visible_anchor_gain, holdout_gain, st, params) -> dict`

**入参**:`judge_gain`(judge 主观增益)、`visible_anchor_gain`(**须上游已过滤为 frozen 留存锚真实增益**)、`holdout_gain`(`float | None`,None=非抽检轮跳过闸③)、`st`(只读 `drift_count`)、`params`(可覆盖 `frozen_anchor_effective_gain_eps`=0.02、`selfdeception_alert_band`=0.15)。

**返回**

```
{
  "value":        float,       # judge_gain − visible_anchor_gain(round 12 位)
  "alerts":       list[str],   # 触发闸名(每闸旧名+新名两条;统计次数勿用 len)
  "block_accept": bool,        # 闸②:visible_anchor_gain < eps
  "force_review": bool,        # 闸③:overfit_holdout(主信号)
  "force_human":  bool,        # = force_review(向后兼容别名)
}
```

### 相邻模块接口

- **上游 evaluate / judge → accept**:evaluate 产出 `paired`(A 档 task_passed 配对 / B 档锚增益配对)、`visible_anchor_gain`、`holdout_gain`、`anchors_visible_verified`、`coverage_floor_violation`;judge 产出主观 `judge_gain` 与一致性 `alpha`。这些经 `params` 与 `eval_out` 喂进 accept 的两个函数。
- **accept → 状态机(下游唯一消费者)**:`statemachine.combine_route` / `resolve_accept` 消费两个 dict,产出 `"ARCHIVE" | "PAUSE_FOR_HUMAN" | "REJECT"`,并负责所有副作用,`st.drift_count += 1`(读到 `judge_anchor_divergence`)、写人审队列(`gate_human.enqueue`)、归档进 lineage。
- **accept → anchors**:B 档门2 调 `anchors.effective_independent_count` 折算有效独立锚数。
- **accept 不触碰**:RunState 的任何写入、文件 IO、归档动作。两个核心函数是纯函数,签名锁定(`decide` 接口 M1a 起不变,`selfdeception` 标 IMMUTABLE)。

---

## 反自欺点(本模块的自欺形态 + 对应闸门)

accept 是流水线最后一关,也是自欺最可能「闯关成功落地」的地方。本模块针对的自欺形态及其闸门:

| 自欺形态 | 它怎么骗 | 对应闸门 |
|---|---|---|
| **多看几轮刷假阳性** | 反复评测,挑赌本最高的一刻宣布成功 | e-process anytime-valid:取 `max(path)`,Ville 不等式保证 type-I ≤ α,看多少轮都不放大假阳性 |
| **平均涨但踩坏已有能力** | 整体 e-value 好看,却让原本能过的任务退化 | no-regression 硬门(A 档 `before≥1>after` / C 档 `c_tier_no_regression`),覆盖一切统计结果 |
| **相关锚冒充独立证据** | 拿一堆同源锚假装样本量大 | 门2 有效独立锚下限(`effective_independent_count` 次线性折算)+ `_decorrelate_downweight` 同源降权 |
| **每轮塞新好看锚刷增益** | 当轮新增锚算进当轮增益 | 闸①(上游只计 frozen 留存锚,新锚不计当轮;`retained_visible_gain` 工具) |
| **增益地基太薄就采纳** | 真实锚几乎没涨也判 ACCEPT | 闸②`visible_anchor_gain < ε` → `block_accept` 硬拒 |
| **只在可见题上过拟合** | 看得见的锚涨、藏起来的 holdout 原形毕露 | 闸③ overfit_holdout(主信号)→ 强制人审;`cumulative_drift` 查 lineage 级预算超支 |
| **judge 自夸 / judge 与提案合谋** | 主观分虚高、评审自批自 | 闸④`|value|>band`(漂移累计→熔断)、`alpha_gate` 双向门(高一致+锚不涨→计自欺)、`judge_degrade`(Codex 不可用禁单 Claude auto)、C 档 `c_tier_weight=0.05` 永不单独 ACCEPT、纯 C coverage=0 必经人审 |

贯穿性原则:**判官只报信号、绝不自己改状态**(单向数据流,漂移计数与落地都收敛到状态机),以及**非对称设计**,宁可降级人审多打扰,绝不让假阳性自动落地。数学证明(Ville 不等式、ONS 收敛、有效独立锚折算)详见 `reference/acceptor_math.md`;A/B/C 信号来源的权威定义见 `reference/signal-providers.md`。

---

## 代码锚(file:func 列表)

**`tools/sie/acceptor.py`**
- `decide`, 公开 API,三档路由 + 硬门 + e-process 决策
- `_ons_betting_wealth`, 自洽 ONS 下注鞅(anytime-valid,confseq 缺失时回退)
- `_wealth_betting`, confseq 优先 / ONS 回退的统一适配器
- `_pace_threshold`, 采纳阈值 1/α
- `_scale_subjective`, C 档主观分方差缩放 + 单步截断
- `_decorrelate_downweight`, B 档同源锚去相关降权
- `c_tier_no_regression`, C 档不退化硬门
- `alpha_gate`, 双向一致性门(含 None 哨兵 + 合谋计自欺)
- `judge_degrade`, Codex 不可用降级(禁单 Claude auto + 锚唯一裁决)
- `_apply_c_tier_gates`, 纯 C coverage=0 强制人审叠加门

**`tools/sie/selfdeception.py`**
- `index`, 自欺多闸主函数(闸②/③/④,返回 value/alerts/block_accept/force_review)
- `retained_visible_gain`, 闸①辅助:只计 frozen 留存锚增益
- `cumulative_drift`, 闸④辅助:lineage 级累计漂移预算检测

**相邻锚(下游裁决,非本模块但接口紧邻)**
- `tools/sie/statemachine.py:combine_route`, 两判官信号 → ARCHIVE/PAUSE_FOR_HUMAN/REJECT 固定优先级合议
- `tools/sie/statemachine.py:resolve_accept`, B 档 ACCEPT 态接线(drift_count 累计 + 人审抢救)
- `tools/sie/anchors.py:effective_independent_count`, B 档门2 有效独立锚折算
