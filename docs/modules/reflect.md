# reflect：从运行记录形成诊断

reflect 位于选择父代之后、提案之前。它消费已有 trace，指出具体问题和改善方向；
候选修改由 propose 生成。模型反馈经过结构校验后交给 check_reflection。

## Serial 路径

默认 `reflect` 不调用模型。有历史时复制最近一条记录，保留 summary 之外的
files_changed、decision、reason、phase 等字段；这些字段不能在消费者里丢失。
没有历史时列出非测试 Python 源文件，作为静态审查起点。这种初始化记录不是效果证据。

## Parallel 路径

`run_reflections_parallel` 为每个请求深拷贝 history，通过线程池执行 `_reflect_one`。
独立输入减少互相覆盖，但线程和 cwd 分离不能证明进程间文件不可读或模型来源独立。

函数默认 `n_reflectors=3`；生产调用方显式传入请求数量与 family 标签，不能固定宣称
每一轮都有三个独立模型。实际多样性要检查每次调用返回的 provider / family。

`_reflect_one` 对历史调用 `llm_adapter.strip_truth`，通过 `agents.invoke` 使用
当前安装的 llmcall agent 接口。每次调用保留 `ok`、实际来源、attempts 和失败原因。
返回 findings 必须是非空字符串列表；格式错误与合法空发现需要区别记录。
旧 `reflect-fanout.js` 和 provider CLI 启动链已禁用。

## 合并和检查

`meta_aggregate` 按输入顺序对 finding 文本去重，保留完整 backend outcomes 的深拷贝。
去重本身既不证明诊断正确，也不证明各调用独立。

主循环通过 `check_reflection.check` 检查反思结构。`check_benchtrace` 是可单独调用的
trace 引用核验接口，当前不能描述成已经接入主循环的强证据闸。
调用方需要确认 finding 引用与实际 trace 对应；仅通过结构检查不能宣称已完成接地验证。

## 数据与下一步

反思过程不改历史输入。模型调用的运行记录与临时 cwd 属于 PRIVATE 伴生仓 DATA；
不能因为 reflection 对输入只读，就宣称整个调用过程完全不产生运行记录。
主循环将合并结果交给 propose，并保留无结果、失败、暂停和熔断原因。

实现入口：`tools/sie/reflect.py:reflect`、`_reflect_one`、`run_reflections_parallel`、
`meta_aggregate`，以及 `tools/sie/check_reflection.py:check` / `check_benchtrace`。
调用策略见 [runtime](runtime.md)。
