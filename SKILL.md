---
name: self-evolve
description: "Improve an existing skill or repository through isolated proposals, reproducible evaluation and evidence-based acceptance. Use for self-evolve or skill improvement."
---

# self-evolve

在 Git worktree 中提出修改、运行评测，再按证据决定是否采纳。
先明确目标和可执行判据；通过检查只证明所测范围。

## 开始前

1. 确认目标仓库、基线 revision、允许修改的范围和期望改善的行为。
   记录文档影响；无需修改的文档也说明原因。设计理由见 [PHILOSOPHY.md](PHILOSOPHY.md)。
2. 确定评测信号：A 为测试结果，B 为独立事实核验，C 为已提供的主观证据。
   主循环尚无 C 回归与一致性测量生产者，也不执行 A+B 组合。
3. 按 [DATA.md](DATA.md) 配置 PRIVATE 伴生仓，保留真实运行证据。
4. 运行 `python <skill-path>/tools/sie_cli.py doctor --target <target>`，
   阅读配置和能力缺口。doctor 不调用模型，退出零不能单独证明就绪。

## 工作流

| 步骤 | 要做的事 |
| --- | --- |
| PROFILE | 实现前冻结评测策略、目标契约与留出集；续跑沿用原契约 |
| REFLECT | 从已有记录形成诊断，核对引用；结构检查不等于事实核验 |
| PROPOSE | 提出允许范围内的修改，保留实际 provider 和失败原因 |
| PATCH | 在候选工作树应用提案，执行路径、AST 与 IMMUTABLE 检查 |
| EVALUATE | 用相同口径测量父代和候选，保留任务身份及不可用原因 |
| ACCEPT / REVIEW | 由代码处理证据与门控，归档采纳版本或记录拒绝、人审原因 |

**LLM 只提议，代码裁决。** agent 使用已安装的
`llmcall.call(prompt, mode="agent")`，文本 judge 使用默认模式。
继承其路由、模型、超时和回退策略，不另设 provider 链。
只有实际返回的已知不同家族才能支持独立评审结论。

## 运行与恢复

```bash
python <skill-path>/tools/sie_cli.py init --target <target>
python <skill-path>/tools/sie_cli.py run --target <target> --run-id <id> --base-ref HEAD
python <skill-path>/tools/sie_cli.py status --target <target> --run-id <id>
```

默认 `builtin` 将已提供的修复转成提案，不会自主发现修复。
模型提案使用 `--live`，JSON 产物使用 `--proposer llm-artifact`。
续跑复用 run ID；`--max-rounds` 是本次调用的额外轮数。
参数、自举和恢复语义见 [runtime](reference/runtime.md)。

## 接受与交付

- 沙箱与私有目录不等于操作系统权限隔离；真值不进入提案 prompt。
- 缺少基线、回归记录、核验结果或独立 provider 时，明确报告缺口。
- 没有回归或测试全绿不单独构成改进；按 [evaluation](reference/evaluation.md) 解释证据。
- 人审队列记录待审动作；发布、合并和对外发送仍按已有授权单独执行。
- 评审前完成实现、文档和已获授权的版本更新，再冻结准确的候选快照。
  这不改变实现前的评测冻结；评审后改动须重新检查受影响部分。流程见 [maintenance](reference/maintenance.md)。
- 交付候选差异、源码版本、实际测量、采纳原因、未覆盖范围和运行状态。
  统计解释须满足 [acceptor_math](reference/acceptor_math.md) 的假设。

按需加载上述参考，不读取历史研究资料来代替当前实现和测量。
