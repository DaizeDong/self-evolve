# /self-evolve-resume

以同一目标和 run ID 续跑，沿用冻结的目标契约与已有事件。

```text
/self-evolve-resume <run_id> --target <target>
```

```bash
python <skill-path>/tools/sie_cli.py run --target <target> --run-id <run_id> --base-ref <original-ref>
```

沿用原来的自举、提案和反思选项；`--max-rounds` 是本次调用的额外轮数。
主循环从事件恢复轮次、反思记录、已采纳版本及 holdout 测量进度，不重跑 PROFILE。

需要检查重建状态时：

```bash
python <skill-path>/tools/sie_cli.py replay --target <target> --run-id <run_id>
```

replay 输出从事件重建的状态，不写回 state.json。无需先删除状态文件。
暂停、失败和待审原因仍须处理；续跑本身不代表问题已解决。
详情见 [runtime](../reference/runtime.md#resume-and-recovery)。
