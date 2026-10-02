# self-boot：用冻结基线评测自身

`--self` 用于改进 self-evolve 自身。初始化先建立 canonical candidate worktree，
再从指定 Git base ref 物化 frozen 决策代码，交给 Supervisor 使用。
候选文件可以被修改，负责判定的那份代码则必须与冻结摘要一致。

## 初始化与调用路径

1. 校验 run ID 和 PRIVATE 运行目录，创建 `self__<run_id>` candidate worktree。
2. `materialize_frozen` 从 Git base ref 读取所需决策文件，生成冻结副本与摘要。
   权威文件集合是 `immutable.py:IMMUTABLE_RELPATHS`，不在文档中另抄固定数量。
3. `verify_immutable` 检查摘要集合和 candidate 对应文件。缺失、改动或不完整基线会失败。
4. `candidate_path_is_isolated` 检查 Supervisor 的模块解析路径，防止选择到 candidate。
5. 创建 `Supervisor`，主循环使用同一个 candidate 完成修改、评测和快照。

`selfboot_init` 返回 `candidate_worktree`、`frozen_dir`、`frozen_digests` 和 `supervisor`。
主循环在自举评分前再次核对 patch 与 grade 的 candidate 路径一致。
它不会另外建立一棵普通候选树，再把另一棵树交给 frozen grader。

## Frozen grader 与任务身份

`Supervisor.grade(..., self_mode=True)` 调用 frozen `verifiable.grade_pytest`，
将被测 worktree 作为输入；`task_dimensions` 供 Supervisor 投影成逐任务维度。
父代基线也使用同一个 frozen grader。后续按任务身份配对，删除的父代任务仍保留并记零。
`Supervisor.decide` 使用 frozen acceptor；`self_mode=False` 不能误用自举 grade 接口。

结果中的 `graded_by` 标记用于说明该调用路径。完整验收仍须核实实际加载文件、摘要、
逐任务人口和执行结果，不能仅凭一个字符串标记认定隔离有效。

## 保护的范围

IMMUTABLE、按路径加载、摘要检查和独立工作树保护指定的决策代码与模块解析路径。
它们不建立独立操作系统身份。共享账户可能拥有修改只读文件权限或访问旁边目录的能力；
`chmod`、Python 检查与不加入 `sys.path` 不能单独证明候选物理上不可读写 frozen / holdout。

运行 DATA、frozen 副本及候选工作树必须位于验证为 PRIVATE 的伴生 Git 仓。
禁止在公开工具仓内提供运行目录 fallback。需要抵抗不可信 native 代码时，须另行验证
操作系统权限、进程和网络边界，再报告实测范围。

实现入口：`selfboot.selfboot_init`、`immutable.materialize_frozen`、`verify_immutable`、
`supervisor.load_frozen_decider`、`candidate_path_is_isolated` 和 `Supervisor`。
信号契约见 [signal-providers](../../reference/signal-providers.md)。
