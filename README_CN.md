# self-evolve

对 skill 或仓库提出修改，在隔离工作树中评测，再按证据决定是否采纳。通过一道检查，只能证明这道检查实际测到的能力。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-local%20suite-blue?style=flat)](tests/)
[![Anti-self-deception](https://img.shields.io/badge/acceptance-evidence%20gates-blue?style=flat)](SKILL.md)
[![语言](https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-EN%20%2F%20CN-blue?style=flat)](#语言)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ 先读这个, 设计理念

文献里的自改进 agent 几乎都只在**可验证域**成功, 代码、数学、一切有 ground truth 的地方。真正难、被普遍跳过的是**无 ground-truth 的开放生成域**：你可以宣称「我改进了」，却无法核验。再叠加「自出题 + 自评分」的 self-judge 结构，按文献几乎注定产出**虚假上升曲线**：分数涨，能力不涨。

self-evolve 正是为填这块真空白而生。核心立场：

- **方法论恒定，信号来源自适应。** 闭环永远是 `reflect → propose → evaluate → judge → accept`；唯一随目标变的是「评测信号从哪来」。
- **先确认评测证据。** 优先使用 A 程序裁决或 B 独立事实核验。C 可消费已有的回归与一致性证据；自动生成场景尚未实现。缺少证据不能算改进。
- **LLM 提议，代码裁决。** 采纳 / 拒绝 / 回滚 / 定信号源全由 harness 确定性代码决定，LLM 绝不评判自己产出。
- **让采纳结论有据可查。** 记录候选哈希、测试、事实来源和实际 provider；按各项检查的覆盖范围解释结果。

完整理念：[`docs/philosophy.md`](docs/philosophy.md) · 设计规格与原理见 [`docs/superpowers/`](docs/superpowers/)。

## 这是什么（不是什么）

一个**方法论 skill + 轻量确定性 harness**，让 agent 在 `git worktree` 沙箱内多轮自动改进任意 skill / 仓库 / 项目，配确定性的采纳检查。它属于 **Self-Evolving / Self-Improving Agents** 家族里「agent 自动改进自己的 skill / scaffolding」一支，思路上缝合 **DGM + SICA + MARS + OMNI + PACE**，并针对文献缺失的「无 ground-truth 开放生成域」补齐护栏：verification-anchor + anytime-valid acceptor + 异构 judge + 对抗式协同进化。

它**不是**一键「把我的仓库变好」的魔法按钮，也**不是**替你落地改动的工具。全自动的部分都在沙箱里发生；出沙箱的任何动作（push / 合主分支 / 对外发送）都走独立的人审子流程。

**采纳检查：**

| candidate 自欺路径 | 防御 |
|---|---|
| 改 grader / judge 自评 | IMMUTABLE 决策码清单 + frozen 物化 + 启动哈希 fail-closed + patch 硬拒门 + supervisor 双进程裁决（candidate 永不进 `sys.path`、不裁决 / 不评分自己） |
| 塞无法核验的"锚" | `verify_anchor`（EDGAR 程序化核查）+ `marginal_gain` 未核验恒 0 |
| holdout 过拟合 | prompt 排除 holdout 真值；文件读取隔离须另行验证部署边界+ 确定性拆分 + 背离闸 + 累计漂移预算 |
| judge 合谋 | 根据实际返回 provider 判断已知且不同的家族+ `pairwise_agreement` + judge↔锚校准（只用 holdout 锚） |
| 相关锚虚高 e-value | `effective_independent_count` 同源去相关（8→4）+ 独立性下限门 |
| 出站隐蔽信道 exfil | proxy harness 代发（candidate 无 URL 构造权）+ 熵 / 编码 / 序列异常审查 |

## 安装

```
/plugin install github:DaizeDong/self-evolve
```

或手动 clone：

```bash
git clone --recursive https://github.com/DaizeDong/self-evolve.git ~/.claude/plugins/self-evolve
```

## 快速开始

先按下文配置私有伴生仓，再从 skill 仓库对有 Git 历史的目标运行：

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

默认 `builtin` / `serial` 使用提供的确定性证据。业务测试运行
`python -m pytest tests`，共享守卫另测。`--live` 使用已安装的
`llmcall.call(..., mode="agent")` 生成提议和反思，judge 使用默认模式。
路由、模型、超时和回退策略均由 llmcall 决定，指定别名不能证明评审独立。
agent 每次使用私有伴生仓中的独立临时目录，调用后清理，调用者 cwd 不变。

## 配置与首次诊断

将 `SELF_EVOLVE_CONFIG` 指向已有的 PRIVATE Git 伴生仓，或将
`SELF_EVOLVE_DATA_DIR` 指向其中的绝对目录。真实产物在私有仓中版本化。
写入前检查 GitHub origin 和 `~/.pii-guard/visibility.json` 中的 PRIVATE 记录；
`_refreshed` 必须带时区且不早于 30 天。缺失、过期、公开或未知的证明都会阻止写入。
新建伴生仓或改变其可见性后，先刷新 fleet 的可见性记录。

在 skill 仓库运行 `python -m tools.sie.cli doctor --target <target>`，再执行 `init`。
从其他目录或安装别名启动时，用
`python <skill绝对路径>/tools/sie_cli.py doctor --target <target>`，其他子命令同样支持。
doctor 只报告本地配置与能力，不调用模型，不创建运行目录。

普通目标与 `--self` 的记录都存入私有数据根目录，按目标规范路径分别建命名空间。
`init` 返回实际路径；公开目标下不会创建运行产物。run ID 必须是单个非空路径段。
无记录时，`status` 和 `replay` 明确报告未初始化。独立 cwd 不能代替防范恶意绝对路径
写入的操作系统沙箱。profile 可识别 A+B，但当前执行会拒绝该组合，直到两路采纳条件都得到支持。
B 评测保留全部冻结身份与跨度；抽检 holdout 必须有固定内容哈希和独立核验结果。
自举的修改、评测与归档快照使用同一候选树。


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
