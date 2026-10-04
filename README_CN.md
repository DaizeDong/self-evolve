# self-evolve

对 skill 或仓库提出修改，在 Git worktree 中评测，再按证据决定是否采纳。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](README.md)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.0-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

## ⭐ 先读这里

提出修改前，先确定怎样衡量改进。模型提出建议，确定性代码检查证据并决定是否采纳。
没有取得的观测就报告不可用。通过一道检查，只能证明这道检查实际测到的范围。

流程为 `profile → reflect → propose → patch → evaluate → accept or review`。
采纳的候选会归档，供后续审查。发布、合并和对外发送是独立动作，按调用方获得的授权处理。

## 安装

克隆仓库时一并获取固定版本的 guard 和 style 子模块：

```bash
git clone --recursive https://github.com/DaizeDong/self-evolve.git
```

技能入口是 [SKILL.md](SKILL.md)，命令适配器位于 [commands/](commands/)。
从其他目录或安装别名启动时，使用 `tools/sie_cli.py` 的绝对路径。
业务测试运行 `python -m pytest tests`。

## 配置

将 `SELF_EVOLVE_CONFIG` 指向已有的 PRIVATE Git 伴生仓，或将
`SELF_EVOLVE_DATA_DIR` 指向其中的绝对目录。运行写入必须有有效的 PRIVATE
目标证明；证明缺失、过期、公开或未知都会阻止写入。
存储与保留规则见 [DATA.md](DATA.md)，前置条件见
[运行配置](reference/runtime.md#configuration)。

模型调用继承已安装 `llmcall` 的路由、模型、超时和回退设置。
agent 使用 `mode="agent"`，文本 judge 使用默认模式。
评审是否独立要看实际返回的 provider，请求时使用不同别名不能证明独立。

## 使用

从仓库目录检查前置条件、初始化，再运行：

```bash
python -m tools.sie.cli doctor --target <target>
python -m tools.sie.cli init --target <target>
python -m tools.sie.cli run --target <target> --run-id <id> --base-ref HEAD --max-rounds 3
python -m tools.sie.cli status --target <target> --run-id <id>
```

阅读 doctor 的 JSON，包括 `private_data.available`；退出码为零不能单独证明就绪。
目标需要 Git 历史和可用评测证据。默认 `builtin` 使用已提供的修复内容生成提案。
添加 `--live` 可启用模型提案和并行反思；JSON 产物提案使用
`--proposer llm-artifact`。以同一 run ID 再次运行即可续跑。

完整参数、replay、rollback 和自举见 [CLI 与恢复](reference/runtime.md#cli)，
评测证据要求见 [Evaluation](reference/evaluation.md)。

## 当前限制

- A 衡量测试结果；所有配对结果都没有变化时，转交人审。
- B 独立核验冻结事实；合成锚只能验证机制。
- C 的 API 可以校验调用方提供的证据，但主循环没有回归或一致性测量生产者。
  自动场景生成尚未实现。
- PROFILE 可以识别 A+B，但主循环会在提案前拒绝执行该组合。
- `--mode gated` 不提供逐步人审。`--self` 支持 A 路评测。
- worktree、prompt 过滤和静态检查不能证明操作系统沙箱隔离。
- 统计保证依赖 [acceptor 数学说明](reference/acceptor_math.md) 中的假设；
  当前没有整次运行的错误概率上界证明。

## 文档

[Agent 工作流](SKILL.md) · [运行说明](reference/runtime.md) ·
[评测契约](reference/evaluation.md) · [数据](DATA.md) · [路线图](ROADMAP.md)

## 许可

[MIT](LICENSE)。版本记录见 [CHANGELOG.md](CHANGELOG.md)。
