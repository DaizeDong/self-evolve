---
name: self-evolve
description: "Improve an existing skill or repository through isolated proposals, reproducible evaluation and evidence-based acceptance. Use for self-evolve or skill improvement."
---

# self-evolve (SKILL)

在 git worktree 沙箱内对 skill 或仓库提出修改、运行评测，再按证据决定是否采纳。
通过检查只证明所测范围，不能据此保证所有使用场景都改善。

**方法论恒定，信号来源自适应。** reflect → propose → evaluate → judge → accept，全程
反自欺；唯一随目标变的是「评测信号从哪来」。

> **先确认目标、可执行的评测和私有产物目录，再开始迭代。缺少证据不能算通过。**

## 统一评测框架（评测策略，不是目标等级）

先把目标转成可观察的任务与判据，再选择 `evaluate` 的证据来源。
不同来源可以组合；没有足够证据时明确报告缺口。

| 评测策略 | 取信号的方式 | 何时用 | 强度 |
|---|---|---|---|
| **A 程序裁决** | 跑目标自带 / 可生成的测试，pass/fail | 有可执行判据（含可为其生成测试） | 最高（确定、可重放） |
| **B 锚核验** | 改进主张拆成可独立核验的事实锚（URL/文献/SEC/可复现命令），逐锚 verify | 「对」系于外部事实 | 高（独立源、可抽 holdout） |
| **C 主观评测** | 消费已提供的回归与一致性证据，核验实际 judge 家族 | 有场景但缺少程序判据 | 需报告覆盖率与人工复核边界 |

自动场景生成 `scenario-eval` 尚未实现。缺少回归或一致性证据时，C 不能报告
`no_regression=True`，覆盖率为零。纯 C 默认需要人审。详见
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
| **PROPOSE** | LLM 出候选改动 | LLM 只提议，prompt 排除核验真值 |
| **PATCH** | 写进 git worktree 沙箱 | 越界 / 危险调用 / 改 IMMUTABLE → 拒 |
| **EVALUATE** | 跑出评测信号（A/B/C provider） | prompt 不提供核验真值，实际隔离另验 |
| **JUDGE** | 确定性代码裁决采纳与否 | 代码裁决，绝不让 LLM 评自己 |

底层是 10 态门控状态机（实现真相），收敛成上面 6 个直觉动词的映射 + 熔断语义见
[`docs/pipeline.md`](docs/pipeline.md)；各模块方法见 [`docs/modules/`](docs/modules/)。

## 铁律（不可违背）

1. **LLM 提议，代码裁决**,采纳 / 拒绝 / 回滚 / 定信号源全由 harness 确定性代码决定；LLM 绝不评判自己产出。
2. **原始证据只读**,trace / 反思 append-only，`events.jsonl` 唯一真相源，崩溃可 replay 重建。
3. **真值隔离**,reflect/propose/judge 的 prompt 排除真值。共享账户上的目录分开不等于物理不可读；需要文件读取隔离时另行验证操作系统权限。
4. **信号源一次冻结**,PROFILE 定的策略首轮冻结，resume 不重评。
5. **沙箱内全自动，出沙箱走人审**,push / 合主分支 / 对外发送只在独立人审子流程发生。

## 自举隔离（`--self`）

candidate 改自己代码时，IMMUTABLE 清单内的决策码（acceptor / judges / verifiable / patch /
events …）从 frozen base ref 物化 + sha256 启动 fail-closed 校验、patch 写 IMMUTABLE 硬拒、
Supervisor 用 frozen grader 和 acceptor 处理同一个 candidate worktree；模块解析检查不代替操作系统权限隔离。
细节见 [`docs/modules/self-boot.md`](docs/modules/self-boot.md)。

## 成熟度

先运行 `doctor` 查看证据来源、可修改范围、必需输入和未实现的能力。
`--live` 的 agent 使用已安装的 `llmcall.call(..., mode="agent")`，judge 使用默认模式。
不指定另一套路由、模型或超时。独立性以实际返回 provider 为准；同一家族的别名不算
两个独立评审。保留每次调用的 provider、attempts 与失败原因。

运行记录、候选工作树和 agent 临时目录都放入经验证的 PRIVATE 伴生仓。
设置 `SELF_EVOLVE_CONFIG` 或 `SELF_EVOLVE_DATA_DIR`，刷新可见性证明；真实 DATA
在私有仓中版本化，缺少证明时写入失败。agent 每次使用独立 cwd，结束后清理；这不能
代替操作系统沙箱。默认 builtin 用于确定性证据流程。CLI 细节见 [`README.md`](README.md)。

## 用法

```
/self-evolve <target>            # 对目标启动一次自迭代 run（需先部署到 ~/.claude/skills/）
/self-evolve-status <run_id>     # 查看 run 状态
/self-evolve-resume <run_id>     # 从已有 run 续跑
```

底层 CLI：

```
python -m tools.sie.cli doctor   --target <target>
python -m tools.sie.cli init     --target <target>
python -m tools.sie.cli run      --target <target> --run-id <run_id> --base-ref HEAD \
                                 [--max-rounds 3] [--mode auto|gated] [--proposer builtin|llm] \
                                 [--reflect-mode serial|parallel] [--live] [--self --enforce-immutable]
python -m tools.sie.cli status   --target <target> --run-id <run_id>
python -m tools.sie.cli replay   --target <target> --run-id <run_id>
python -m tools.sie.cli rollback --target <target> --run-id <run_id> --vid <vid>
```

上述命令从 skill 仓库运行。其他 cwd 或安装 junction 使用
`python <skill绝对路径>/tools/sie_cli.py <子命令> ...`，入口按自身位置解析资源。

## 文档

[`docs/philosophy.md`](docs/philosophy.md)（普适哲学）·
[`docs/pipeline.md`](docs/pipeline.md)（10 态门控全景）·
[`reference/`](reference/)（acceptor 数学 / 锚契约 / 信号 provider）·
[`docs/superpowers/`](docs/superpowers/)（设计规格与 52 任务计划）。

### 模块文档 [`docs/modules/`](docs/modules/)

一模块一篇，按 pipeline 顺序排列。

| 模块 | 讲什么 |
|---|---|
| [`profile.md`](docs/modules/profile.md) | 探测目标能用什么信号衡量，装配 evaluator 组合，一次冻结进 `target.json` |
| [`reflect.md`](docs/modules/reflect.md) | 从历史 trace 诊断出 findings，并行反思与跨路去重 |
| [`check-reflection.md`](docs/modules/check-reflection.md) | 反思的 trace 证据门；全部不过则该轮直接 STATIC_REJECT，不进 propose |
| [`propose.md`](docs/modules/propose.md) | findings 翻成整文件改动提议；proposer 只提议，永不参与裁决 |
| [`patch.md`](docs/modules/patch.md) | 落盘前唯一一道静态准入门：import 白名单、AST 危险调用、IMMUTABLE 硬拒、沙箱 realpath 边界 |
| [`evaluate.md`](docs/modules/evaluate.md) | 信号枢纽：选 provider，把异构证据收口成同构 `paired` + coverage |
| [`judge.md`](docs/modules/judge.md) | judge 按实际返回的已知不同 provider 家族核验独立性并给出主观分，并给它套 pairwise_agreement 与 judge↔锚校准两道信任闸 |
| [`scenario-eval.md`](docs/modules/scenario-eval.md) | **设计目标，尚未实现**：生成场景 + rubric，给纯 C 一个真 coverage 与 accept 端平权 |
| [`accept.md`](docs/modules/accept.md) | 消费上游成对证据，汇总成统计决策：归档落地 / 丢弃 / 交人审 |
| [`gates.md`](docs/modules/gates.md) | 人审队列契约、selfdeception 多闸接线、熔断阈值 |
| [`archive.md`](docs/modules/archive.md) | 版本谱系、快照、回滚、Pareto 硬维门、库漂移冷藏 |
| [`events.md`](docs/modules/events.md) | `events.jsonl` 唯一真相源，以及 replay 重建运行状态 |
| [`agents.md`](docs/modules/agents.md) | 统一 agent 调用层：`invoke` / `cross_check`，任意阶段可跨家族交叉校验 |
| [`self-boot.md`](docs/modules/self-boot.md) | `--self` 自举装配：IMMUTABLE 物化 + 启动哈希 fail-closed + supervisor 双进程裁决 |
