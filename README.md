# self-improving-research-agent

自改进 / 自进化调研 Agent —— 让一个「商业/投资调研 skill」（market-intel、small-cap-deepdive 类）在长时间全自动循环里持续自我迭代升级的研究与工程项目。

闭环形态：**读历史运行数据 → 多 subagent 独立反思 → brainstorm 汇总修改方案 → 改 skill + 复查 → 重跑旧主题对比 + brainstorm 多样新主题做评估 → 多路迭代直到达标**。

## 当前状态

仅完成**前期调研**（全景 + 硬信号交叉验证）。尚未开始实现。

- 📄 [`docs/自改进Agent调研.md`](docs/自改进Agent调研.md) — 全景调研：研究方向定位（Self-Evolving / Self-Improving Agents）、论文全清单、可复用开源仓库、对本项目 prompt 的逐条对标缺口分析、护栏设计、可发表研究方向。
- 📄 [`docs/02-crossval-deepdive.md`](docs/02-crossval-deepdive.md) — 用 market-intel 学术工具链（arXiv / Semantic Scholar / OpenReview / HF）做的**交叉验证 + 2026 新论文深读**：引用量硬信号、ICLR 2026 RSI workshop 录用、14 篇晚于知识截止的新论文逐篇归类到护栏/缺口，并**更新研究空白判断**。原始数据在 [`docs/data/`](docs/data/)。

## 一句话定位

属于 **Self-Evolving / Self-Improving Agents** 中「agent 自动改进自己的 skill/scaffolding」一支，架构上是 **DGM + SICA + MARS + OMNI** 的并集。

## 核心风险（来自调研）

被优化对象是**无 ground-truth 的开放生成任务**（调研报告），而文献里自改进成功的几乎都在可验证域（代码/数学）。叠加「自出题 + 自评分」的 self-judge 结构，按文献**几乎注定产出虚假的上升曲线**（分数涨、能力不涨）。

**实现前必须先上的护栏三件套**：① 外部可验证锚点（edgartools/EDGAR 程序化核查事实断言）② 异构 judge（judge 强制换不同模型家族）③ Archive + Pareto 版本管理。

详见调研报告 §5–§7。

## 直接复用候选

- **GEPA**（`gepa-ai/gepa`）— 反思 + 遗传 + Pareto，优化任意文本参数
- **OpenEvolve**（`algorithmicsuperintelligence/openevolve`）— AlphaEvolve 开源复现，island + MAP-Elites
- **OpenSkill**（`OpenLAIR/OpenSkill`）— 无监督下从外部抽 verification anchor 自建练习任务（最贴本项目场景，= 护栏①蓝图）
- **MOSS**（`hkgai-official/Moss`）— trial-worker 重放 + health-probe 回滚（= 护栏⑤）
- **meta-agent-challenge**（`ant-research/meta-agent-challenge`）— 防 reward-hacking 评测 harness 模板
- **PACE**（论文 arXiv 2606.08106）— anytime-valid acceptor 门，替代「重跑对比涨了就保留」
- **edgartools** — 外部真值源（small-cap-deepdive 已依赖）

> ⚠️ 研究空白更新（见 doc 02）：原「空白2 自指改进可信认证」已被 **PACE（2026-06）** 基本占据；残留真空白 = **无 ground-truth 的开放调研域** 上把 verification-anchor + anytime-valid acceptor + 对抗式任务-skill 协同进化三者缝合。

## 相关基建

- `../market-intel`、`../small-cap-deepdive` — 被优化的调研 skill 本体与信息源 catalog
