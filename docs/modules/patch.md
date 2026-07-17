# patch, 静态准入门（import 白名单 + AST 危险调用 + IMMUTABLE 硬拒 + 沙箱边界）

> 代码：`tools/sie/patch.py`、`tools/sie/sandbox.py`

## 职责（含在 pipeline 的位置）

self-evolve 的主循环是恒定的五步：反思 → 提议 → 评测 → 裁决 → 接受，全程伴随反自欺核查。提议（propose）阶段产出的永远只是"候选改动文本"，自己不写盘、不被信任；写盘这一步发生在状态机的 **态5 PATCH**，由 `apply_patch` 把候选内容落到沙箱工作区,**这一落盘动作就是本模块的全部职责所在**。

本模块是 candidate 代码真正进入磁盘前的**最后一道、也是唯一一道静态准入门**。它在"内容已生成、尚未执行"的窗口里做纯静态判断：只看 AST、只看路径，不运行任何候选代码。它把守四件事，任一不过即整文件 REJECT、绝不落盘：

1. **import 白名单**,只许导入预先许可的安全模块；
2. **AST 危险调用门**,拒绝 `eval`/`exec`、进程执行、网络外联、动态 import 等危险调用，并堵住别名、`importlib`、`builtins`、`getattr`、下标取值等绕过路径；
3. **IMMUTABLE 硬拒**,自举/enforce 模式下，凡命中"裁决代码集"清单的写入一律先拒，护住裁决逻辑自身不被候选改动篡改；
4. **沙箱 realpath 边界**,写入目标的真实路径（解符号链接、解 `..`）必须落在沙箱根内，越界即拒。

它在反自欺体系里属于**最外层的"门前体检"**：评测信号（无论用 A/B/C 哪种评测策略产生）只对"已经安全落盘、可在沙箱里跑起来的 candidate"才有意义。如果一个候选能偷偷 `import subprocess` 起进程、能 `open('/etc/passwd')` 读越界文件、能改掉裁决自身的代码，那么后面再精巧的评测与裁决全都可被它从根上架空。本门的存在，是让"后续所有评测面对的都是一个被静态封住危险动作的对象"。

边界判定（`canonical_in_sandbox` / `action_class`）与 IMMUTABLE 清单本身都属于 IMMUTABLE 裁决代码集（见 `immutable.py` 的 `IMMUTABLE_RELPATHS`，`patch.py`、`sandbox.py`、`immutable.py` 三者都在册）,也就是说，**这道门自己受自己保护**：候选无法通过改写 `patch.py`/`sandbox.py` 来给自己开后门，因为改这些文件会先被 IMMUTABLE 硬拒、并被自举哈希门核出。

## method

落盘走 `apply_patch(sandbox_root, file_rel, new_content, allow=None, enforce_immutable=False)`，内部是**严格有序的四道闸**，前序闸不过立即返回 `{"status":"REJECT", ...}`，文件一个字节都不会写。顺序本身是安全契约的一部分：

### Gate 0, IMMUTABLE 硬拒（先于一切）

`immutable_gate([file_rel], enforce_immutable)`。仅当 `enforce_immutable=True`（自举 / `--self` / `--enforce-immutable`）时生效；默认 `False` 直接放行返回 `None`，向后兼容非自举调用方。

判定委托给 `immutable.is_immutable_relpath`，它先做**路径归一化再取 basename**：反斜杠转正斜杠 → `normpath` 去掉 `./`、`../` → 取文件名。于是 `acceptor.py`、`./acceptor.py`、`tools/sie/acceptor.py`、`tools\sie\acceptor.py`、`sub/../acceptor.py`、`/abs/path/acceptor.py` 全部归一为 `acceptor.py`，无法靠路径花样绕过清单。命中即 `REJECT`，reason 形如 `immutable_hit: <paths>`。

注意分工：**Gate 0 拦的是"对裁决文件的写入企图"**（写时拒）；而"裁决文件是否已被篡改"由 supervisor 启动时的哈希门（`immutable.verify_immutable` 比对 `materialize_frozen` 从 base ref 取出的冻结哈希）独立把守。两者互补,一个防写、一个防已改。

### Gate 1, 沙箱 realpath 边界（先于任何 I/O）

`canonical_in_sandbox(target, sandbox_root)`（来自 `sandbox.py`），把目标路径与沙箱根都过 `os.path.realpath` 取真实路径后比较。关键设计：

- **未存在路径也能判**。`_real` 对尚不存在的写入目标，逐级向上走到"最近的已存在祖先"，对该祖先取 realpath，再把剩余的不存在尾段拼回。于是"父目录在沙箱内、文件本身还没创建"这一最常见情形能被正确判定。
- 防御面覆盖：指向沙箱外的**符号链接**、`..` **穿越**、**前缀同名的兄弟目录**（`/a/sandbox-evil` 不算在 `/a/sandbox` 内，靠 `commonpath == root` 精确比较而非字符串 startswith）、以及 Windows 下经 `os.path.normcase` 的**大小写不敏感**比较。
- 跨盘符（`commonpath` 抛 `ValueError`）一律判为越界。

这道闸**必须在任何文件 I/O 之前**跑,它是"先确认目标合法，再谈写入"的硬边界。

### Gate 2, import_gate（仅 `.py`，M1a 基线白名单 + 基线危险调用）

`import_gate(source, allow)` 解析 AST，命中即返回 `(False, reason)`：

- **危险模块**：`subprocess`/`socket`/`ctypes`/`multiprocessing`（`_DANGER_MODULES`）,即便调用方把它加进 `allow` 也照拒（硬黑名单优先于白名单）。
- **白名单外 import**：顶层模块名不在 `allow ∪ _DEFAULT_ALLOW`（`json`/`math`/`re`/`typing`/`pathlib` 等安全子集）即拒。
- **危险内建调用**：`eval`/`exec`/`compile`/`__import__`（`_DANGER_CALLS`）。
- **危险属性调用**：`os.system`/`os.popen`（`_DANGER_ATTR`）。
- **符号走私**：`from os import system` 这类把危险符号直接 import 进来的写法（按原始符号名而非 `asname` 核查）。

### Gate 3, scan_ast_dangerous（仅 `.py`，M1b 全危险面）

这是危险调用门的主体，覆盖 Gate 2 之外的全部绕过路径，返回**违规原因列表**（空列表=通过）：

- **import 白名单**（更宽的默认集 `DEFAULT_IMPORT_ALLOW`，含 `os`/`sys`/`ast`/`hashlib` 等）+ `DANGEROUS_MODULE_PREFIXES` 硬黑名单（`subprocess`/`socket`/`ctypes`/`importlib`/`requests`/`urllib`/`httpx`/`http`/`aiohttp`/`ftplib`/`telnetlib`/`smtplib`/`multiprocessing`，加进 `allow` 也拒）。
  - 设计取舍：`asyncio`/`concurrent` 已**移出**黑名单,它们是正常并发原语，不直接执行代码或外泄数据，留着只会误伤。
- **裸名调用**：只有 `eval`/`exec`/`compile`/`__import__`（`_BARE_DANGEROUS_CALLS`）作为裸名才拦。`run`/`get`/`post`/`delete` 等**故意不**当裸名拦,它们只有挂在危险模块上才危险，裸名拦会误伤 `app.run()`、`db.run(q)`、`client.get()`。
- **属性调用** `a.b.c()`，分层精确判定，避免按"叶名在危险集"粗暴误伤：
  - `importlib.import_module` / `importlib.__import__` → 动态 import 绕过；
  - `builtins.<危险>` / `__builtins__.<危险>` → builtins 绕过；
  - `(os, system)`/`(os, popen)`/`os.exec*`/`os.spawn*`（`_DANGEROUS_MODULE_METHOD_PAIRS`）→ 即便 `os` 在白名单，这些方法仍拒；
  - 顶层模块 ∈ `DANGEROUS_MODULE_PREFIXES`（`subprocess.run`、`requests.get`、`socket.socket`…）→ 这是 `run`/`get`/`post`/`socket` 这类名字的**主拦截机制**。
- **别名追踪（污点传播）**：`_collect_tainted_names` 先扫一遍赋值，把直接绑到危险可调用对象的名字标为污点（`fn = eval`、`g = importlib.import_module`、`fn = os.system`），再用**不动点迭代**沿 `Name→Name` 赋值多跳传播（`fn1=eval; fn2=fn1; fn2('x')` 全链命中）。随后调用点扫描里，污点名的裸调用与属性调用都拒。容器别名（`lst=[eval]; lst[0]()`）静态不可解，明确不追踪。
- **下标绕过**：`__builtins__['eval']('x')` / `builtins['exec']('x')`（兼容 Py<3.9 的 `ast.Index` 解包）。
- **getattr 绕过**：`getattr(builtins, '__import__')` / `getattr(__builtins__, 'eval')`（对象指向 builtins 且属性名是危险字面量）。
- **沙箱越界 open()**：`open('字面绝对路径')` 经 `_is_outside_sandbox`（同样过 realpath + `commonpath`，相对路径以 target 所在目录为基）判越界则拒；给了 `sandbox_root` 但路径是**非字面量动态值**时也拒,静态无法证明在沙箱内，按 fail-closed 处理。

四闸全过，才 `os.makedirs` 建父目录并以 UTF-8 写入，返回 `{"status":"APPLIED","reason":"ok"}`。

## 契约（I/O schema + 相邻模块接口）

### 主入口 `apply_patch`

入参：

| 字段 | 类型 | 含义 |
|---|---|---|
| `sandbox_root` | str | 沙箱工作区根（`make_worktree` 产物） |
| `file_rel` | str | 沙箱内相对写入路径 |
| `new_content` | str | 候选文件全文（文本） |
| `allow` | set[str] \| None | 额外许可的 import 模块名（并入两道 AST 门的白名单；硬黑名单不受其影响） |
| `enforce_immutable` | bool | True=自举模式，启用 Gate 0 IMMUTABLE 硬拒；默认 False |

返回（恰二选一）：

- `{"status": "APPLIED", "reason": "ok"}`, 四闸全过，已写盘；
- `{"status": "REJECT",  "reason": <str>}`, 任一闸不过，**文件未写**。reason 前缀标明拦截层：`immutable_hit: …` / `path outside sandbox boundary` / `AST gate: …` / `AST danger gate: …`。

### 子函数签名

- `import_gate(source, allow=None) -> (bool, str)`,`(True,"")` 过 / `(False, reason)` 拒。
- `scan_ast_dangerous(source, *, allow_imports=None, sandbox_root=None, target_path=None) -> list[str]`,空列表=过；非空=违规原因清单。
- `immutable_gate(target_relpaths, enforce) -> dict | None`,命中返回 `{"decision":"REJECT","reason":"immutable_hit","paths":[...]}`，未命中或 `enforce=False` 返回 `None`。

### sandbox.py 接口

- `canonical_in_sandbox(path, sandbox_root) -> bool`,realpath 边界判定。
- `action_class(action, sandbox_root) -> "auto" | "gated"`,动作分级（IMMUTABLE 规则，不受 `--mode` 影响）：`op ∈ OUTWARD_OPS`（`push`/`merge_main`/`send`/`delete_outside`/`land`/`approve`）恒 `gated`；canonical 路径在沙箱内 → `auto`；其余 `gated`。
- `make_worktree(target, base_ref, run_id) -> str`,在 `<target>/.sie/worktrees/<run_id>` 建（或幂等复用）git worktree（分支 `sie/<run_id>`），返回其绝对路径，即后续 `apply_patch` 的 `sandbox_root`。

### 相邻模块

- **上游 `statemachine.py`（态5 PATCH）**：对每条提议调 `apply_patch(sandbox_root, p["file_rel"], p["new_content"], enforce_immutable=…)`；任一 APPLIED 则本轮算应用成功，全 REJECT 则记 `STATIC_REJECT` 并触发熔断核查。`sandbox_root` 来自 `make_worktree`，`enforce_immutable` 由 `--self`/`--enforce-immutable` 透传。
- **`immutable.py`**：Gate 0 委托 `is_immutable_relpath`；与之配套的启动哈希门（`materialize_frozen` / `verify_immutable` / `hash_file`）在 supervisor 侧独立运行，二者一防写一防改。
- **proposer 后端 `backends/llm.py`**：明确遵循"铁律1 to proposer 只生成提议，采纳由确定性 harness 裁决"，其产物正是经本门核验。

## 反自欺点（本模块的自欺形态 + 对应闸门）

本门要防的"自欺"，是候选改动**伪装成无害、实则在静态层就埋下危险动作或为自己开后门**。逐一对应：

- **危险动作换皮绕过白名单核查**。直接 `eval`/`import subprocess` 太显眼，于是改用别名（`fn=eval; fn()`）、`importlib.import_module`、`builtins['exec']`、`getattr(builtins,'eval')`、`__builtins__.__import__` 等迂回写法。→ 闸门：`scan_ast_dangerous` 的污点不动点传播 + importlib/builtins/getattr/下标四类绕过专项 + 模块前缀硬黑名单。
- **"看起来在白名单内"实则危险**。`os` 在白名单，便用 `os.system`/`os.popen`/`os.exec*`/`os.spawn*` 偷起进程。→ 闸门：`_DANGEROUS_MODULE_METHOD_PAIRS` 在模块整体许可下仍单独拒这些方法。
- **越界读写伪装成普通文件操作**。`open('/etc/passwd')`、或写到沙箱外、或用 `..`/符号链接穿越边界。→ 闸门：`canonical_in_sandbox` 的 realpath 边界 + `scan_ast_dangerous` 对 open 字面越界 / 非字面动态路径（无法静态证明在内即拒）的双重核查。
- **改裁决逻辑自身来架空整套门**。候选试图改写 `patch.py`/`sandbox.py`/`acceptor.py` 等裁决文件，给自己放行。→ 闸门：Gate 0 IMMUTABLE 硬拒（写时，路径归一化防绕过）+ supervisor 启动哈希门（改后，base ref 冻结哈希比对）。
- **静态不可判时默认放行的侥幸**。如动态路径的 open、容器别名调用。→ 闸门：对"无法静态证明安全"的情形取 **fail-closed**,动态 open 路径直接拒；容器别名虽不可追踪，但其要落地仍须经过被本门核验的可调用对象，整体保持"宁拒勿漏"。

闸门设计的另一面是**反过度自欺（防误伤导致的虚假拒绝）**：裸名 `run`/`get`/`post` 与任意接收者的 `.get()`/`.run()` 故意不拦，避免把 `app.run()`、`client.get()` 误判为危险而制造假阳性,危险性的判定锚定在"危险模块接收者"这一真实信号上，而非叶名字面。

## 代码锚（file:func 列表）

- `tools/sie/patch.py:apply_patch`, 四闸有序编排，唯一写盘入口
- `tools/sie/patch.py:immutable_gate`, Gate 0，IMMUTABLE 写时硬拒
- `tools/sie/patch.py:import_gate`, Gate 2，M1a 基线白名单 + 基线危险调用
- `tools/sie/patch.py:scan_ast_dangerous`, Gate 3，M1b 全危险面 AST 扫描
- `tools/sie/patch.py:_collect_tainted_names`, 别名污点不动点传播
- `tools/sie/patch.py:_attr_chain` / `_is_outside_sandbox`, 属性链还原 / open 越界判定辅助
- `tools/sie/sandbox.py:canonical_in_sandbox`, Gate 1，realpath 沙箱边界
- `tools/sie/sandbox.py:_real`, 未存在路径的最近祖先 realpath 解析
- `tools/sie/sandbox.py:action_class`, 动作分级（OUTWARD_OPS 恒 gated）
- `tools/sie/sandbox.py:make_worktree`, 沙箱 worktree 创建/复用
- `tools/sie/immutable.py:is_immutable_relpath`, IMMUTABLE 路径归一化判定（被 Gate 0 调用）
