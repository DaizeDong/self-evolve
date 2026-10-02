# 评测信号参考

PROFILE 首轮冻结证据来源。A、B、C 是不同评测路径，其可用性要依据当前生产者和
消费者一起判断。配置里出现一个标签，不代表该路径已有完整观测。

| 路径 | 当前信号 | 接受时的重要条件 |
| --- | --- | --- |
| A | 测试结果与父代任务配对 | 基线可用、无已通过任务退化、统计接受条件满足 |
| B | 独立核验的冻结事实 | 完整身份和配对、覆盖、有效独立锚、留出及自欺检查 |
| C | 已提供的回归、一致性和实际 judge 结果 | 观测可用、无已测回归、judge 家族证据及人工复核门 |

主循环对 A+B 在 PROFILE 后、提案与修改前明确报错。含 B 的其他组合标签按 B 分派，
不能据此宣称所有组成路径都已执行。自动场景生成 scenario-eval 尚未实现。

## A：程序测试

普通执行通过 `_grade_pytest_per_task` 得到逐任务结果；`pair_parent_dimensions`
按父代任务名配对，候选缺失的父代任务记零。旧聚合基线保留聚合语义。
自举通过 frozen `grade_pytest` 的 `task_dimensions` 取得同口径数据。

no-regression 拒绝已通过任务退化，其后仍要满足 e-process 接受条件。A 不使用 CONTINUE。
低层 grader 的聚合兼容分支和 `verifiable_coverage` 数值不能代替完整测试人口的核验。
变异校验还须区分被测失败与测试基础设施错误；没有可用观测时保留不可用原因。

## B：事实核验

`build_btier_scores` 从冻结的可见身份取得父代与候选的事实，分别核验并生成 before/after
正确性配对。数值事实按 `(cik, metric, period)` 匹配。缺失、重命名或歧义候选仍保留
原身份，after 记零；新增事实不能替换冻结的比较义务。

`_evaluate_btier` 汇总 `b_paired`、`visible_anchor_gain`、`coverage` 和抽检轮的
`holdout_gain`。覆盖按冻结的 span 分母计算。B 保留正负变化，并按净增益及专属门裁决，
没有 A 路逐项 no-regression 的保证。

留出观测要求冻结路径、正整数数量和规范 JSON SHA-256；来源被改、为空、与 visible
重叠或实际核验不可用时，不能批准该轮。旧 profile 缺摘要时需要重新初始化。
有效独立锚按同源簇折算，相关事实不能仅靠增加行数充当独立证据。

`resolve_accept` 组合锚下限、有效独立性、e-process、覆盖和自欺信号。
可见增益与留出或 judge 背离时可能拒绝、暂停或增加漂移计数。阈值依运行参数及代码，
数学约束见 [acceptor_math](acceptor_math.md)。

## C：已有主观证据的消费

`evaluate_c_tier(artifact_path, regression_replay, internal_consistency)` 校验调用方
提供的回归记录和有限、位于允许范围的配对。两者都可用时，才能据 replay 判定
`no_regression`。它同时报告 `available`、两类证据状态和 `scenario_eval`。

当前主循环没有回归回放和一致性测量生产者，传入的两组数据为空，因此这些观测仍不可用。
`coverage` 为零，纯 C 默认交人工复核。历史 ACCEPT 记录不能替代对当前候选重新测量。
[scenario-eval](../docs/modules/scenario-eval.md) 描述设计目标，不能作为已经能自动
生成场景、rubric 和完整覆盖的使用指令。

## Judge 与模型调用

agent 经安装的 `llmcall.call(..., mode="agent")`；文本 judge 使用其默认 judge 模式。
继承当前路由、模型、超时和 fallback 策略。`claude`、`codex` 等兼容入口名本身
不能证明实际模型来源不同，须检查返回的 provider、family、attempts 和失败原因。

`inject_judge_scores` 组织 judge 结果。只有有效且来自已知不同家族的结果，才能用作
相应独立性与一致性判断。高一致度同时缺少事实改善只是复核信号，不是合谋的事实证明。

## 隔离、持久化与收敛

结构化 prompt 排除核验真值；单独目录、工作树、线程或 Python 网络限制不等于
操作系统权限隔离。所有运行 DATA 写入经验证的 PRIVATE 伴生 Git 仓。
暂停、拒绝、来源不可用和熔断原因都须保留；释放阀只调整人工复核频率，不降低接受阈值。

运行结果应分别报告源码版本、实际测试及事实人口、失败与缺口、是否独立复审和是否真实运行。
一轮 ACCEPT 或局部 green 不能代表整个技能已经收敛。
