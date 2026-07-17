# 计划：接通 LLM 接缝（Claude + Codex 两个真 agent）

把 self-evolve 从"骨架 + 桩"推到**真正能自我迭代**：用本机 `claude` 与 `codex` CLI
填上 5 处生成式接缝。裁决/安全/反自欺骨架不动（521 测试保持绿）。

## 已核实的真实 CLI 接口（live 探测过）

| Agent | 非交互调用 | 输出 |
|---|---|---|
| Claude (`cc` 封装的本体) | `claude -p --output-format json --dangerously-skip-permissions [--bare] [--model M] [--allowed-tools ...] [--append-system-prompt S] "<prompt>"` | `{"type":"result","result":"<响应>",...}` → 取 `.result`；exit 0 |
| Codex | `codex exec -m gpt-5.5 -s read-only "<prompt>"`（prompt 也可走 stdin） | stdout 头部噪声 + 末尾响应；默认 effort=xhigh、sandbox=read-only；exit 0 |

- **现有 `codex-judge.js` 参数是错的**（无 `exec` 子命令、`--approval-mode/--allowed-tools/--quiet` 非真实 flag）,必须重写为 `codex exec`。
- Codex `-s read-only` = 硬安全边界（判官进程不能写盘/逃逸 shell）；可加 `--output-last-message <file>` 取干净末条消息，或沿用现有 JSON 块提取。
- Claude `--bare` = 跳过 CLAUDE.md/memory/hooks，判官调用干净无污染。

## 家族分配（反自欺核心，铁律1）

- **Proposer + Reflector = Claude**（`claude -p`）。
- **C 档 judge = Claude + Codex 两个异质家族**。
- 因 proposer 是 Claude，design 既有的 `single_claude_block` 保证：Codex 不可用时**禁单 Claude 自动 ACCEPT**,proposer 家族不能独自裁决自己产出。两家族 `pairwise_agreement` 去相关。**这正是当初要两个最强 agent 的原因。**

## 5 处接缝（均为干净 stdin/stdout 契约，逐一替换桩体）

| # | 文件 | 现状 | 接法 |
|---|---|---|---|
| 1 | `workflows/claude-judge.js`（**新建**） | 缺失（judge_claude.py 已指向它） | 读 stdin prompt → `claude -p --output-format json --bare --dangerously-skip-permissions --allowed-tools WebSearch --model <claude>` → 取 `.result` → stdout |
| 2 | `workflows/codex-judge.js`（**重写**） | 参数错、从未真跑通 | 保留 JS 层 flag 校验（禁 browser/playwright 执行点契约）→ 实际调 `codex exec -m <model> -s read-only` → stdout |
| 3 | `workflows/reflect-fanout.js`（**填**） | 桩 `findings:[]` | 读 {history} → `claude -p` 反思 prompt（只读 history，铁律2）→ 解析 findings → stdout |
| 4 | `workflows/review-fanout.js`（**填**） | 桩 | 同上，评审 prompt |
| 5 | propose 后端（`backends/builtin.py` 旁新增 `backends/llm.py`） | 确定性占位 | `claude -p` 据 reflections 生成 patch → {file_rel,new_content}；**保留 builtin 为默认/测试用** |

## 测试策略（关键：不拖垮 521 测试 / 不烧 token）

- pytest **默认仍全程 mock**（judge_*/propose 注入），真 CLI **绝不进 pytest**,521 测试不变、不调外部。
- 新增**опт-in live smoke 测试**：`@pytest.mark.skipif(os.getenv("SIE_LIVE")!="1")`，各做一次真 `claude -p` / `codex exec` 单轮，验证端到端接通（手动跑 `SIE_LIVE=1 pytest -k live`）。
- propose 后端用 env/参数选择 `builtin`(默认,确定性,测试用) vs `llm`(真 Claude)；run_loop 默认 builtin，加 `--proposer llm` 开真。

## 实施顺序（分两阶段，中间 live smoke 闸）

**Phase 1, 判官（反自欺核心，风险最高的外部集成先验证）**
1. 重写 codex-judge.js → `codex exec`；新建 claude-judge.js → `claude -p`。
2. live smoke：`SIE_LIVE=1` 各调一次，确认 span_scores JSON 能被 `_parse_span_scores` 解析、降级路径(超时/非0)正确。
3. 全套 pytest（mock）保持 521 绿。

**Phase 2, 提议 + 反思（生成闭环）**
4. 填 reflect-fanout.js / review-fanout.js（claude），run_reflections_parallel 真并行。
5. 新增 backends/llm.py（claude proposer）；CLI 加 `--proposer llm`。
6. live smoke：对一个**小测试仓库**（如临时 git repo + 一个 failing pytest）跑一轮真 `run`，看能否真生成 patch→沙箱验证→采纳。
7. 全套 pytest（mock）保持绿 + 新 live smoke（opt-in）通过。

## 安全/成本注意

- Codex 判官 `-s read-only`、Claude 判官 `--bare --allowed-tools WebSearch`：判官只读+受限工具，不能写/exfil（叠加 harness 既有 proxy/沙箱）。
- 自举（`--self`）时：harness 决策码仍走 frozen/Supervisor 隔离；claude/codex 是外部进程，与决策码隔离不冲突。
- **成本**：一轮 = N=3 反思 + propose + 2 判官 ≈ 6+ 次 agent 调用；真 run 是分钟级 + 真 token。默认 max-rounds 保守（3），文档标注。
- Codex 调用时本机 ~/.codex 的 figma MCP 报错是无害噪声；可加 `-c` 关 MCP 让判官调用更干净（可选）。

## 验收

- 521 mock 测试保持绿（外部 CLI 不进 pytest）。
- `SIE_LIVE=1` 下：claude-judge / codex-judge 各真出一次 span_scores；一轮真 run 在小仓库上能 propose→evaluate→accept。
- C 档真异质判官（Claude+Codex）端到端：pairwise_agreement 用两家族真分、single_claude_block 在 Codex 缺席时真拦。
