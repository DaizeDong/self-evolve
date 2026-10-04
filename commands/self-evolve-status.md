# /self-evolve-status

查看现有运行的状态。除 run ID 外，还需同一目标路径；没有上下文时先取得目标。

```text
/self-evolve-status <run_id> --target <target>
```

```bash
python <skill-path>/tools/sie_cli.py status --target <target> --run-id <run_id>
```

run ID 使用 init 返回值，或初始化时指定的单个非空路径段。
JSON 包含 phase、round、tier、三个计数器、archive Pareto 前沿和待审动作。
读取 state 快照不等于重新评测候选。

没有运行记录或私有数据根不可用时，命令可返回 `status: uninitialized`
并退出零；须查看返回原因。该命令不修改运行状态。
恢复说明见 [runtime](../reference/runtime.md#resume-and-recovery)。
