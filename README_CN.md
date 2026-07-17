# self-evolve

指向任意 skill / 仓库 / 项目，让 agent 自我迭代它, 用不可 game 的接受门保证「被采纳 = 真改进」，而非分数涨、能力不涨的虚假上升曲线。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-521%20passing-green?style=flat)](tests/)
[![Anti-self-deception](https://img.shields.io/badge/anti--self--deception-6%20paths%20closed-green?style=flat)](SKILL.md)
[![语言](https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-EN%20%2F%20CN-blue?style=flat)](#语言)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这个, 设计理念

文献里的自改进 agent 几乎都只在**可验证域**成功, 代码、数学、一切有 ground truth 的地方。真正难、被普遍跳过的是**无 ground-truth 的开放生成域**：你可以宣称「我改进了」，却无法核验。再叠加「自出题 + 自评分」的 self-judge 结构，按文献几乎注定产出**虚假上升曲线**：分数涨，能力不涨。

self-evolve 正是为填这块真空白而生。核心立场：

- **方法论恒定，信号来源自适应。** 闭环永远是 `reflect → propose → evaluate → judge → accept`；唯一随目标变的是「评测信号从哪来」。
- **能跑就跑，能核就核，都不能就生成场景让异质判官评, 所以没有不能进化的目标。** 三个信号 provider（A 程序裁决、B 锚核验、C 生成评测）实现同一 `evaluate` 契约；往上尽量取，取不到向下兜底, 底永远存在。
- **LLM 提议，代码裁决。** 采纳 / 拒绝 / 回滚 / 定信号源全由 harness 确定性代码决定，LLM 绝不评判自己产出。
- **反自欺是全部目的。** 六条具体作弊路径全部闭合（见下表）,因为在长时间全自动循环里，「被采纳」必须意味着真，而非自我恭维。

完整理念：[`docs/philosophy.md`](docs/philosophy.md) · 设计规格与原理见 [`docs/superpowers/`](docs/superpowers/)。

## 这是什么（不是什么）

一个**方法论 skill + 轻量确定性 harness**，让 agent 在 `git worktree` 沙箱内多轮自动改进任意 skill / 仓库 / 项目，配一个不可 game 的提交门。它属于 **Self-Evolving / Self-Improving Agents** 家族里「agent 自动改进自己的 skill / scaffolding」一支，思路上缝合 **DGM + SICA + MARS + OMNI + PACE**，并针对文献缺失的「无 ground-truth 开放生成域」补齐护栏：verification-anchor + anytime-valid acceptor + 异构 judge + 对抗式协同进化。

它**不是**一键「把我的仓库变好」的魔法按钮，也**不是**替你落地改动的工具。全自动的部分都在沙箱里发生；出沙箱的任何动作（push / 合主分支 / 对外发送）都走独立的人审子流程。

**反自欺主线（六路径全闭合）：**

| candidate 自欺路径 | 防御 |
|---|---|
| 改 grader / judge 自评 | IMMUTABLE 决策码清单 + frozen 物化 + 启动哈希 fail-closed + patch 硬拒门 + supervisor 双进程裁决（candidate 永不进 `sys.path`、不裁决 / 不评分自己） |
| 塞无法核验的"锚" | `verify_anchor`（EDGAR 程序化核查）+ `marginal_gain` 未核验恒 0 |
| holdout 过拟合 | holdout 真值物理隔离（铁律 5）+ 确定性拆分 + 背离闸 + 累计漂移预算 |
| judge 合谋 | 异构 judge（Claude + Codex，强制不同模型家族）+ `pairwise_agreement` + judge↔锚校准（只用 holdout 锚） |
| 相关锚虚高 e-value | `effective_independent_count` 同源去相关（8→4）+ 独立性下限门 |
| 出站隐蔽信道 exfil | proxy harness 代发（candidate 无 URL 构造权）+ 熵 / 编码 / 序列异常审查 |

## 安装

```
/plugin install github:DaizeDong/self-evolve
```

或手动 clone：

```bash
git clone https://github.com/DaizeDong/self-evolve.git ~/.claude/plugins/self-evolve
```

## 快速开始

对任意有 git 历史的目标仓库启动一次自迭代 run（沙箱内全自动）：

```bash
# 初始化一次 run（取 run_id）
python -m tools.sie.cli init   --target <目标仓库绝对路径>

# 跑闭环
python -m tools.sie.cli run    --target <目标> --run-id <id> --base-ref HEAD --max-rounds 3

# 查看 / 恢复
python -m tools.sie.cli status   --target <目标> --run-id <id>     # 查看状态
python -m tools.sie.cli replay   --target <目标> --run-id <id>     # 崩溃后从 events 重建
python -m tools.sie.cli rollback --target <目标> --run-id <id> --vid <vid>

# 自举（改 self-evolve 自身，开 IMMUTABLE enforce）
python -m tools.sie.cli run --target <self-evolve 自身> --run-id <id> --self --enforce-immutable
```

默认 `builtin` / `serial`（确定性，521 测试用，不调外部）。`--live`（= `--proposer llm --reflect-mode parallel`）开真 agent 闭环：proposer / reflector / 两个 judge 走本机 `cc` 网关（split-billing，fallback `claude`）+ `codex` CLI。

## 如何调用

斜杠命令（需先把本仓库部署到 `~/.claude/skills/self-evolve`，例如用 junction）：

```
/self-evolve <target>            # 对目标启动一次自迭代 run
/self-evolve-status <run_id>     # 查看 run 状态
/self-evolve-resume <run_id>     # 从已有 run 续跑
```

铁律、门控序列、各档与锚的契约见 [`SKILL.md`](SKILL.md) 与 [`reference/`](reference/)。

## 示例输出

闭环是 10 态门控状态机，收敛成六个直觉动词：

```
              ┌──────────────────── 一次迭代 ────────────────────┐
  PROFILE ──► REFLECT ──► PROPOSE ──► PATCH ──► EVALUATE ──► JUDGE ──┐
  (定信号源)  (读历史)   (出方案)   (落沙箱)  (取信号)   (码裁决)  │
     │                                                 accept/reject/rollback
     └────────────────────◄── LOOP ◄────────────────────────────────┘
                                │  命中自欺/熔断 → PAUSE(人审) → STOP
```

采纳的版本进 archive lineage；出沙箱的任何动作走人审。示例 run 见 [`examples/`](examples/)。

## 局限

- 纯 A 档自动 ACCEPT 需「改后更多测试通过」的改进空间, 绿基线无此空间（按设计），真正的开放域改进信号在 B / C 质量档。
- 当前代码对纯主观 C 仍取保守处理（`coverage=0`、权重偏低、默认人审）；A/B↔C 的 accept 端平权是 scenario-eval 模块的设计 / 落地方向，尚未完全落地。
- 全自动的部分都在沙箱内；落地动作（push / 合并 / 对外发送）永远需要人审子流程。

## 语言

English（[`README.md`](README.md)，权威版本）· 中文（`README_CN.md`）

## Roadmap · 更新日志 · 许可

见 [ROADMAP.md](ROADMAP.md) · [CHANGELOG.md](CHANGELOG.md) · [LICENSE](LICENSE)（MIT）。

姊妹 skill：[market-intel](https://github.com/DaizeDong/market-intel), [`docs/02-crossval-deepdive.md`](docs/02-crossval-deepdive.md) 的学术工具链交叉验证喂给了本项目的护栏设计。
