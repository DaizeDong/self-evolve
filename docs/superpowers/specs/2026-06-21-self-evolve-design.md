# self-evolve 设计规格（Design Spec）

- **日期**：2026-06-21
- **状态**：设计已获用户批准（全光谱方案 B）；待 subagent 校验 + 用户复核 → 转 writing-plans
- **作者**：brainstorming 流程（用户 + 5 视角 subagent 收敛）
- **依据**：本仓 `docs/自改进Agent调研.md`（全景）、`docs/02-crossval-deepdive.md`（交叉验证）

---

## 1. 目标与非目标

**目标**：一个用于 **agent 自我迭代开发工程工具**（skill / 仓库 / 项目）的 Claude Code skill `self-evolve`。把"读历史→反思→改→评测→采纳→归档"做成一个**确定性、可复现、不自欺**的闭环：你把它指向任意目标，它在沙箱里自动多轮迭代改进该目标，并用不可 game 的提交门保证"被采纳的改动是真改进"。以**现实工程效果**为唯一标准（无发表包袱），公开发布 + 自用。

**非目标**：① 不追求论文/发表新意（不为新意牺牲实用）；② 不做权重训练/微调（只改 scaffolding/prompt/代码/配置等文本资产）；③ 不替代人对"要不要把改动落地到真仓库"的最终判断（不可逆动作永远人审）。

---

## 2. 锁定决策（设计前置约束，不可推翻）

| # | 决策 | 落点 |
|---|---|---|
| D1 | **范围**：工程工具进化（skill/仓库/项目），分层——可验证内核当骨干，无 ground-truth 目标用可插拔护栏。**全光谱一次到位（方案 B）**：A/B/C 三档信号 + 锚点适配器 + 自欺指数 v1 全做。 | signal profiler + tiers |
| D2 | **形态**：方法论 skill（SKILL.md 门控）+ 轻量确定性 Python harness（裁决用代码）+ subagent 编排；搜索环节**可选**接 GEPA/OpenEvolve，默认内置。 | 全仓布局 |
| D3 | **迭代对象**：主改外部目标；自举（改自身）为**可选**路径，默认关闭，递归隔离 + 冻结 supervisor。 | `--self` |
| D4 | **安全**：worktree/沙箱内全自动；不可逆/外向动作（commit/push/合主分支/删文件/对外发送）一律 GATED 人审。 | action 分级表 |
| R1 | **部署**：作为 `self-evolve` 仓内 skill，junction 到 `~/.claude/skills/self-evolve`，加进 SyncClaudeSkills（9:00 pull）。仓库已由 `self-improving-research-agent` 重命名为 `self-evolve`。 | junction |
| R2 | **人审通道**：待审队列 + Discord relay 推送到手机 + CLI/slash 回执（`review --approve/--reject`、`/self-evolve-resume`）。 | gate_human |

---

## 3. 架构总览与仓库布局

**核心原则**：LLM 只"提议"（反思/候选生成/主观评审）；所有"采纳/拒绝/回滚/裁决"由 harness **确定性代码**做。搜索引擎（GEPA/OpenEvolve）只能进候选生成步，**绝不允许评判自己的产出**。原始证据（trace/反思）一等公民，append-only 只读，永不被 LLM 改写。

```
self-evolve/                      (= CodesSelf/self-evolve, junction → ~/.claude/skills/self-evolve)
  SKILL.md                        # 门控序列总纲(给主 agent 读)
  commands/                       # slash 命令(junction 同步)
    self-evolve.md                #   /self-evolve <target> ...
    self-evolve-status.md
    self-evolve-resume.md
  tools/sie/                      # 确定性 harness(可独立 python -m sie.cli 跑)
    cli.py                        #   CLI 入口
    statemachine.py               #   9 态主循环
    state.py                      #   RunState + 原子 checkpoint(tmp+rename)
    reflect.py                    #   调度 N 个独立反思 subagent(MARS)
    check_reflection.py           #   反思正确性校验(BenchTrace)
    propose.py                    #   meta 汇总→scoped patch 规约(HarnessFix);可选委托 backend
    patch.py                      #   worktree 内逐 patch 应用 + contract 静态检查
    profile.py                    #   信号发现/目标画像→verifiability_score→tier
    probes/                       #   可插拔探针注册表(exec/ci/fact/self-test 合成)
    evaluate.py                   #   分层评测,产 per-task 分向量(不裁决)
    verifiable.py                 #   A 档:跑 test/build/CI/grader,快照哈希锁定
    anchors.py                    #   B 档:抽事实锚 + edgartools/EDGAR/价格核查 + EVE 边际增益
    judges.py                     #   异构 judge 适配器(强制≠proposer 家族)
    acceptor.py                   #   PACE anytime-valid e-process 提交门
    archive.py                    #   DGM lineage + GEPA Pareto + Library Drift 退役
    selfdeception.py              #   自欺指数(judge 增益 vs 锚增益背离)监控
    gate_human.py                 #   不可逆/外向动作分级表 + 待审队列 + Discord 推送
    backends/                     #   gepa_backend.py / openevolve_backend.py(可选)
    notify.py                     #   复用 the notifier
  workflows/                      # JS subagent 编排
    reflect-fanout.js             #   N 个独立反思(MARS)
    review-fanout.js              #   异构 judge 评审
  reference/
    target_contract.md           # 被改对象接口契约
    acceptor_math.md             # PACE 配对 e-process 公式与参数
    tiers-and-anchors.md         # 信号分档与锚点抽取规范
    runbook.md                   # 故障/回滚/人审/熔断 SOP
  metrics/                        # append-only 账本(verdicts/events 摘要)
  tests/                          # harness 自测(见 §11)
  learnings.md                    # 跨会话经验(stop-hook 维护,append-only)
  docs/                           # (已有调研)+ specs/
```

---

## 4. 门控主循环（确定性状态机，9 态）

每态：**输入 → 动作（标注 确定性/LLM）→ 产出工件**。每态结束原子 checkpoint；`events.jsonl` 为真相源，崩溃可重放。

| 态 | 名称 | 动作 | 谁做 | 产出 |
|---|---|---|---|---|
| 0 | INIT | 读 target+contract；建 worktree 沙箱；载 archive；**DGM 加权采样**选 parent 版本(非贪心) | 代码 | `run/<id>/state.json` |
| 1 | REFLECT | spawn N=3 **独立**反思 subagent(MARS,互不可见)读历史 trace(只读)+上轮失败 replay；逐条过 **反思正确性校验**(BenchTrace,<阈值丢) | LLM 提议→代码校验 | `reflections/<r>/*.json` |
| 2 | PROPOSE | meta-agent 汇总通过校验的反思→**scoped patch 规约**(HarnessFix:限文件/段+声明修哪条失败)；**可选**委托 GEPA/OpenEvolve 当候选 backend | LLM(默认内置) | `proposals/*.json` |
| 3 | PATCH | worktree 内逐 patch 应用(临时 branch,可逐个回退)；破坏 contract 静态检查(语法/import/SKILL schema)即拒该 patch | 代码 | patched worktree |
| 4 | EVALUATE | 按 §5 目标画像分层评测：A 跑 grader / B 抽锚核查 / C 内部一致性；含**固定回归集 + 历史失败 replay** + novelty 门控新主题。只产分向量 | 代码(judge 是 LLM 子调用) | `evals/<r>.json` |
| 5 | ACCEPT | **PACE acceptor 提交门**(配对 e-process,控误提交率)；no-regression 任一回退**硬覆盖**为 REJECT；三态 ACCEPT/REJECT/CONTINUE | 代码 | `acceptor/<r>.json` |
| 6 | ARCHIVE | ACCEPT 进 archive(lineage + Pareto 多目标,不线性覆盖)；Library Drift 活跃上限+outcome-driven 退役(冷藏不删)；写回 learnings.md | 代码 | `archive/` 更新 |
| 7 | HUMAN_GATE | 扫待审队列(不可逆/外向动作)→阻塞+Discord 推送,等回执 | 代码 | `pending_actions.jsonl` |
| 8 | LOOP/STOP | 检查停止条件(达标/预算/连续无 accept/自欺指数报警/熔断)→回 0 或终止 | 代码 | — |

---

## 5. 评测与防自欺脊柱（全光谱）

1. **信号发现/目标画像**（`profile.py`+`probes/`）：程序化探针探测客观信号 → `verifiability_score∈[0,1]` → 落 **A 硬内核 / B 半可验证 / C 纯主观**（可叠加）。**按信号选策略，不按目标类型选分支**（防四不像）。探针：exec(test/build/CLI 退出码)、ci、fact(产物可核验字段)、self-test 合成(OpenSkill 式从 README/docstring/历史轨迹抽锚自建练习题)。⚠️ exec 探针须二次校验"测试是否真断言/非全 skip"，防假 grader。
2. **A 档**（`verifiable.py`）：真实 test/build/CI/grader 退出码当硬 reward；**测试集快照哈希锁定**防 exfiltration（Meta-Agent Challenge 实证 agent 会窃改测试放水）；MOSS trial-worker 重放历史失败 + health-probe 回滚。
3. **B 档**（`anchors.py`）：抽可外部核验子断言(市值/营收/毛利/内部人持股/8-K 日期…)→ edgartools/EDGAR/价格核查算事实准确率/幻觉率；**EVE-Agent 边际增益**:每条结论挂逐字证据 span(来源 URL+抓取时间戳),按"加该证据是否真提升正确率"打分(非绝对准确率,防堆水货);前瞻断言(catalyst/guidance)挂日历到期异步回查;OpenSkill 自建练习题把部分 B **升格成 A**。
4. **C 档兜底**（`evaluate.py` 内）：无客观信号时硬门是**"不退化"而非"进步"**——内部一致性(报告内不矛盾/引用 span 真存在/格式合规)+ 改后回跑历史成功轨迹;acceptor 默认 conservative(不显著变好就不提交);**长期无进展释放阀**(借 interestingness 衰减:连续无进展则降阈或升人审,防"诚实变瘫痪")。
5. **PACE acceptor**（`acceptor.py`）：全档统一,anytime-valid e-process **配对**检验替代"涨了就留"(实证拦 30-42% 假提交/72-100% 噪声自改);**配对统计量优先级 A 硬信号 > B 锚增益 > C 主观分(极低权重,绝不单独触发提交)**;控误提交率 α(默认 0.05),e-value 越阈早停省算力。三态 ACCEPT/REJECT/CONTINUE。
6. **异构 judge**（`judges.py`+`review-fanout.js`）：评审强制换模型家族(复用本机 `codex`=gpt-5.5 / `gemini-search` / `minimax`),禁与 proposer 同族;算 judge 间一致性(Krippendorff α)低则升人审;位置/长度去偏。
7. **自欺指数**（`selfdeception.py`）：每轮 `judge 报告增益 − 外部锚真实增益`,背离持续放大=正在 reward hack→自动暂停告警(BenchTrace:反思<30%正确,背离是前兆)。**锚点覆盖率 <阈值(默认 30%)→该轮禁止自动 ACCEPT,强制人审**。

---

## 6. 安全与自治

- **沙箱**：全程 git worktree + 隔离目录；评测子进程禁网/白名单代理(防 exfiltration 走网络外传答案,且审查出站产物——答案不得编码进文件名/日志/commit message);资源/时长配额;沙箱进程不带 push 凭证。
- **archive/回滚**：DGM lineage append-only,任意版本一键 `rollback`(MOSS health-probe);原始证据/反思只读一等公民(Useful Memories 实证持续改写会跌破不改 baseline);Library Drift 活跃上限+outcome-driven 退役(冷藏不删);每 K 轮全量回归防能力侵蚀(CPE);重写版必须在 acceptor 上打赢原始版才生效。
- **action 分级表（`gate_human.py`,写死不可绕过）**：sandbox-internal(worktree commit/eval/archive)=auto;irreversible/outward(push/合主分支/删文件/对外发送)=GATED 阻塞;只读外部 API(SEC/价格查询)豁免,只 gate 写/发。`--mode auto` 只放开沙箱内。
- **人审通道（R2）**：GATED 动作入 `pending_actions.jsonl`→Discord 推送→`/self-evolve-resume` 或 CLI `review --approve/--reject`。
- **自举隔离（D3）**：`--self` 默认关；开启时**冻结只读 supervisor 进程**(代码副本不可被本轮 patch 触及)负责跑评测与裁决,candidate 永不能裁决自己(SICA overseer);递归隔离到独立 worktree。
- **熔断**：连续 N 轮全拒/锚无进展熔断;轮数/预算硬上限;每轮检查 kill-switch 哨兵文件;每 K 轮人在环抽样审计校准 judge/锚漂移。

---

## 7. 数据/状态布局

```
run/<run_id>/
  state.json            # RunState(原子 tmp+rename)
  events.jsonl          # append-only 事件流(真相源,可重放)
  target.json           # 画像:tier/verifiability_score/探针证据
  reflections/<r>/*.json
  proposals/*.json
  traces/<task>/*.json  # 评测任务完整 trace(只读,GEPA/反思读这个)
  evals/<r>.json        # per-task 分向量 + anchor 明细 + judge 原始分
  acceptor/<r>.json     # e-process wealth/threshold/decision
  pending_actions.jsonl # 待人审动作
archive/
  versions/<vid>/       # 版本快照(git ref + 元数据)
  lineage.json          # 进化树边
  pareto.json           # 当前 Pareto 前沿
  retired.jsonl         # 退役(冷藏,append-only)
```

---

## 8. 接口

**CLI**：`python -m sie.cli {init|run|status|review|replay|rollback|diff}`
- `init --target <path> --base <ref> --run-id <id>`
- `run --run-id <id> [--rounds N] [--budget $] [--backend builtin|gepa|openevolve] [--mode auto|gated] [--self]`
- `status --run-id <id>`（态 + Pareto + 真提交率 + 假提交拦截数 + 自欺指数 + 待审队列）
- `review --run-id <id> [--approve <aid>|--reject <aid>]`
- `replay --run-id <id> --round R`（事件流审计）
- `rollback --to <vid>`；`diff --a <vid> --b <vid>`

**slash**：`/self-evolve <target> [...]`、`/self-evolve-status`、`/self-evolve-resume <run-id>`

**target_contract**（`reference/target_contract.md`）：`probe()` 列可改资产 glob；`tasks()` 产评测任务；`grade(task)→(score_vector, verifiable:bool)`；`regression_set()` 固定回归+历史失败 replay。把 D1 分层落成 contract 内的 `if verifiable` 分支。

---

## 9. 测试策略（harness 自测，`tests/`）

- **acceptor 噪声回归（最高优先）**：喂"纯噪声序列/已知真增益序列",验证 PACE 的"纯噪声自改拒绝率"≈1、"真增益采纳率"高、误提交率≤α。这是防自欺命门,必须单测锁参数。
- **profiler fixtures**：构造已知 tier 的样例目标(带有效 test 的 repo / 全 skip 的假 test / 带锚字段的调研产物 / 纯文风文本),验证分档正确 + 假 grader 被二次校验抓出。
- **anchors 核查**：mock edgartools 返回,验证事实准确率/边际增益计算 + 锚覆盖率门。
- **gate/action 分级**：验证 outward 动作一定进队列、sandbox-internal 一定放行、只读 API 豁免。
- **端到端冒烟**：① 一个小型可验证 repo(有 pytest)跑通 A 档全闭环;② 一个调研 skill 样例跑通 B 档(锚+异构 judge+acceptor);③ C 档纯文本验证"不退化门"生效。
- **崩溃重放**：杀进程后从 events.jsonl 重建 state,断言一致。

---

## 10. 借鉴机制溯源

PACE(2606.08106)=acceptor 提交门 · DGM(2505.22954)=lineage archive+加权采样 · GEPA(2507.19457)=Pareto 多目标+反思变异 backend · OpenEvolve=island/MAP-Elites backend · MARS(2509.20502)=独立反思+异构 judge · BenchTrace(2605.29225)=反思正确性校验 · HarnessFix(2606.06324)=scoped patch · Library Drift(2605.19576)=活跃上限+退役 · Useful Memories(2605.12978)=原始证据只读 · CPE(2605.09315)=每K轮全量回归 · MOSS(2605.22794)=trial-worker+health-probe 回滚 · OpenSkill(2606.06741)+EVE-Agent(2605.22905)=verification anchor+边际增益 · Meta-Agent Challenge(2606.04455)=exfiltration 防线+快照哈希 · SICA=自举 overseer · Panickssery(2404.13076)=异构防自偏好 · obra/superpowers=门控序列+learnings.md/stop-hook。

---

## 11. 风险与缓解（收敛清单）

| 风险 | 缓解 |
|---|---|
| 状态非原子→崩溃留脏 state | events.jsonl 真相源 + tmp+rename + 重放重建 |
| acceptor 实现错=橡皮图章 | 独立噪声回归单测锁参数(§9 首项) |
| B 档锚覆盖率太低,70% 未锚区被主观分拖假涨 | 覆盖率<阈值禁自动 ACCEPT 强制人审；judge 只对挂 span 断言计分 |
| skill 学会 game 锚本身(堆易核验水货) | EVE 边际增益(非绝对准确率)+ 锚集换血 + 前瞻到期回查 |
| exfiltration 走隐蔽信道 | 禁网+白名单+出站产物审查+真值与 candidate 进程物理隔离 |
| 异构 judge 共同偏置(都爱长报告) | 长度/位置去偏 + 简洁度作 Pareto 一维 |
| 评测集 mode collapse,窄分布过拟合 | novelty/coverage 门控 + 回归集换血 + 时间隔离 |
| 无人值守误差累积 | 自欺指数刹车 + 每轮回归 replay + 熔断 + 人在环抽样校准 |
| 自举改坏自己 | 默认关 + frozen supervisor 双进程 + candidate 不裁决自己 |
| backend 输出格式漂移 | backends 统一 schema,违约 reject 而非尽力解析 |
| C 档"不退化门"导致永不改(瘫痪) | 长期无进展释放阀(降阈/升人审) |

---

## 12. 校准参数（默认值，A 档目标上先标定再迁 B/C）

`N_reflectors=3` · `reflection_correctness_threshold` · `acceptor α=0.05` · `anchor_coverage_floor=0.30` · `selfdeception_alert_band` · `active_cap`(skill 库上限) · `K`(全量回归周期) · `no_progress_circuit=N 轮` · `judge_families≥2`(codex/gemini/minimax) · `judge_agreement_floor`(Krippendorff α)。

---

## 13. 验收标准 / MVP 定义（= 全光谱，方案 B）

v1 即满足：① 三档信号 profiler 工作且假 grader 被抓；② A 档端到端在真 repo 上跑通并被 acceptor 正确采纳/拒绝；③ B 档锚点+边际增益+异构 judge+覆盖率门工作(以 market-intel/small-cap-deepdive 为目标样例,复用 edgartools);④ C 档"不退化门"生效;⑤ PACE acceptor 噪声单测通过(纯噪声拒绝率≈1);⑥ 自欺指数监控+熔断+Discord 人审门贯通;⑦ archive 一键回滚 + events 重放可用;⑧ `--self` 自举隔离冒烟通过(默认关)。

---

## 14. 开放项（writing-plans 前需确认/计划期决定）

- 异构 judge 调用预算上限(影响 §5.6 成本)。
- PACE 是否有可用 repo,还是按论文从零实现 e-process(影响 acceptor.py 工作量;倾向自实现 + 噪声单测验证)。
- 校准参数初值先按文献默认跑一轮再校准(§12)。
- 旧目录 `CodesSelf/self-improving-research-agent` 句柄释放后清理(会话结束后)。
