# 测试结果与接受契约

grader 提供观测；evaluate 构造父代与候选的比较；acceptor 决定下一步。
返回一个合法字典、没有回归，或整个进程退出零，都不单独构成 ACCEPT。

## A 路 grader 字段

| 字段 | 含义 |
| --- | --- |
| `task_passed` | grader 对本次运行的整体判断；应结合退出码与逐项结果解释 |
| `grader_exit_code` | 测试进程退出码；基础设施失败、未收集到测试和超时不能当作有效通过 |
| `dimensions` | 带 `name`、`tier`、`score`、`weight` 的评分记录 |
| `task_dimensions` | `grade_pytest` 另外保留的逐任务记录，供 frozen supervisor 投影 |
| `anchors` | 事实锚记录；普通 A 路为空 |
| `verifiable_coverage` | grader 的覆盖字段，不是所有业务场景均已测试的证明 |

`grade_pytest` 保留兼容的聚合 `dimensions`，同时从 verbose pytest 输出解析
`task_dimensions`。普通 A 路的 `_grade_pytest_per_task` 直接提供逐项 `dimensions`。
两种结构要按各自消费者解释，不能拿一个聚合分替代所有任务身份。

## 父代配对

`pair_parent_dimensions` 按 `name` 匹配任务。父代存在而候选缺失的任务仍进入比较，
其 after 分为零；新增候选任务不会替换原有义务。旧的单个 `pytest` 聚合基线保留
聚合语义，不能将它描述成逐任务证据。

主循环从所选父代的可用记录取得基线；无法证明基线可用时进入
`BASELINE_UNAVAILABLE` / `PAUSE_FOR_HUMAN` 路径。低层 `evaluate` 保留冷启动
和聚合兼容分支，直接调用这些分支不等于完成主循环的基线验证。

## 接受条件

`acceptor.decide(paired, tier, st, params)` 消费 before/after 配对。
A 路任一已通过任务退化会触发 no-regression 硬拒绝。没有退化后，仍须满足
当前统计接受条件和后续门控；“无退化即接受”的旧 M1a 说明不适用于当前实现。
A 路不使用 CONTINUE 累积接受，B、C 的规则见 [signal-providers](signal-providers.md)。
参数和数学定义见 [acceptor_math](acceptor_math.md)，实际默认值以代码为准。

## 自举与失败报告

自举时，基线和候选均由 frozen grader 取得相同口径的任务分，再交 frozen acceptor。
被修改的 candidate 不能通过提供另一份 grader 替代这条调用路径。
真实操作系统隔离仍须单独验证，见 [self-boot](../docs/modules/self-boot.md)。

C 路的 `available`、`regression_evidence` 和 `consistency_evidence` 必须与实际输入一致。
缺失记录不能生成 `no_regression=True`；scenario-eval 当前未实现。
B 路的数值、事实身份、覆盖分母和留出集核验见 [evaluate](../docs/modules/evaluate.md)。

实现入口：`tools/sie/verifiable.py:grade_pytest`、`tools/sie/evaluate.py:evaluate`、
`pair_parent_dimensions`、`tools/sie/statemachine.py:_parent_baseline` 和
`tools/sie/acceptor.py:decide`。
