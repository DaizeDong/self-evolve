# evaluate：取得可比较的观测

evaluate 把不同来源的证据交给对应接受路径。它须同时说明比较对象、实际观测及缺口，
不能用一个聚合分掩盖丢失的任务或事实。

## A 路测试

`evaluate(sandbox_root, tier="A", base_result=...)` 调用 `_grade_pytest_per_task`。
verbose pytest 的逐项结果转换为带名字的 dimensions；`task_passed` 仍取自退出码，
因此必须与逐项分一起解释。解析器的历史聚合兼容分支不等于证明所有测试都实际运行。

候选必须显式报告整数退出码 0、task_passed=True，以及非空、名字唯一且分数有限的 dimensions。
除旧的单一 pytest 聚合基线外，所有父代任务身份都必须保留。失败或不完整的候选返回
usable=False 和空 paired，并保留原始评分。普通 A 路与自举 A 路会在调用接受器前再次检查。

底层 `pair_parent_dimensions` 按父代任务 `name` 配对，候选缺失的父代任务 after 记零，
不会按列表下标把另一个任务对上。单个 `pytest` 旧聚合基线保留聚合语义。
直接调用 `evaluate` 时保留冷启动兼容行为；生产主循环先核验所选父代基线，
无法获得基线时记录 `BASELINE_UNAVAILABLE` 并暂停。

`grade_pytest` 保留聚合 `dimensions`，同时输出 `task_dimensions`。
自举 Supervisor 用后者取得逐任务数据，并与同一 frozen grader 得到的父代基线比较。
A 路 no-regression 之后仍须满足接受条件，不能把无退化等同于改善已证实。

## B 路事实

`build_btier_scores` 对冻结身份分别核验父代和候选；数值事实按 `(cik, metric, period)`
匹配。缺失、换键或重复匹配的候选 after 记零，保留 before 与原身份。
新增父代或候选事实不能改变本轮的冻结义务。

`_evaluate_btier(ctx)` 生成 `b_paired`、visible 增益、覆盖和抽检轮的 holdout 增益。
覆盖采用冻结 span 分母。B 以完整正负配对及净增益裁决，不提供 A 的逐项 no-regression 保证。

留出生产者先验证冻结路径、正整数数量、规范 JSON SHA-256 及与 visible 不重叠，
再对父代和候选实际核验。缺失、被改或没有有效观察时禁止该轮接受。
旧 profile 缺摘要须重新初始化。仅有 JSON 结构合法或来源 URL 不等于核验通过。

## C 路主观证据

`evaluate_c_tier` 消费已提供的 regression replay 与 consistency pairs。
两者都有效才能报告 `available=True`，并按 replay 判断 `no_regression`。
缺失或无效输入会报告对应证据不可用，不能把空集合视为通过。

当前主循环没有这两类测量生产者，传入空记录；`coverage=0.0`，
`scenario_eval="not_implemented"`。自动场景和 rubric 生成仍是设计目标。
因此纯 C 的真实效果需要另补测量与人工复核，不能通过历史决策记录推定。

## Judge 与隔离

`inject_judge_scores` 经 llmcall 的默认 judge 接口组织主观评分，并保留实际 provider。
兼容入口名不能证明两个家族独立；无有效独立结果时不能计算可信的一致性证据。
高一致度与事实改善背离是复核信号，不是合谋的事实结论。

grader 使用精简环境、PRIVATE 临时目录和 Python 网络限制。结构化 prompt 过滤真值。
这些机制保护特定调用路径，不能代替对操作系统文件权限、native 子进程和网络隔离的实测。

## 验收记录

结果应记录源码版本、基线、完整任务或事实身份、退出码、逐项观测、失败和不可用原因。
作者控制、原始完整回归、独立复审与真实使用分别报告。
详细字段见 [target_contract](../../reference/target_contract.md)，
接受规则见 [signal-providers](../../reference/signal-providers.md)。

实现入口：`evaluate.evaluate`、`pair_parent_dimensions`、`build_btier_scores`、
`_evaluate_btier`、`evaluate_c_tier`、`inject_judge_scores`、`verifiable.grade_pytest`。
