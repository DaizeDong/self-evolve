# self-evolve (SKILL)

指向任意 skill / 仓库 / 项目，在 git worktree 沙箱内多轮自动改进它，用不可 game 的
提交门保证"被采纳 = 真改进"。三档评测（A 可验证 / B 外部锚 / C 主观异质 judge）+
自举隔离，全程反自欺。

## 铁律（不可违背）

1. **LLM 只提议，代码裁决**：采纳 / 拒绝 / 回滚 / 分档由 harness 确定性代码决定；
   搜索 / 反思 / 评审才用 LLM，绝不让 LLM 评判自己产出。
2. **原始证据只读**：trace / 反思 append-only，永不被 LLM 改写（events.jsonl 是唯一真相源，
   计数器只能经事件 delta 写入，崩溃可 replay 重建）。
3. **数据隔离（铁律5）**：frozen 锚真值 / holdout 测试真值对 REFLECT / PROPOSE / PATCH 不可读
   （holdout 物理隔离到 `_holdout/`，target.json 只存引用 + 计数）。
4. **tier 首次冻结**：A/B/C 档在首次 PROFILE 冻结，resume 不重跑。
5. **沙箱内全自动，落地走人审**：沙箱内 canonical 写 = auto；出沙箱写删 / push / 合主分支 /
   对外发送 = GATED，只在人审独立子流程发生，永不在自动循环内。

## 门控序列（10 态，A/B/C/self 全实现）

```
INIT → PROFILE(A/B/C 可叠加，变异测试二次校验) → SELECT_PARENT →
REFLECT(N=3 并行 MARS) → CHECK_REFLECTION(BenchTrace 门) → PROPOSE →
PATCH(import 白名单 + AST 危险门 + IMMUTABLE 硬拒 + 沙箱边界) →
EVALUATE(A:pytest / B:锚 coverage+holdout 抽检 / C:异质 judge) →
ACCEPT(PACE e-process + 各档门 + 自欺多闸 + 强制人审) →
ARCHIVE(Pareto 硬维门 + lineage + rollback + Library Drift) → LOOP / STOP
                                                              ↘ 9.5 PAUSE_FOR_HUMAN
```

- **PROFILE**：A（有测 + 基线全绿 + 变异被杀）/ B（≥24 真锚字段）/ C（主观）**可叠加**
  （如 "A+B"）；tier 首次冻结。
- **REFLECT**：N=3 独立 MARS 反思并行 fanout（只读历史 trace），meta 汇总去重。
- **CHECK_REFLECTION**：BenchTrace 门——每条 finding 须引用真实历史 trace 证据，杜绝臆造。
- **PATCH**：import 白名单 + AST 危险调用门 + **IMMUTABLE 路径硬拒**（自举时）+ 沙箱
  realpath 边界（越界 → REJECT）。
- **EVALUATE**：A 档 pytest（禁网 / 凭证隔离 / HOME 监狱）；B 档逐锚 verify + marginal_gain
  配对 + coverage 门 + 每 K 轮 holdout 抽检；C 档异质 judge（Claude + Codex，prompt 无真值）
  + pairwise_agreement + judge↔锚校准。
- **ACCEPT**：**PACE e-process acceptor**（confseq，缺则 ONS 回退，type-I ≤ α 已验证）；
  no-regression 硬门；B 档 n_min + 独立性下限 + evalue_max_step 三门；C 档双向 α + 纯 C
  强制人审 + Codex 不可用禁单 Claude 自动 ACCEPT；自欺多闸（低锚增益 / holdout 背离 /
  judge-anchor 背离 / 累计漂移）；命中 → 态 9.5 强制人审。
- **ARCHIVE**：Pareto 多维硬维门（软涨硬平不可选 parent，只冷藏）+ lineage append-only +
  版本快照 + rollback + Library Drift retire_stale。
- **熔断**（经事件持久的三正交计数器 + drift）：no_progress / static_reject /
  forced_review / drift_count 各达阈停机；no_progress 释放阀仅升人审频率、绝不自动降阈采纳。

## 自举隔离（`--self`，铁律3 决策码不可改）

candidate 改自己代码时，决策码（14 个 IMMUTABLE 文件含 acceptor / judges / verifiable /
patch / proxy / events …）从 frozen base ref 物化、记 sha256：启动哈希 fail-closed 校验、
patch 写 IMMUTABLE 路径硬拒、**supervisor 双进程**用 frozen 代码裁决（candidate worktree
永不进 sys.path）、自举评测用 frozen grader（candidate 不能自评 / 自打分）。

## 成熟度（重要）

裁决 / 门控 / 反自欺 / 自举隔离 / crash-replay 全部为**真实可用代码**（521 测试）。
**生成式 LLM 接缝目前为确定性占位 / 桩**，真正"自我迭代"前需填：
① `tools/sie/backends/builtin.py` propose 接真模型；
② `workflows/{reflect,review}-fanout.js` 接真 Claude / Codex 子代理；
③ B 档真实 judge 评分接线。架构已留钩子。

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
                                 [--max-rounds 3] [--mode auto|gated] [--self --enforce-immutable]
python -m tools.sie.cli status   --target <target> --run-id <run_id>
python -m tools.sie.cli replay   --target <target> --run-id <run_id>
python -m tools.sie.cli rollback --target <target> --run-id <run_id> --vid <vid>
```

档位 / 锚契约、acceptor 数学见 [`reference/`](reference/)；设计规格与 52 任务计划见
[`docs/superpowers/`](docs/superpowers/)。
