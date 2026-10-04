# /self-evolve

对目标启动一次运行。目标必须有 Git 历史、可用评测证据和 PRIVATE 伴生仓。

```text
/self-evolve <target>
```

从安装目录使用绝对入口：

```bash
python <skill-path>/tools/sie_cli.py doctor --target <target>
python <skill-path>/tools/sie_cli.py init --target <target>
python <skill-path>/tools/sie_cli.py run --target <target> --run-id <id> --base-ref HEAD
```

先检查 doctor 的 JSON，再使用 init 返回的 run ID。
默认使用已提供的确定性修复；`--live` 启用模型提案与并行反思，
`--proposer llm-artifact` 处理 JSON 产物。

输出包含运行目录、采纳版本和最终状态。退出零不等于有改进。
模型提出建议，代码裁决；对外动作按已有授权单独处理。
完整参数与能力限制见 [runtime](../reference/runtime.md) 和
[evaluation](../reference/evaluation.md)。
