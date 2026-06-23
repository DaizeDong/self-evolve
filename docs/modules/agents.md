# Module: agents（统一 agent 调用层 + 异质交叉校验）

## 职责

把「调一个 agent」与「用另一家族交叉校验」抽象成**任意阶段可复用**的原语，使 codex 成为
**全流程可选的异质 agent**——而非 C 档判官专属组件。reflect / propose / patch-review /
evaluate / judge 任一阶段都能：
- `invoke(prompt, family="codex")` —— 在该阶段调指定家族的一个 agent；
- `cross_check(prompt, families=("claude","codex"))` —— 同一任务跑多家族 → 收齐 + 比对分歧。

这是「强化不同类别 agent 互校验、把 codex 当任意阶段的调用选项」这一设计诉求的承载模块。

## method

**家族分发**（`workflows/_agent_launch.js: launch(family, opts, prompt)`）：
- `claude` / `cc` → 经 `_claude_launch`（cc 优先、claude fallback、`-p` json、prompt 走 stdin）。
- `codex` → `codex exec -s read-only`（只读沙箱：任意阶段调 codex 都不能写盘 / 逃逸 shell；
  `-o` 取最终消息避噪；默认 `gpt-5.5` + `xhigh`，与「codex 永远用最强」一致）。

**统一入口**（`workflows/agent.js`）：`--family <claude|cc|codex> [--role ..] [--model ..]
[--tools web_search] [--effort ..]`，stdin prompt → stdout 结果。是「在某阶段调某家族 agent」
的唯一命令。

**Python 层**（`tools/sie/agents.py`）：
- `invoke(prompt, family, model?, tools?, effort?, role?, timeout_s)` → `{ok, result, family}`。
- `cross_check(prompt, families)` → `{per, n_ok, results_ok, heterogeneous}`：多家族各跑一遍并
  收齐；`heterogeneous=True` 表示 ≥2 个不同家族都成功（真交叉校验成立）。
- `cross_check_verdicts(prompt, families)` → `{verdicts, agree, n_ok}`：评审特化，期望各家族
  回 `{verdict}`，给出是否一致（<2 成功 → `agree=None`）。

**已接入的非判官阶段**（codex 不再只限判官）：
- **REFLECT**：`reflect.run_reflections_parallel(..., families=["claude","codex","claude"])` →
  N=3 MARS 跨家族异质反思（`reflect-fanout.js --family`）。
- **REVIEW**：`review-fanout.js --family` → 评审可由不同家族独立出 verdict。
- **JUDGE**：C 档判官本就异质（见 [`judge.md`](judge.md)）。

## 契约

- `invoke` I/O：`prompt:str → {ok:bool, result:str, family:str}`；失败 graceful（不抛）。
- `cross_check` 只负责「异质地各跑一遍并收齐」；**是否一致 / 分歧由调用方按角色解释**
  （judge 用 `judges.pairwise_agreement` 比分；review 用 `cross_check_verdicts` 比 verdict）。
- 家族：`claude`|`cc`|`codex`（`VALID_FAMILIES`）。

## 反自欺点

| 形态 | 闸门 |
|---|---|
| 用同一家族「自校验」（伪异质） | `cross_check.heterogeneous` 要求 ≥2 个**不同**家族成功；同源不计 |
| agent 越权写盘 / 副作用 | codex 路径强制 `-s read-only`；claude 路径只读工具（`--tools web_search`→WebSearch） |
| 让 agent 裁决自己产出 | 铁律1：这些是「搜索 / 反思 / 评审」用途；采纳/拒绝仍归确定性 acceptor，cross_check 只产参考信号 |
| 单家族不可用时静默降级成「自评」 | `n_ok<2 → heterogeneous=False / agree=None`，调用方据此不得当作已交叉校验 |

## 代码锚

- `workflows/_agent_launch.js`（`launch`）、`workflows/agent.js`（统一 CLI）
- `tools/sie/agents.py`（`invoke` / `cross_check` / `cross_check_verdicts`）
- `tools/sie/reflect.py`（`run_reflections_parallel(families=...)`）、`workflows/reflect-fanout.js`、`workflows/review-fanout.js`
- 判官侧仍见 `tools/sie/judges.py` / `judge_codex.py` / `judge_claude.py`
