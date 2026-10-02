# propose：把诊断转成候选修改

上游 reflect 和 check_reflection 提供 findings，propose 返回完整文件的新内容。
后续 patch 决定能否写入，evaluate 与 acceptor 决定能否采纳。模型输出本身不具备采纳权限。

## 当前后端

| `backend` | 行为 | 无可用模型提案时 |
| --- | --- | --- |
| `builtin` | 将 reflection 中已有的 `file_rel` / `fix_content` 转为提案 | 缺少可用内容就没有提案 |
| `llm` | 根据已提供源码和 findings 请求 agent 生成修改 | 允许使用 builtin，并保留模型失败的诊断和 backend outcomes |
| `llm-artifact` | 请求修改已定位的结构化事实产物 | 不回退代码生成器，保留空结果与原因 |

入口为 `tools/sie/propose.py:propose(sandbox_root, reflections, backend="builtin")`。
builtin 适合可复现地驱动流程，它不会自主发现新修复。

## Agent 传输与返回值

`backends/llm.py` 收集允许修改的输入，构建结构化 prompt，通过 `llm_adapter.invoke_agent`
调用安装的 llmcall。Python agent child 使用独立 PRIVATE 临时 cwd，父进程不改变 cwd。
模型、路由、超时和 fallback 继承当前 llmcall 策略；旧 JavaScript 启动器已禁用。
传输及错误契约见 [runtime](runtime.md)。

代码提案只能命名已提供的文件，`new_content` 必须是非空的完整文本。结果用
`ProposalBatch` 保留 `backend_outcomes` 与 `diagnostics`。调用失败、不可解析结果、
错误路径和缺失内容分别记录原因，不能把这些空结果当作成功审查。

## 结构化产物

`generate_artifact` 选择输入产物，检查路径、大小和 JSON 结构。`llm_adapter.strip_truth`
在构建 prompt 时递归删除核验真值字段。提案须保持目标路径和 `sections` / anchors 结构，
数值事实还须包含可用的 metric、cik、period 和有限 numeric expected。

Python 校验保留原锚数量与数值查找身份的 multiplicity，拒绝删除、替换或重复原有身份。
合法结构不能证明事实为真，实际正确性仍交给 B 路独立核验。
prompt 过滤不代表共享账户下文件在操作系统层面不可读。

## 与下游衔接

每个提案包含 `file_rel`、`new_content` 和来源信息。`patch.apply_patch` 检查路径、
IMMUTABLE、导入和静态危险调用。静态规则覆盖已识别的语法形态，不证明任意 Python
间接调用或文件系统竞态都受到隔离。

空提案由主循环记录为 `STATIC_REJECT` 并进入后续循环或熔断判断；有提案也仍须完整评测。
PRIVATE 写入失败必须传播，不能通过吞掉错误或退回公开仓保存来继续。

实现入口：`propose.propose`、`backends.builtin.generate`、`backends.llm.generate`、
`generate_artifact`、`llm_adapter.invoke_agent`、`patch.apply_patch`。
