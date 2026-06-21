# self-evolve (SKILL)

指向任意 skill/仓库/项目，在 git worktree 沙箱内多轮自动改进它，用不可 game 的
提交门保证"被采纳=真改进"。

## 铁律（不可违背）

1. **LLM 只提议，代码裁决**：采纳/拒绝/回滚/分档由 harness 确定性代码决定；
   搜索/反思/评审才用 LLM，绝不让 LLM 评判自己产出。
2. **原始证据只读**：trace/反思 append-only，永不被 LLM 改写。
3. **数据隔离（铁律5）**：frozen 锚真值/测试真值对 REFLECT/PROPOSE/PATCH 不可读。
4. **沙箱内全自动，落地走人审**：沙箱内 canonical 写=auto；出沙箱写删/push/合主
   分支/对外发送=GATED，只在人审独立子流程发生，永不在自动循环内。

## 门控序列（10 态，M1a 已实现）

```
INIT → PROFILE(A/C 二分，变异测试二次校验) → SELECT_PARENT → REFLECT(串行) →
CHECK_REFLECTION(弱门) → PROPOSE(builtin) → PATCH(import 白名单+危险门) →
EVALUATE(verifiable pytest) → ACCEPT(no-regression 兜底) → ARCHIVE(lineage+rollback) →
LOOP/STOP
```

- **INIT**：创建 run 目录，写首条 event。
- **PROFILE**：A/C 二分（有测 + 基线全绿 + 变异被杀 → A；否则 C）。tier 在首次
  PROFILE 冻结，resume 不重跑（铁律4）。B 档（锚）在 M2 实现。
- **SELECT_PARENT**：冷启动取 base，否则取 lineage 尾版。
- **REFLECT**：M1a 串行单条反思（M3 接入真 LLM 并行 fanout）。
- **CHECK_REFLECTION**：弱结构门，过滤空/无效反思。
- **PROPOSE**：内置确定性 backend（M3 换真 LLM）。
- **PATCH**：import 白名单 + AST 危险调用门 + 沙箱 realpath 边界（越界 → REJECT）。
- **EVALUATE**：A 档跑 pytest；禁网/凭证隔离/HOME 监狱；grader_exit_code 映射
  score∈{0,1}。B/C 档 evaluate 在 M2/M3 接入。
- **ACCEPT**：no-regression 硬门兜底——任一任务从 pass 退化到 fail → 硬 REJECT；
  无退化 → ACCEPT。M1b 升级为 PACE e-process（confseq）。
- **ARCHIVE**：lineage append-only + 版本快照 + rollback 能力。

强制人审门（出沙箱动作）与累计漂移熔断（三计数器：no_progress / static_reject /
forced_review）为后续里程碑（M1b）加硬。

## M1a 当前能力

- A 档可验证目标（有 pytest / 退出码）的端到端自迭代闭环：改进→沙箱验证→采纳→lineage。
- `cli rollback`：回滚 archive 到历史版本。
- `cli replay`：删 state.json 后从 events.jsonl 重建 RunState（崩溃一致性）。
- 评测子进程禁网 + 凭证隔离 + 沙箱 realpath 边界负向用例全过。

## M1b+ 计划（尚未实现）

- PACE e-process acceptor（confseq 替换 no-regression 兜底）。
- 三计数器熔断（no_progress / static_reject / forced_review）。
- AST 危险调用全清单扩充 + 变异测试有效性门加硬。
- 人审非阻塞待审队列（gate_human 完整实现）。
- 异构 judge、自欺指数、自举均为后续里程碑。
- `review` / `land` / `diff` 子命令（M1b+）。

## 用法

```
/self-evolve <target>               # 对目标启动一次自迭代 run
/self-evolve-status <run_id>        # 查看 run 状态
/self-evolve-resume <run_id>        # 从已有 run 续跑
```

底层 CLI（M1a 已实现子命令）：

```
python -m tools.sie.cli init     --target <target>
python -m tools.sie.cli run      --target <target> --run-id <run_id> --base-ref HEAD
python -m tools.sie.cli status   --target <target> --run-id <run_id>
python -m tools.sie.cli replay   --target <target> --run-id <run_id>
python -m tools.sie.cli rollback --target <target> --run-id <run_id> --vid <vid>
```

保留给后续里程碑（未实现）：`review` / `land` / `diff`（M1b+）。
