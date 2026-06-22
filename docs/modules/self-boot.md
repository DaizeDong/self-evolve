# self-boot（自举装配）

> 代码：`tools/sie/selfboot.py`、`tools/sie/immutable.py`、`tools/sie/supervisor.py`、`tools/sie/proxy.py`

## 职责

self-boot 是 self-evolve 在「评测对象 = self-evolve 自己」这一特殊场景下的装配层。

self-evolve 的方法论恒定：reflect（反思）→ propose（提候选）→ evaluate（评测）→ judge（裁决）→ accept（接纳），全程贯穿反自欺。平时被改、被评、被裁的是某个外部目标仓库；而当我们用 `--self` 旗标让 self-evolve 改进**自身**时，出现了一个普通场景没有的致命问题：

**被评测的代码里，包含了负责评测/裁决的代码本身。** 如果不加隔离，候选版本（candidate）完全可以在自己提出的 patch 里顺手把 acceptor（裁决配对）、verifiable（A 类策略下的 grader）、selfdeception（自欺指数闸）改成「永远 ACCEPT」「打分恒为满分」，然后用这套被自己篡改过的逻辑给自己打分、放行自己。这就是自举场景下最根本的自欺形态——**裁判即选手**。

self-boot 在 pipeline 中的位置：它**早于** reflect/propose/evaluate/judge 的任何一步，是 `--self` 运行的第 0 步装配。`is_self_run(args)` 判定旗标后，`selfboot_init(...)` 先把整条流水线赖以信任的「裁决基线」固化下来，再把这套基线交给一个独立于 candidate 的只读裁决进程（Supervisor）。此后所有 evaluate/judge 的裁决调用，都走 Supervisor 用 frozen（冻结）副本执行，而不是 candidate 工作区里那份可能被改过的代码。

它要同时落实四件事：

1. **14 个决策码 frozen 物化** —— 把这 14 个被列为 IMMUTABLE 的裁决文件，从 git 基准内容复制成一份只读快照。
2. **sha256 fail-closed** —— 对每个 frozen 文件算哈希作为基线；candidate 工作区里对应文件只要缺失、改动、或基线为空，一律拒绝运行，绝不静默放过。
3. **supervisor 双进程裁决** —— 裁决由一个只从 frozen 副本 import 决策码的主进程做，candidate 子进程只产原始评测数据。
4. **frozen grader** —— 自举评测时 grader 取自 frozen，candidate 工作区既不进 `sys.path`、其 `grade()` 也不被采信，杜绝自评。

## method

### 1. IMMUTABLE 决策码集（14 个）

权威清单写死在 `immutable.py` 的 `IMMUTABLE_RELPATHS`，相对 `tools/sie/`，全是顶层文件名（无子目录）：

| 文件 | 在裁决里管的事 |
|---|---|
| `statemachine.py` | 状态机转移 |
| `acceptor.py` | 配对裁决（before/after 分数配对 → ACCEPT/REJECT/CONTINUE） |
| `judges.py` | 异构 judge |
| `verifiable.py` | A 类评测策略的 grader / 变异测试门 |
| `anchors.py` | B 类评测策略的锚点核查（trace 证据门、锚核查） |
| `selfdeception.py` | 自欺指数多闸 |
| `gate_human.py` | action 分级 / 人审门 |
| `profile.py` | tier 画像冻结判定 |
| `sandbox.py` | realpath 边界 / action 分级 |
| `supervisor.py` | 双进程裁决 loader（本模块） |
| `immutable.py` | 清单与哈希门自身 |
| `patch.py` | AST 危险调用拒绝门 |
| `proxy.py` | 出站审查：harness 代发 + 熵/序列异常 |
| `events.py` | 状态机 `_apply`：熔断 / 活性计数清零 / delta 归约 |

为什么必须把这套清单本身也冻结、还要把 `immutable.py`、`patch.py`、`proxy.py`、`events.py` 列进去？因为它们各自守着一个「如果漏列，candidate 就能从这里翻墙」的口子：

- 漏掉 `immutable.py` → candidate 能改清单或哈希门自己，整套锁形同虚设。
- 漏掉 `patch.py` → candidate 能在 patch 里白名单任意危险 import（AST 拒绝门被绕过）。
- 漏掉 `proxy.py` → candidate 能开隐蔽外传信道（出站审查被绕过）。
- 漏掉 `events.py` → candidate 能破坏熔断、把活性计数清零逻辑改掉。

**登记原则**：今后任何**新增**的裁决模块都必须登记进 `IMMUTABLE_RELPATHS`，否则自举哈希门不会保护它，它就成了新的翻墙口。

#### 路径归一防绕过

`is_immutable_relpath()` 经 `_normalize()` 判定：先把 `\` 统一成 `/`，再 `os.path.normpath` 去掉 `./` 与 `../` 段，最后取 `basename`。于是 `acceptor.py`、`./acceptor.py`、`tools/sie/acceptor.py`、`tools\sie\acceptor.py`、`sub/../acceptor.py`、`/abs/path/acceptor.py` 全部归一为 `acceptor.py`。取 basename 之所以足够防绕过，正是因为清单全是纯文件名、无子目录——这条不变式是 `_normalize` 简化成立的前提，清单一旦引入子路径就必须升级它。

### 2. frozen 物化 + sha256（fail-closed）

`materialize_frozen(base_ref, sie_root, frozen_dir)` 干三件事：

1. 用 `git rev-parse --show-toplevel` 找到仓库根，算出 `tools/sie` 在仓库里的 git 路径前缀。
2. 对清单里每个文件，用 `git show <base_ref>:<git_path>` 取**基准引用的内容**——**关键**：内容取自 git base ref，绝不读 candidate 工作区。这样即使 candidate 已经把工作区里的 IMMUTABLE 改了，进 frozen 的也是干净的基准版本。
3. 把内容写到 `frozen_dir/<文件名>`，`os.chmod(out, 0o444)` 设为只读，再 `hash_file` 算 sha256 记进 `digests`。

返回 `{relpath: sha256}` 的哈希基线。`frozen_dir` 由调用方放在 candidate 不可写的区域（见下「目录布局」）。

若某文件在 base ref 里还不存在（新文件尚未提交），`git show` 报错被捕获后**跳过**该文件，不入 `digests`——缺口留给 Supervisor 启动时的加载门去暴露（frozen 缺模块 → `ImmutableViolation`）。

`verify_immutable(candidate_sie_root, frozen_digests)` 是 fail-closed 的核：

- `frozen_digests` 为空 → 直接 `ImmutableViolation`（拒绝在无基线下运行 IMMUTABLE 锁）。
- 逐个比对 candidate 工作区里的同名文件：缺失记一笔，哈希不符记一笔。
- 任何一笔违规都汇总后 `ImmutableViolation`。**绝无静默通过的异常路径。**

跨平台行尾：frozen 的内容来自 `git show`（LF），candidate 工作区在 Windows 下可能是 CRLF。`hash_file(..., normalize_crlf=True)` 在哈希前把 `\r\n` 归一成 `\n`，让两边计算口径一致，避免纯行尾差异造成误报。

### 3. supervisor 双进程裁决

核心安全铁律（写在 `supervisor.py` 头部）：

- candidate worktree 路径**绝不**进 `sys.path`；
- 裁决模块的解析必须指向 frozen 副本，而非 candidate 工作区版本；
- 隔离 import 用 `spec_from_file_location` + 唯一模块名，**不**改全局 `sys.path`；
- frozen 缺模块 → 立即 `ImmutableViolation`（fail-closed）。

#### 隔离 import：`load_frozen_decider(frozen_dir, module)`

不走 `sys.path` 搜索，而是用 `importlib.util.spec_from_file_location` 按**文件路径**直接建 spec，以唯一名 `sie_frozen_<module>` 注册到 `sys.modules`（供模块内部自引用），`exec_module` 后**立即 pop**（load-and-pop）。这套做法的用意：

- 唯一名避免与 candidate 的同名标准模块（如 `acceptor`）在 `sys.modules` 里冲突或被覆盖；
- 标准名不写入 `sys.modules`，不污染、不影响 candidate 自己的 import 解析；
- exec 后移除唯一名，防止跨版本命名空间污染、多次调用累积。

frozen 里缺 `<module>.py`，或建不出 spec → `ImmutableViolation`。

#### 隔离断言：`candidate_path_is_isolated(frozen_dir, candidate_worktree)`

只检查**真实的 import 风险方向**。candidate 的 `tools.sie` 被 import 成的风险只有两种：

- (a) worktree 根**本身**在 `sys.path` 上（`sys.path` 某条目 == candidate）→ 顶层模块直接可 import；
- (b) candidate 的**子目录**在 `sys.path` 上（条目落在 candidate 之下）→ 该子目录模块可 import。

而「candidate 是某 `sys.path` 条目的子孙」（条目是 candidate 的祖先）**不**算风险——`import tools.sie` 仍解析到该条目自己的 `tools/sie`，不是 worktree 那份。所以把 worktree 建在「在 `sys.path` 上的 repo」的子目录里，是安全的，不算违规。

细节：`sys.path` 里的空串代表 cwd，展开为 `os.getcwd()`（覆盖 cwd == candidate 的风险）；`frozen_dir` 自身允许出现在解析路径（`load_frozen_decider` 不依赖它在 `sys.path`），不算违规；Windows 大小写不敏感，全程 `os.path.normcase(os.path.realpath(...))` 归一后再比。命中风险方向且不是 frozen_dir → 返回 `False`（隔离失败）。

#### `Supervisor` 类——只读主进程裁决器

构造时就 `load_frozen_decider(frozen_dir, "acceptor")` 隔离加载 frozen acceptor，绝不从 candidate import。它持有 frozen 决策码，candidate 子进程只产原始评测数据，裁决调用由它代为执行：

- `assert_candidate_intact(candidate_sie_root)` —— 随时复验 candidate 的 IMMUTABLE 与 frozen 基线一致（调 `verify_immutable`）。
- `decide(paired, tier, st, params)` —— 用 frozen acceptor 的 `decide` 做配对裁决，返回 `{"decision", "evalue", "reason", ...}`。这里的 `tier`（A/B/C）是**评测策略/信号 provider** 的选择，不是「目标等级」——A 是可验证执行类信号、B 是 trace 证据/锚核查类信号、C 是裁判模型类信号；框架权威见 `docs/reference/signal-providers.md`。
- `grade(task, candidate_worktree, *, self_mode)` —— 见下「frozen grader」。

### 4. frozen grader（candidate 不进 sys.path / 不能自评）

自举时被评测的代码**不能给自己打分**，grader 必须是 frozen/外部的。两条线落实：

- `Supervisor.grade(..., self_mode=True)`：懒加载 frozen `verifiable`，调 `grade_pytest(candidate_worktree)`——candidate_worktree 仅作为 **sandbox_root**（被测目录）传进去，frozen 的 grade 逻辑去跑它的测试，**完全不调用、不 import** candidate 工作区里那份 `grade()`。结果强制 `setdefault("graded_by", "FROZEN")`，便于负向用例断言「candidate 的 grade 没被采信」。
- `Supervisor.grade(..., self_mode=False)`：直接 `raise RuntimeError`——`Supervisor.grade` **仅自举专用**，非自举场景走正常 evaluate 路径（fail-closed，不让它误用）。
- `candidate_grade_is_trusted(self_mode)`：`self_mode=True` 返回 `False`（自举不信 candidate grade），`self_mode=False` 返回 `True`（非自举才信 candidate 的契约 grade）。

### 装配总流程：`selfboot_init`

`selfboot_init(self_repo_root, base_ref, run_id, runs_root)` 把上述拼成一条 fail-closed 的启动链：

1. **建独立 candidate worktree** —— `make_worktree(self_repo_root, base_ref, f"self__{run_id}")`，前缀 `self__` 标记「递归隔离」，避免与外层 run 撞目录。
2. **frozen 物化** —— `frozen_dir = runs_root/<run_id>/_frozen`（在 candidate worktree **之外**、主进程私有、candidate 不可写）；`materialize_frozen(base_ref, ...)` 内容取自 base ref。
3. **立刻校验** —— `verify_immutable(cand_sie_root, frozen_digests)`：首轮 candidate 应与 base ref 完全一致；不一致即 fail-closed。
4. **隔离断言** —— `candidate_path_is_isolated(frozen_dir, cand_sie_root)` 为假 → `ImmutableViolation("candidate worktree 出现在 supervisor 解析路径，自举隔离失败")`。
5. **起 Supervisor** —— `Supervisor(frozen_dir, frozen_digests)`，从 frozen import 决策码。

返回 `{"candidate_worktree", "frozen_dir", "frozen_digests", "supervisor"}`。任何一步不过即抛异常、不进入 reflect/propose——**自举宁可拒绝启动，也不在裁决基线可疑时往下跑**。

#### 目录布局（信任边界）

```
runs_root/
  <run_id>/
    _frozen/                  ← frozen 副本（0o444 只读，supervisor 私有，candidate 不可写）
      acceptor.py
      verifiable.py
      ... （14 个 IMMUTABLE 之中 base ref 已存在者）
<self_repo_root>/.../self__<run_id>/   ← candidate worktree（被改、被测，不进 sys.path）
  tools/sie/...
```

关键不变式：**裁决基线（_frozen）与被评测对象（candidate worktree）物理分离**，前者只读且不在 candidate 写权范围内，后者永不进入 supervisor 的 import 解析路径。

## 契约

### `is_self_run(args) -> bool`
- 入：argparse 命名空间；读 `args.self_mode` 或 `args.self`。
- 出：任一为真 → `True`。

### `selfboot_init(self_repo_root, base_ref, run_id, runs_root) -> dict`
- 入：被自举仓库根、git 基准引用（如 `"HEAD"`）、run 唯一 ID、run 根目录。
- 出：`{"candidate_worktree": str, "frozen_dir": str, "frozen_digests": dict[str,str], "supervisor": Supervisor}`。
- 抛：`ImmutableViolation`（verify 失败 / 隔离断言失败）、`subprocess.CalledProcessError`（git worktree 创建失败）。

### `materialize_frozen(base_ref, sie_root, frozen_dir) -> dict[str, str]`
- 出：`{relpath: sha256}`；base ref 中不存在的清单文件被跳过（不入返回值）。

### `verify_immutable(candidate_sie_root, frozen_digests) -> None`
- `frozen_digests` 空、文件缺失、或哈希不符 → `ImmutableViolation`；无静默通过路径。

### `Supervisor`
- `__init__(frozen_dir, frozen_digests)` —— 构造即隔离加载 frozen acceptor。
- `assert_candidate_intact(candidate_sie_root) -> None`。
- `decide(paired, tier, st, params) -> {"decision","evalue","reason",...}`。
- `grade(task, candidate_worktree, *, self_mode) -> dict`（`self_mode=False` 直接 `RuntimeError`；`self_mode=True` 结果含 `"graded_by":"FROZEN"`）。

### 相邻模块接口
- **sandbox**：`make_worktree(target, base_ref, run_id) -> str`（建隔离 worktree）。
- **acceptor**：`decide(paired, tier, st, params) -> dict`（Supervisor 从 frozen 副本调它做配对裁决）。
- **verifiable**：`grade_pytest(sandbox_root) -> dict`（Supervisor 在 `self_mode` 下从 frozen 副本调它，把 candidate_worktree 当 sandbox_root）。
- **immutable**：`IMMUTABLE_RELPATHS`、`is_immutable_relpath`、`hash_file`、`materialize_frozen`、`verify_immutable`、`ImmutableViolation`——本模块的清单与哈希门基座，被 selfboot/supervisor 共用。
- **评测策略 A/B/C 的语义**：`docs/reference/signal-providers.md`（A/B/C 是评测策略/信号 provider，不是目标等级）。

## 反自欺点

自举场景下「裁判即选手」是反自欺的主战场。本模块对应的自欺形态与闸门：

| 自欺形态（candidate 想怎么骗） | 对应闸门 |
|---|---|
| 改裁决码让自己永远 ACCEPT / 满分 | frozen 副本取自 git base ref（`git show`），不读 candidate 工作区；裁决一律走 frozen，candidate 工作区版本不参与裁决 |
| 改完 IMMUTABLE 还想蒙混启动 | `verify_immutable` sha256 fail-closed：缺失/改动/基线空一律 `ImmutableViolation`，宁拒不放 |
| 把 candidate 塞进 import 路径、让裁决码解析到自己改过的版本 | `candidate_path_is_isolated` 断言 + `load_frozen_decider` 按文件路径隔离 import（不动全局 `sys.path`、唯一名 load-and-pop） |
| 用自己的 `grade()` 给自己打分 | 自举 grader 取自 frozen `verifiable.grade_pytest`；candidate 工作区不进 `sys.path`、其 `grade()` 不被调用、不被采信（`candidate_grade_is_trusted(True)==False`，结果标 `graded_by=FROZEN`） |
| 用路径写法绕过 IMMUTABLE 判定（`./`、子目录、反斜杠、`..`） | `_normalize` 归一（统一分隔符 + 去 `./..` + basename），多种写法收敛到同一文件名 |
| 新增一个裁决模块但不登记，留作后门 | 登记原则：新增裁决模块必须进 `IMMUTABLE_RELPATHS`，否则哈希门不护它——这是流程闸门，需 reviewer 把关 |
| 改 `immutable.py`/`patch.py`/`proxy.py`/`events.py` 自身来拆门 | 这四者本身都在 14 个 IMMUTABLE 之列，被 frozen 哈希门同等保护 |
| 用 CRLF/LF 行尾差异制造哈希误判（误拒或试图借差异翻墙） | `hash_file(normalize_crlf=True)` 两边统一行尾口径 |

**残余风险（已知未尽）**：低于启发式阈值的隐蔽信道（如 proxy 序列异常检测里的时序/编码信道，见 `proxy.py` `sequence_anomaly` 注与 spec §6 残余风险）不在本模块覆盖内，依赖 proxy 出站审查与人审门兜底。

## 代码锚

- `tools/sie/selfboot.py:is_self_run` —— `--self` 旗标判定
- `tools/sie/selfboot.py:selfboot_init` —— 自举装配主流程（worktree → frozen → verify → 隔离断言 → Supervisor）
- `tools/sie/immutable.py:IMMUTABLE_RELPATHS` —— 14 个决策码权威清单
- `tools/sie/immutable.py:_normalize` / `is_immutable_relpath` —— 路径归一防绕过
- `tools/sie/immutable.py:hash_file` —— sha256（可选 CRLF 归一）
- `tools/sie/immutable.py:materialize_frozen` —— 从 git base ref 物化 frozen + 算哈希 + 置只读
- `tools/sie/immutable.py:verify_immutable` —— fail-closed 哈希校验
- `tools/sie/immutable.py:ImmutableViolation` —— 自举启动 fail-closed 异常
- `tools/sie/supervisor.py:load_frozen_decider` —— 按文件路径隔离 import（load-and-pop）
- `tools/sie/supervisor.py:candidate_path_is_isolated` —— sys.path 隔离断言
- `tools/sie/supervisor.py:Supervisor` —— 只读主进程裁决器（`decide` / `grade` / `assert_candidate_intact`）
- `tools/sie/supervisor.py:candidate_grade_is_trusted` —— 自举不信任 candidate grade
- `tools/sie/sandbox.py:make_worktree` —— 隔离 worktree 创建（相邻）
- `tools/sie/acceptor.py:decide` —— 配对裁决（frozen 副本被调，相邻）
- `tools/sie/verifiable.py:grade_pytest` —— 自举 frozen grader（相邻）
- `tools/sie/proxy.py:screen_request` / `dispatch` / `sequence_anomaly` —— 出站审查决策码（IMMUTABLE 之一，残余信道兜底）
