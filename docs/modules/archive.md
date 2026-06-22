# archive — 版本档案 / 谱系 / 快照 / 回滚 / 库漂移

## 职责（在 pipeline 中的位置）

self-evolve 的主循环是 **reflect → propose → evaluate → judge → accept**，全程贯穿反自欺闸门。archive 是这条链最末端 **accept** 之后的"落盘与记账"环节：当裁决判定一个候选版本被接受（状态机进入 `ARCHIVE`），archive 负责把这个版本永久记入谱系、把它当时的整棵沙箱代码冻成快照，从此它就成了后续轮次可被选为"父版本"的候选之一。

archive 同时是循环**反向回头**时的依赖：

- **谱系（lineage）**：append-only 的版本族谱，记录每个版本的 id、父版本、各维度得分。只追加、不改写、不重排——这是"演化历史不可篡改"的物理保证。
- **快照（snapshot）**：每个被接受版本的整树代码冷冻一份，使任何历史版本都能被原样复活。
- **回滚（rollback）**：当新版本走歪（退化、塌缩），把某个历史版本的快照还原成 `current`，让演化从一个已知良好的点重新出发。
- **多维 Pareto 硬维门（selectable_parents）**：决定"哪些历史版本有资格被选作下一轮的父版本"。不是单一分数取最高，而是多目标 Pareto 前沿 + 硬维度中位数门槛，专门挡住"只靠软分（裁判主观打分）虚高、硬指标（客观可验证）拉胯"的伪赢家。
- **库漂移 retire_stale**：当活跃版本数超过上限时，把陈旧版本"冷藏"（写进 `retired.jsonl`），而**不是删除**——谱系本体永不被动手。

简言之：accept 之后由 archive 记账与存档；下一轮 propose 选父版本时由 archive 的硬维门做"准入"；循环跑久了由 archive 的库漂移做"瘦身但不失忆"。

## method

### 目录结构

archive 把所有状态都挂在 run 目录下的 `archive/` 子目录里（`_arch_dir` 在写入时按需创建）：

```
<run_dir>/archive/
  lineage.json            # 谱系，纯 JSON 列表，append-only
  retired.jsonl           # 冷藏记录，一行一条 JSON
  versions/
    <vid>/
      snapshot/           # 该版本整树代码的冷冻副本
  current/                # rollback 还原目标（被覆盖）
```

### 谱系：只追加，永不改写

`add_version` 是唯一的写谱系入口。它做三件事：

1. 确保 `archive/versions/<vid>/` 目录存在；
2. 读出当前完整谱系（`lineage`），在末尾 append 一条新记录 `{"vid", "parent_vid", "scores"}`；
3. 把整个列表先写到 `lineage.json.tmp`，再用 `os.replace` 原子改名覆盖正式文件。

用"先读全量、append、原子改名重写整文件"而非"原地追加一行"，是刻意的：原子改名保证任何时刻读到的 `lineage.json` 要么是旧的完整版、要么是新的完整版，不会读到半截。**append-only 是语义契约**——条目只增不删、不重排序，这一点由调用约束（只有 `add_version` 写它，且只 append）共同保证。`_load_versions` 兼容两种磁盘格式：纯 list（`add_version` 写出的格式）和 `{"versions": [...]}` 的旧/备用格式。

### 快照：整树冷冻，可复活

`snapshot_version` 把当前 `sandbox_root` 整棵目录拷进 `versions/<vid>/snapshot/`，忽略 `.git`、`__pycache__`、`.sie` 三类目录。已存在则先删后拷（幂等替换）。这一份是该版本的"标本"——回滚就靠它。

### 回滚：从已知良好点重启

`rollback(archive_dir, vid)` 把 `versions/<vid>/snapshot/` 拷进 `archive/current/`（已存在先删）。若该 vid 没有快照，抛 `FileNotFoundError`——拒绝静默回滚到不存在的版本。CLI 的 `rollback` 子命令直接转调它。

### 多维 Pareto 前沿

`pareto_front` 计算"没有被任何其他版本支配"的版本集合。维度分两类：

- **硬维度** `_HARD_DIMS = ("A", "anchor")`：客观可验证的指标——A 是评测策略给出的客观分，anchor 是冻结锚点上的回归分。这两个不靠主观判断，作弊空间小。
- **软维度** `_SOFT_DIMS = ("judge",)`：裁判主观打分，作弊空间大（容易被"讨好裁判"的修改刷高）。

支配判定 `_dominates(a, b, dims)`：a 在**所有**维度上 `>=` b，且在**至少一个**维度上 `>` b，则 a 支配 b。`pareto_front` 在硬+软全维度上求前沿——前沿成员就是"在某种权衡下不输给任何人"的版本。

### 硬维门：挡住"只靠软分虚高"的伪赢家

仅在 Pareto 前沿上还不够：一个 judge 极高、但 A/anchor 很低的版本，会因为它在 judge 维上无人能及而留在前沿——这正是典型的自欺形态（讨好裁判而非真做对）。`selectable_parents` 在前沿之上再加一道**硬维度中位数门**：

1. 取出整条 Pareto 前沿；
2. 对每个硬维度（A、anchor），算出该维度在**所有前沿成员**上的中位数；
3. 一个前沿成员只有在**每个**硬维度上都 `>=` 对应中位数时，才算"可选父版本"。

于是软分虚高、硬指标拉胯的版本即便在前沿里，也被挡在"可被选作父版本"之外——它仍存在于谱系（不删），但不会污染下一轮的演化起点。**这是 archive 反自欺的核心闸门**：父版本准入由客观硬指标把关，主观软分不能单独开门。

### 库漂移 retire_stale：冷藏不删除

跑久了活跃版本会膨胀。`retire_stale(archive_dir, active_cap)` 在版本数超过 `active_cap` 时启动瘦身，但语义是"冷藏"而非"删除"：

- 需要冷藏的数量 `n_retire = len(vs) - active_cap`；
- **保留优先级**：可选父版本（通过硬维门者）优先保留，因此**先冷藏非可选版本**；
- 两组各自按 `last_used_round` 升序排（最久没被用到的最先冷藏）；
- 冷藏顺序 = 非可选（旧→新）+ 可选（旧→新）。即非可选不够冷藏额度时，最旧的可选父版本也会被冷藏——**库漂移必须强制守住上限**；
- 冷藏动作 = 向 `retired.jsonl` append 一行 `{"vid", "reason": "stale_active_cap"}`。**`lineage.json` 本体绝不被修改**——这是"冷藏不失忆"，历史永远可考、可复活。

`_read_retired` 读 `retired.jsonl` 时逐行解析，遇到损坏/半截行（崩溃时半写）静默跳过，对崩溃鲁棒。

> 注：`last_used_round` 字段由调用方在版本被选作父版本时回填到谱系条目；archive 用 `v.get("last_used_round", 0)` 读取，缺省按 0（最旧）处理。

## 契约（I/O schema + 相邻模块接口）

公开 API（契约锁定，禁止改名，见模块 docstring）：

| 函数 | 输入 | 输出 / 副作用 |
| --- | --- | --- |
| `add_version(run_dir, vid, scores, parent_vid)` | run 目录、版本 id、得分、父 id（可为 `None`） | append 一条谱系记录 + 建 `versions/<vid>/` 目录 |
| `snapshot_version(archive_dir, vid, sandbox_root)` | 已拼好的 archive 目录、vid、沙箱根 | 整树拷进 `versions/<vid>/snapshot/` |
| `lineage(archive_dir)` | archive 目录 | 完整有序谱系 `list[dict]` |
| `rollback(archive_dir, vid)` | archive 目录、vid | 还原快照到 `current/`；无快照抛 `FileNotFoundError` |
| `pareto_front(archive_dir)` | archive 目录 | 非支配版本 id 列表 `list[str]` |
| `selectable_parents(archive_dir)` | archive 目录 | 前沿 ∩ 硬维门 的可选父版本 id 列表 |
| `retire_stale(archive_dir, active_cap)` | archive 目录、活跃上限 | 超额时 append 冷藏记录到 `retired.jsonl` |

**谱系条目 schema**（`lineage.json` 内每条）：

```json
{ "vid": "v3", "parent_vid": "v2", "scores": { "A": 0.8, "anchor": 0.7, "judge": 0.9 } }
```

`scores` 是 `{维度名: 数值}` 的字典——`pareto_front` / `selectable_parents` 据此做多目标比较，缺失维度按 0 处理。

**路径约定（易错点，状态机注释里专门标注）**：`add_version` 收的是 **`run_dir`**（内部自己 join 出 `archive`），`snapshot_version` 收的是**已拼好的 `arch_dir`**。二者不可混传。

**相邻模块接口**：

- 上游 **状态机（statemachine.py）**：accept 进入 `ARCHIVE` 时，分配 `vid = f"v{len(accepted)+1}"`，调 `archive.add_version(run_dir, vid, _a_dims, parent)` + `archive.snapshot_version(arch_dir, vid, sandbox_root)`。注意调用点传入的 `scores` 实参是评测/Supervisor 返回的 `dimensions` 列表（A 档维度），而 Pareto 数学按 dict 读取——条目的 `scores` 形态最终须是 `{维度名: 值}` 字典才能参与硬维门比较。
- 上游 **评测策略 / 信号 provider**（框架权威见 `docs/reference/signal-providers.md`）：A/B/C 是不同的"评测策略 / 信号来源"而非"目标等级"。archive 的硬维度 `A`、`anchor` 与软维度 `judge` 的分值都来自这些 provider 产出的维度分；archive 本身不打分，只消费分数做 Pareto 与门控。
- 下游 **propose / 选父**：下一轮选父版本时应只从 `selectable_parents` 里选，而非全谱系——这是硬维门发挥作用的地方。
- **CLI（cli.py）**：`status` 子命令调 `pareto_front` 展示当前前沿；`rollback` 子命令转调 `archive.rollback`。

## 反自欺点

archive 这一层特有的自欺形态，以及对应的闸门：

1. **讨好裁判（软分虚高）**：候选学会迎合主观裁判（judge）而非真把客观指标做对，靠 judge 维度单独冲上 Pareto 前沿。
   - **闸门**：`selectable_parents` 的硬维度中位数门——前沿成员必须在 A、anchor 上都不低于前沿中位数才可当父版本。软分高不足以开门。

2. **篡改/重排历史**：把退化版本"洗白"成更好的祖先，或抹掉失败记录。
   - **闸门**：谱系 append-only + `os.replace` 原子重写；只有 `add_version` 写谱系且只追加；`retire_stale` 只写 `retired.jsonl`、**绝不动 `lineage.json`**。

3. **删除淘汰版本来掩盖搜索路径**：把被淘汰的版本物理删掉，使"演化探索过哪些方向、失败在哪"不可考。
   - **闸门**：库漂移是"冷藏"而非"删除"——`retired.jsonl` 留痕、快照仍在、谱系完整，任何历史版本都可 `rollback` 复活、可审计。

4. **回滚到不存在/被伪造的版本**：以"回滚"为名跳到一个没有真实快照的状态。
   - **闸门**：`rollback` 找不到 `versions/<vid>/snapshot/` 即抛 `FileNotFoundError`，拒绝静默回滚。

5. **库漂移时优待"自己人"导致上限失守**：为保住高软分版本而拒绝守住活跃上限。
   - **闸门**：`retire_stale` 的冷藏顺序虽优先保可选父版本，但非可选不够额度时连最旧的可选父版本也照冷藏——上限是硬约束，不被"保留偏好"破坏。

## 代码锚（file:func）

- `tools/sie/archive.py:_arch_dir` — 创建/返回 run 下的 archive 目录
- `tools/sie/archive.py:_load_versions` — 读谱系，兼容 list 与 `{"versions":...}` 两种格式
- `tools/sie/archive.py:_dominates` — Pareto 支配判定
- `tools/sie/archive.py:add_version` — append-only 谱系写入 + 原子改名
- `tools/sie/archive.py:lineage` — 读完整谱系
- `tools/sie/archive.py:snapshot_version` — 整树快照（忽略 .git/__pycache__/.sie）
- `tools/sie/archive.py:rollback` — 还原快照到 current，无快照抛错
- `tools/sie/archive.py:pareto_front` — 硬+软全维度多目标前沿
- `tools/sie/archive.py:selectable_parents` — 前沿 + 硬维度中位数门
- `tools/sie/archive.py:retire_stale` — 库漂移冷藏（不删除）
- `tools/sie/archive.py:_read_retired` — 读冷藏记录，跳过损坏行
- `tools/sie/statemachine.py` (ARCHIVE 分支, 约 1014-1024 行) — accept 后调用 add_version + snapshot_version
- `tools/sie/cli.py` (status / rollback 子命令) — 展示 pareto_front、转调 rollback
