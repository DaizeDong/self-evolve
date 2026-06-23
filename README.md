# self-evolve

> A methodology skill + lightweight deterministic harness that lets an agent **self-iterate any
> skill / repo / project**, with an **un-gameable acceptance gate** so "accepted = real improvement"
> — not a self-deceiving score-up-but-capability-flat curve. Built for the hard case the
> self-improving-agent literature mostly skips: **open-ended generation domains with no ground truth.**

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-521%20passing-green?style=flat)](tests/)
[![Anti-self-deception](https://img.shields.io/badge/anti--self--deception-6%20paths%20closed-red?style=flat)](SKILL.md)
[![Sister skill](https://img.shields.io/badge/sister-market--intel-yellow?style=flat)](https://github.com/DaizeDong/market-intel)

*English summary above · 完整中文文档如下。*

---

让 agent **自我迭代开发任意 skill / 仓库 / 项目**的方法论 skill + 轻量确定性 harness。
核心目标是**反自欺**：在长时间全自动循环里改进目标时，用不可 game 的提交门保证
「被采纳 = 真改进」，而非分数涨、能力不涨的虚假上升曲线。

闭环形态：**读历史 trace → 多 subagent 独立反思 → 汇总修改方案 → 改目标 + 复查 →
沙箱内可验证评测 + 不可 game 的接受门 → 多路迭代直到达标**，采纳的版本进 archive
lineage，出沙箱的落地动作走人审。

## 当前状态

**实现完成 — 安全/裁决骨架全部建成并测试，ship-ready 框架。**

- 52 任务 / 5 里程碑 / **521 测试通过**（2 个 confseq 用例按环境跳过）。
- 全分支终审通过：跨任务整合自洽、反自欺六路径全闭合、自举安全四铁律端到端守。

> ✅ **成熟度**：裁决 / 门控 / 反自欺 / 自举隔离 / crash-replay 全部真实可用，**生成式
> LLM 接缝也已接通真 agent 并 live 验证**——proposer / reflector / 两个 judge 走本机
> `cc`（split-billing 网关，fallback `claude`）+ `codex` CLI：
> ① propose（`backends/llm.py` + `claude-propose.js`）— live 生成正确代码修复；
> ② reflect / review fanout（`workflows/*-fanout.js`）— live N=3 并行 MARS；
> ③ C 档异质 judge（`claude-judge.js` + `codex-judge.js`）— live 双家族评分 + pairwise。
> 默认 `builtin` / `serial`（确定性，521 测试用，不调外部）；`--live`（= `--proposer llm
> --reflect-mode parallel`）开真 agent 闭环。注：纯 A 档自动 ACCEPT 需"改后更多测试通过"
> 的改进空间（绿基线无此空间，按设计），真正的开放域改进信号在 B / C 质量档。

## 这是什么

属于 **Self-Evolving / Self-Improving Agents** 中「agent 自动改进自己的 skill /
scaffolding」一支，思路上缝合 **DGM + SICA + MARS + OMNI + PACE**，并针对**无
ground-truth 的开放生成域**补齐护栏（文献里自改进成功几乎都在代码 / 数学等可验证
域）——这正是本项目要填的真空白：在开放域上把 verification-anchor + anytime-valid
acceptor + 异构 judge + 对抗式协同进化缝合起来。

## 反自欺主线（六路径全闭合）

| candidate 自欺路径 | 防御 |
|---|---|
| 改 grader / judge 自评 | IMMUTABLE 决策码清单 + frozen 物化 + 启动哈希 fail-closed + patch 硬拒门 + supervisor 双进程裁决（candidate 永不进 sys.path、不裁决 / 不评分自己） |
| 塞无法核验的"锚" | verify_anchor（EDGAR 程序化核查）+ marginal_gain 未核验恒 0 |
| holdout 过拟合 | holdout 真值物理隔离（铁律5）+ 确定性拆分 + 背离闸 + 累计漂移预算 |
| judge 合谋 | 异构 judge（Claude + Codex，强制不同模型家族）+ pairwise_agreement + judge↔锚校准（只用 holdout 锚） |
| 相关锚虚高 e-value | effective_independent_count 同源去相关（8→4）+ 独立性下限门 |
| 出站隐蔽信道 exfil | proxy harness 代发（candidate 无 URL 构造权）+ 熵 / 编码 / 序列异常审查 |

## 里程碑

| 里程碑 | 内容 |
|---|---|
| **M1a** | 确定性状态机 harness：10 态 run_loop、events.jsonl append-only 真相源 + crash-replay、git worktree 沙箱、三正交计数器 |
| **M1b** | PACE e-process acceptor（反自欺命门，type-I ≤ α 验证、ONS 回退）、AST 危险门、变异有效性门、非阻塞人审队列、熔断 + 活性 |
| **M2** | B 档外部锚（extract / coverage / 去相关 / 确定性 holdout / EDGAR verify / EVE 边际增益）、acceptor 三门、selfdeception holdout 背离、出站 proxy 反 exfil |
| **M3** | C 档异质 judge（Claude + Codex）、pairwise_agreement、judge↔锚校准、自欺多闸、双向 α 门、纯 C 强制人审、Pareto 硬维门、N=3 MARS、BenchTrace |
| **M4** | 自举隔离：IMMUTABLE 清单 + frozen、启动哈希门、patch 硬拒、supervisor 双进程裁决、自举 frozen grader、`--self` 端到端 |

## 用法

```bash
# 对任意有 git 历史的目标仓库启动一次自迭代 run（沙箱内全自动）
python -m tools.sie.cli init  --target <目标仓库绝对路径>                       # 取 run_id
python -m tools.sie.cli run   --target <目标> --run-id <id> --base-ref HEAD --max-rounds 3
python -m tools.sie.cli status   --target <目标> --run-id <id>                 # 查看状态
python -m tools.sie.cli replay   --target <目标> --run-id <id>                 # 崩溃后从 events 重建
python -m tools.sie.cli rollback --target <目标> --run-id <id> --vid <vid>
# 自举（改 self-evolve 自身，开 IMMUTABLE enforce）
python -m tools.sie.cli run --target <self-evolve 自身> --run-id <id> --self --enforce-immutable
```

斜杠命令（需先把本仓库 junction / 部署到 `~/.claude/skills/self-evolve`）：
`/self-evolve <target>`、`/self-evolve-status <run_id>`、`/self-evolve-resume <run_id>`。

铁律、门控序列、各档与锚的契约见 [`SKILL.md`](SKILL.md) 与 [`reference/`](reference/)。

## 研究溯源（调研原始数据已入库）

- 📄 [`docs/自改进Agent调研.md`](docs/自改进Agent调研.md) — 全景调研：方向定位、论文全清单、可复用开源仓库、缺口分析、护栏设计。
- 📄 [`docs/02-crossval-deepdive.md`](docs/02-crossval-deepdive.md) — market-intel 学术工具链交叉验证 + 2026 新论文深读（引用硬信号、ICLR 2026 RSI、14 篇新论文）；原始数据在 [`docs/data/`](docs/data/)（arXiv 扫描 XML + S2 引用 JSON）。
- 📄 [`docs/superpowers/specs/`](docs/superpowers/specs/) — 设计规格（铁律、反自欺机制）。
- 📄 [`docs/superpowers/plans/`](docs/superpowers/plans/) — 52 任务实施计划。
- 📄 [`docs/superpowers/SDD-progress-ledger.md`](docs/superpowers/SDD-progress-ledger.md) — 全程进度账本（每任务摘要 + 复查 + 终审）。

## 核心设计风险（来自调研，已由架构闭合）

被优化对象是**无 ground-truth 的开放生成任务**时，叠加「自出题 + 自评分」的 self-judge
结构按文献几乎注定产出虚假上升曲线。本项目的全部反自欺机制（见上表）正是为闭合此风险
而设计；详见调研报告 §5–§7 与设计规格。

## 直接复用 / 思路来源

GEPA（反思 + 遗传 + Pareto）、OpenEvolve（AlphaEvolve 开源复现）、OpenSkill（从外部抽
verification anchor）、MOSS（重放 + health-probe 回滚）、meta-agent-challenge（防
reward-hacking harness）、PACE（anytime-valid acceptor）、edgartools（EDGAR 外部真值源）。
