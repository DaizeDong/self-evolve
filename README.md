# self-improving-research-agent

自改进 / 自进化调研 Agent —— 让一个「商业/投资调研 skill」（market-intel、small-cap-deepdive 类）在长时间全自动循环里持续自我迭代升级的研究与工程项目。

闭环形态：**读历史运行数据 → 多 subagent 独立反思 → brainstorm 汇总修改方案 → 改 skill + 复查 → 重跑旧主题对比 + brainstorm 多样新主题做评估 → 多路迭代直到达标**。

## 当前状态

仅完成**前期全景调研**（确定研究方向与已有成果）。尚未开始实现。

- 📄 [`docs/自改进Agent调研.md`](docs/自改进Agent调研.md) — 完整调研报告：研究方向定位（Self-Evolving / Self-Improving Agents）、论文全清单、可复用开源仓库、对本项目 prompt 的逐条对标缺口分析、护栏设计、可发表研究方向。

## 一句话定位

属于 **Self-Evolving / Self-Improving Agents** 中「agent 自动改进自己的 skill/scaffolding」一支，架构上是 **DGM + SICA + MARS + OMNI** 的并集。

## 核心风险（来自调研）

被优化对象是**无 ground-truth 的开放生成任务**（调研报告），而文献里自改进成功的几乎都在可验证域（代码/数学）。叠加「自出题 + 自评分」的 self-judge 结构，按文献**几乎注定产出虚假的上升曲线**（分数涨、能力不涨）。

**实现前必须先上的护栏三件套**：① 外部可验证锚点（edgartools/EDGAR 程序化核查事实断言）② 异构 judge（judge 强制换不同模型家族）③ Archive + Pareto 版本管理。

详见调研报告 §5–§7。

## 直接复用候选

- **GEPA**（`gepa-ai/gepa`）— 反思 + 遗传 + Pareto，优化任意文本参数
- **OpenEvolve**（`algorithmicsuperintelligence/openevolve`）— AlphaEvolve 开源复现，island + MAP-Elites
- **edgartools** — 外部真值源（small-cap-deepdive 已依赖）

## 相关基建

- `../market-intel`、`../small-cap-deepdive` — 被优化的调研 skill 本体与信息源 catalog
