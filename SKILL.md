---
name: self-evolve
description: "Use to autonomously self-improve a skill/repo via reflect/propose/evaluate/judge/accept behind an un-gameable eval gate. Triggers: self-evolve, 自迭代/进化 skill, 优化仓库."
---

# self-evolve (SKILL)

指向任意 skill / 仓库 / 项目，在 git worktree 沙箱内多轮自动改进它，用不可 game 的
提交门保证「**被采纳 = 真改进**」。

**方法论恒定，信号来源自适应。** reflect → propose → evaluate → judge → accept，全程
反自欺；唯一随目标变的是「评测信号从哪来」。

> **能跑就跑，能核就核，都不能就生成场景让异质判官评,所以没有不能进化的目标。**

## 统一评测框架（评测策略，不是目标等级）

只要目标意图可抽取、可操作化，信号就能造出来，故不存在不可评的目标。下面三者是同一
`evaluate` 契约的三个 **provider**，可叠加（`A+B`、`C+B`…），按可核验强度排序，往上尽量
取、取不到向下兜底,底永远存在：

| 评测策略 | 取信号的方式 | 何时用 | 强度 |
|---|---|---|---|
| **A 程序裁决** | 跑目标自带 / 可生成的测试，pass/fail | 有可执行判据（含可为其生成测试） | 最高（确定、可重放） |
| **B 锚核验** | 改进主张拆成可独立核验的事实锚（URL/文献/SEC/可复现命令），逐锚 verify | 「对」系于外部事实 | 高（独立源、可抽 holdout） |
| **C 生成评测** | harness 生成场景 + rubric，交异质判官（Claude×Codex，prompt 无真值）盲评 | 前两者都取不到 | 较低（异质 + 防合谋闸补强） |

**C 不是「兜底差等舱」，是第三种合法信号通道**：对任何目标都能生成使用场景、从意图写出
可打分 rubric、让两个异质模型盲评取一致性。「取不到任何信号」在工程上不存在。纯 C 默认
走人审落地，是信号最弱时把终判交回人的审慎，**不是「目标不可用」**。
（**落地状态**：C 的「真 coverage（场景对意图的覆盖率）」与对 A/B 的 accept 端平权由
scenario-eval 模块承载；当前代码对纯主观 C 仍取保守处理,`coverage=0`、权重偏低、默认
人审,平权是 scenario-eval 的设计 / 落地方向。）详见
[`docs/philosophy.md`](docs/philosophy.md)、[`reference/signal-providers.md`](reference/signal-providers.md)。

## Pipeline

```
              ┌──────────────────── 一次迭代 ────────────────────┐
  PROFILE ──► REFLECT ──► PROPOSE ──► PATCH ──► EVALUATE ──► JUDGE ──┐
  (定信号源)  (读历史)   (出方案)   (落沙箱)  (取信号)   (码裁决)  │
     │                                                 accept/reject/rollback
     └────────────────────◄── LOOP ◄────────────────────────────────┘
                                │  命中自欺/熔断 → PAUSE(人审) → STOP
```

| 步 | 做什么 | 关键约束 |
|---|---|---|
| **PROFILE** | 给目标定用什么信号评（一次冻结） | 分「信号怎么来」，不分「能不能做」 |
| **REFLECT** | 只读历史 trace，提炼改什么 | 每条结论须引真实 trace 证据，不许臆造 |
| **PROPOSE** | LLM 出候选改动 | LLM 只提议，永不读真值 |
| **PATCH** | 写进 git worktree 沙箱 | 越界 / 危险调用 / 改 IMMUTABLE → 拒 |
| **EVALUATE** | 跑出评测信号（A/B/C provider） | 真值对前面各步不可读 |
| **JUDGE** | 确定性代码裁决采纳与否 | 代码裁决，绝不让 LLM 评自己 |

底层是 10 态门控状态机（实现真相），收敛成上面 6 个直觉动词的映射 + 熔断语义见
[`docs/pipeline.md`](docs/pipeline.md)；各模块方法见 [`docs/modules/`](docs/modules/)。

## 铁律（不可违背）

1. **LLM 提议，代码裁决**,采纳 / 拒绝 / 回滚 / 定信号源全由 harness 确定性代码决定；LLM 绝不评判自己产出。
2. **原始证据只读**,trace / 反思 append-only，`events.jsonl` 唯一真相源，崩溃可 replay 重建。
3. **真值隔离**,测试 / 锚 / 场景的真值对 reflect/propose/patch 物理不可读（holdout 隔离到 `_holdout/`）。
4. **信号源一次冻结**,PROFILE 定的策略首轮冻结，resume 不重评。
5. **沙箱内全自动，出沙箱走人审**,push / 合主分支 / 对外发送只在独立人审子流程发生。

## 自举隔离（`--self`）

candidate 改自己代码时，14 个 IMMUTABLE 决策码（acceptor / judges / verifiable / patch /
events …）从 frozen base ref 物化 + sha256 启动 fail-closed 校验、patch 写 IMMUTABLE 硬拒、
**supervisor 双进程**用 frozen 代码裁决（candidate worktree 永不进 sys.path / 不能自评）。
细节见 [`docs/modules/self-boot.md`](docs/modules/self-boot.md)。

## 成熟度

裁决 / 门控 / 反自欺 / 自举隔离 / crash-replay 全部真实可用并经测试覆盖。`--live` 开真
agent 闭环（proposer / reflector / 双 judge 走 `cc` + `codex exec`）；默认 builtin 确定性
模式（不调外部 CLI）。CLI flag 细节见 [`README.md`](README.md)。

## 用法

```
/self-evolve <target>            # 对目标启动一次自迭代 run（需先部署到 ~/.claude/skills/）
/self-evolve-status <run_id>     # 查看 run 状态
/self-evolve-resume <run_id>     # 从已有 run 续跑
```

底层 CLI：

```
python -m tools.sie.cli init     --target <target>
python -m tools.sie.cli run      --target <target> --run-id <run_id> --base-ref HEAD \
                                 [--max-rounds 3] [--mode auto|gated] [--proposer builtin|llm] \
                                 [--reflect-mode serial|parallel] [--live] [--self --enforce-immutable]
python -m tools.sie.cli status   --target <target> --run-id <run_id>
python -m tools.sie.cli replay   --target <target> --run-id <run_id>
python -m tools.sie.cli rollback --target <target> --run-id <run_id> --vid <vid>
```

## 文档

[`docs/philosophy.md`](docs/philosophy.md)（普适哲学）·
[`docs/pipeline.md`](docs/pipeline.md)（10 态门控全景）·
[`docs/modules/`](docs/modules/)（各模块方法，含 [`scenario-eval`](docs/modules/scenario-eval.md)）·
[`reference/`](reference/)（acceptor 数学 / 锚契约 / 信号 provider）·
[`docs/superpowers/`](docs/superpowers/)（设计规格与 52 任务计划）。
