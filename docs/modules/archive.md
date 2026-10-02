# archive：保存已采纳版本

接受后，主循环为候选分配新版本 ID，保存业务树快照，再把版本和分数加入谱系。
下一轮可以按谱系和 Pareto 条件选择父代。谱系、快照、冷藏记录和恢复副本都属于
PRIVATE 伴生 Git 仓中的运行 DATA。

## 写入顺序与不变量

`archive.next_version_id(run_dir)` 根据持久谱系选择新 ID，不能使用当前进程内
accepted 列表的长度代替它，否则恢复运行时可能复用旧 ID。

1. `snapshot_version(archive_dir, vid, sandbox_root)` 复制业务树到
   `versions/<vid>/snapshot`，排除 Git 元数据、缓存及内部运行目录。
   已存在的已采纳快照不能替换；该接口抛出 `FileExistsError`。
2. `add_version(run_dir, vid, scores, parent_vid)` 拒绝复用版本 ID，验证分数后追加谱系。
   它通过临时文件和 `os.replace` 写入完整 JSON；append-only 描述的是记录只追加的语义。
3. 主循环写入 ACCEPT 事件，保留版本与运行状态的联系。

这些步骤不是跨文件事务。崩溃可能留下尚未加入谱系的快照，需要保留证据并检查，
不能仅凭一个目录存在认定它已成功采纳。普通文件和原子改名也不构成抵抗同权限进程的不可篡改存储。

## 分数与读取

`score_schema: 1` 将 Pareto 坐标放在 `scores`，逐任务身份与测量放在 `task_dimensions`。
写入和读取都会验证有限数值、任务身份、权重以及坐标一致性；兼容的旧任务列表会按 tier
转换为坐标。读取支持普通 version list 和旧的 `versions` 包装，不把格式损坏当作空谱系。

A 保留逐任务记录供父代基线使用。B 的 anchor 坐标来自实际候选事实正确性。
缺少证据不能凭空补成正分。

## 父代、冷藏和回滚

`pareto_front` 使用 A、anchor 和 judge 坐标比较支配关系；`selectable_parents`
在前沿上应用硬维度中位数条件。缺失坐标按代码规定处理，不等于已观察到该维度。

`retire_stale` 把选出的冷藏记录追加到 `retired.jsonl`，不删除历史谱系或快照。
活跃版本筛选还取决于相应消费者是否使用冷藏记录，不能仅凭写入记录宣称已限制整个库的使用。

`rollback(archive_dir, vid)` 将指定快照恢复到 `archive/current`，缺快照时报错。
`current` 是可替换的恢复副本；它与不可覆盖的 `versions/<vid>/snapshot` 有不同契约。
CLI 的 rollback 不等于直接把用户工作分支或 candidate 改成某个 Git revision。

## 接口

| 函数 | 路径参数 | 结果 |
| --- | --- | --- |
| `add_version` | `run_dir` | 验证并追加谱系记录 |
| `snapshot_version` | `archive_dir`、`sandbox_root` | 创建一次性的已采纳快照 |
| `lineage` | `archive_dir` | 返回验证后的有序版本记录 |
| `pareto_front` / `selectable_parents` | `archive_dir` | 返回对应版本 ID 集合 |
| `retire_stale` | `archive_dir`、`active_cap` | 追加冷藏记录 |
| `rollback` | `archive_dir`、`vid` | 写入恢复副本 |

`add_version` 会自行拼接 archive 路径，`snapshot_version` 接收已经拼好的 archive 路径。
二者不可混传。实现见 `tools/sie/archive.py`、`business_tree.py` 和 `runtime_data.py`；
主循环衔接见 `statemachine.py` 的 ARCHIVE / ACCEPT 分支。
