# self-evolve 设计规格（Design Spec v3.1）

- **日期**：2026-06-21（v3.1：judge 池收敛为 Claude+Codex，去 gemini/minimax；其余同 v3）
- **状态**：架构获批；两轮对抗式校验全部 blocking 已闭合；用户已复核批准 → writing-plans
- **范围**：全光谱，预算 ~50-70h，内部里程碑 M1a/M1b/M2/M3/M4
- **依据**：本仓 `docs/自改进Agent调研.md`、`docs/02-crossval-deepdive.md`
- **v3 变更**：见 §0

---

## 0. v3 相对 v2 的关键变更（校验闭合记录）

- **防自欺（最重要）**：frozen 锚集拆 visible/holdout；锚文本对 proposer 不可见（铁律5）；锚集规模下限+有效独立锚数+同源去相关；累计漂移预算由 holdout/全量回归背书；judge 校准改用独立 holdout 集。
- **状态机**：CONTINUE 仅随机档(B/C)、设 `continue_count` 上限+落点(→REJECT)、A 档二态；三类计数器分离(`no_progress`/`static_reject`/`forced_review`)各自熔断阈，消除活性漏洞与计数矛盾；tier 上调改为仅新 run。
- **接口**：`grade()` 补 per-task `grader_exit_code/task_passed`，喂 A 档配对。
- **里程碑**：M1 拆 M1a/M1b；confseq spike 设 M1 第 0 步硬前置；出站完整审查挪 M2（M1 仅禁网）；M2 自建题延后；M3 按 R3 两档验收。
- **安全**：出站改 harness 代发（candidate 不能自选 ticker/时序）+ 跨请求序列异常检测；承认低带宽时序信道为残余风险。
- **（v3.1）judge 池**：收敛为 **Claude + Codex** 两家（不装 gemini/minimax）；Codex=唯一独立非 proposer judge → **程序化锚成为主防自欺信号、judge 为辅**；移除 R3 登录/付费前置。

---

## 1. 目标与非目标

**目标**：用于 agent 自我迭代开发**工程工具**（skill/仓库/项目）的 Claude Code skill。指向任意目标，沙箱内自动多轮改进，用不可 game 的提交门保证"被采纳=真改进"。现实工程效果为唯一标准（无发表包袱），公开发布 + 自用。
**非目标**：不追发表新意；不做权重训练；不替代人对"落地到真仓库"的最终判断。

---

## 2. 锁定决策

| # | 决策 |
|---|---|
| D1 | 工程工具进化，A/B/C 分层信号，**全光谱**，预算 ~50-70h，里程碑 M1a→M4。 |
| D2 | 方法论 skill（SKILL.md 门控）+ 确定性 Python harness（代码裁决）+ subagent 编排；搜索可选 GEPA/OpenEvolve，默认内置。 |
| D3 | 主改外部目标；自举 `--self` 默认关、递归隔离（M4）。 |
| D4 | 沙箱内全自动；对外落地=人审独立子流程，不在自动循环内。 |
| R1 | `self-evolve` 仓内 skill，junction 到 `~/.claude/skills/self-evolve`，进 SyncClaudeSkills。 |
| R2 | 人审=待审队列+Discord 推送+CLI/slash 回执，非阻塞。 |
| R3 | judge 池=**Claude + Codex 两家**（仅此两家，不装 gemini/minimax）。Codex（走 codex skill，最强模型）=唯一真正非 proposer 家族的独立 judge；Claude=去偏后的次 judge。α 退化为两判官配对一致性。**无登录/付费前置**（codex 已就绪）。代价：judge 异构性变薄 → **程序化锚（frozen/holdout/EVE 边际增益）= 主防自欺信号，judge 为辅**。 |

---

## 3. 设计铁律（防自欺地基）

1. **LLM 只提议，代码裁决**：采纳/拒绝/回滚/分档由 harness 确定性代码；搜索引擎只进候选生成步，绝不评判自己产出。
2. **原始证据一等公民**：trace/反思 append-only 只读，永不被 LLM 改写。
3. **IMMUTABLE 裁决代码集**（`statemachine/acceptor/judges/verifiable/anchors/selfdeception/gate_human/profiler 判定/supervisor loader/沙箱边界判定`）从 frozen base ref 按内容哈希加载，不在 candidate 可写 glob 内，patch 命中即硬拒。
4. **tier 仅在 run 首次 PROFILE 冻结**，resume 从 `target.json` 加载、**不重跑 PROFILE**；tier 上调只通过开新 run 实现，当前 run 内不支持（消除状态机悬空）。
5. **（新）数据隔离**：frozen 锚集的 claim/verified 值/marginal_gain、测试真值，对 REFLECT/PROPOSE/PATCH 进程**一律不可读**（只暴露 task 输入）；与 judge"prompt 不得携带真值"同级，属 IMMUTABLE 数据隔离规则。防候选把答案硬编进 skill 来过拟合标尺。

---

## 4. 门控主循环（确定性状态机，10 态，显式转移 + 计数模型）

> 主循环全程沙箱内，只产"归档候选版本"，**不对真目标落地**。落地=人审独立子流程（末尾）。
> **三类计数器（互相正交）**：`no_progress`=acceptor 的 REJECT/CONTINUE 轮；`static_reject`=态4空返回+态5全拒；`forced_review`=态9.5 强制人审轮。各有独立熔断阈（§12）。

| 态 | 动作 | → 下一态（条件） |
|---|---|---|
| 0 INIT | 读 target+contract；建 worktree（失败→`INIT_FAILED` 干净退出可 resume）；run_id 唯一锁 | →1（首次）/ →2（resume，跳 PROFILE） |
| 1 PROFILE | 跑探针→`verifiability_score`→**冻结 tier**(A/B/C 可叠加)；exec 探针变异测试二次校验（注入 bug 须变红，杀不死则信号作废）；fact 探针锚字段代码判定；**抽锚用异构≠proposer，锚文本按铁律5 隔离**；frozen 锚集拆 visible/holdout（§5.3）。写 `target.json` | →2 |
| 2 SELECT_PARENT | DGM 加权采样选 parent（冷启动 archive 空→parent=base ref） | →3 |
| 3 REFLECT | N 反思（M1 串行；M3 升 N=3 并行 MARS 独立）读历史 trace(只读)+上轮失败 replay（首轮无历史→对 target 当前内容+contract 静态审查）；逐条过 `check_reflection`（M1 弱校验；M3 升 BenchTrace） | →4 |
| 4 PROPOSE | meta 汇总→scoped patch（HarnessFix 限范围+声明修哪条失败）；backend 失败/超时/空→warning+fallback builtin | →5；proposals 空→9(`static_reject++`) |
| 5 PATCH | worktree 内逐 patch 应用（临时 branch）；**AST 危险调用拒绝门**（os/subprocess/socket/ctypes/eval/exec/compile/`__import__`/动态导入/沙箱外 open/网络库；import 默认拒白名单 allow）；contract 静态检查；apply 冲突→该 patch REJECT(reason=conflict) 不影响其他 | →6；全 patch 被拒→9(`static_reject++`) |
| 6 EVALUATE | 按冻结 tier 分层评测（§5）：A 跑 grader(干净一次性环境)；B 锚核查+EVE 边际增益(visible 锚计分,holdout 旁路抽检)；C 内部一致性+历史成功 replay；含固定回归+历史失败 replay+novelty 门控新主题。算分向量+coverage+judge 分+自欺指数。只产数据 | →7 |
| 7 ACCEPT | **PACE per-tier acceptor**（§5.5）。no-regression 任一回退→硬 REJECT。**CONTINUE 仅 B/C 随机档**(A 档二态 ACCEPT/REJECT)，`continue_count`<上限→6，达上限→REJECT。强制人审触发（coverage<floor 欲 ACCEPT / visible 锚有效增益<ε / **visible 涨且 holdout 不涨=过拟合** / judge α 异常高且锚不涨 / 自欺报警 / 纯 C 档欲 ACCEPT）→9.5 | ACCEPT→8；REJECT→9(`no_progress++`)；CONTINUE→6(`no_progress++`)；强制人审→9.5 |
| 8 ARCHIVE | 进 archive（lineage append-only + Pareto；**硬维门**：进前沿者 A/frozen 锚维不低于前沿中位，纯软维优胜只冷藏不可选 parent）；Library Drift 活跃上限+outcome-driven 退役(冷藏不删)；写回 learnings.md；清零 `no_progress/forced_review` | →9 |
| 9 LOOP/STOP | 停止判定：达标/预算耗尽；`no_progress≥N`→熔断；`static_reject≥N_sr`→熔断；`forced_review≥N_fr`→熔断停机等人；`no_progress≥M`(M<N)→释放阀(仅升人审频率,§5.4)；**累计漂移熔断**：连续 ACCEPT 但 holdout/全量回归不涨≥N_drift→停机人审 | →2 或 终止 |
| 9.5 PAUSE_FOR_HUMAN | 由态7 强制人审 或 态9 auto 纯 C 触发；写 `pending_actions.jsonl`+Discord；**非阻塞**(标 pending、跳过、继续)；`forced_review++`；auto 纯 C 无人且 `forced_review≥N_fr`→熔断停机 | →2 |

**对外落地子流程（人审发起）**：`review --approve <aid>` 或 `land --vid <v>`→harness 把指定 archive 版本应用回真 target 并执行 GATED 动作。**只在此发生，永不在自动循环内**。

---

## 5. 评测与防自欺脊柱

**5.1 画像**（态1）：探针(exec/ci/fact/self-test)→`verifiability_score`→A/C 二分(M1)→A/B/C 三档(M2+)。exec 变异测试二次校验防假 grader；锚字段代码判定+异构抽取+铁律5 隔离；tier 冻结(铁律4)。

**5.2 A 档**（`verifiable.py`）：真实 test/build/CI 退出码=硬 reward；快照哈希锁定+变异测试有效性门（杀不死注入 bug 的测试作废）；评测子进程最小化环境（清 env 白名单、home/.credentials 不可读、禁缓存、grade() 只读快照）；MOSS trial-worker 重放+health-probe 回滚。

**5.3 B 档**（`anchors.py`）：抽可外部核验子断言→edgartools/EDGAR/价格核查（先清 `~/.edgar` 缓存/独立 cache 避 WinError 145）。
- **frozen 锚集拆 visible/holdout**：visible 进 e-process 计分；holdout 不进当轮、每 K 轮抽检；**visible 涨而 holdout 不涨→判过拟合、计入自欺指数+强制人审**。
- **锚集规模/独立性下限**：`anchor_set_min=24`；按 source_url/主题聚类去相关后计**有效独立锚数**，<下限→B 档不可单独 ACCEPT 降级 C；per-anchor 配对前同源锚降权防相关锚虚高 e-value。
- **锚文本隔离**（铁律5）：claim/verified 值对 proposer 不可见。
- EVE 边际增益（加该证据是否真提升正确率，非绝对准确率）；前瞻断言挂日历异步回查（机制就位+队列写入即过，不进短期验收）。
- 自建练习题（OpenSkill，**延后到 M2 后增量**）：与固定回归集分离计分、不进 PACE 主权重、新题须在已知失败旧版上确实失败+覆盖度熵监控防坍缩。

**5.4 C 档兜底**：无客观信号硬门=不退化（内部一致性+历史成功 replay）；acceptor conservative；纯 C 档(coverage=0)每轮 ACCEPT 必经人审，`--mode auto` 对纯 C 报错或强制 gated。**释放阀=只降人审触发频率，绝不在 auto 自动降阈采纳**；降阈仅 gated、设硬下限+次数上限、降阈期 C 主观分 e-value 额外加罚、降过阈采纳标 `needs human audit`。

**5.5 PACE acceptor**（`acceptor.py`+`reference/acceptor_math.md`）：anytime-valid e-process 配对检验替代"涨了就留"。
- **per-tier 配对单元**：A=per-task `grader_exit_code/task_passed` 配对（**A 档二态、禁 CONTINUE**）；B=per-anchor 边际增益配对，`n_anchor<n_min(8)` 或 有效独立锚<下限→禁 ACCEPT；C=per-regression-task 一致性配对（改前/改后双跑零均值化）。
- 主观分进 e-process 前按历史方差缩放 + 单轮 `evalue_max_step` 上限；同源锚去相关。
- 配对优先级 A>B>C，C 极低权重绝不单独触发；控误提交率 α=0.05。
- **站现成 testing-by-betting 库（confseq 等）拿 e-value/wealth 接口，自写 per-tier 配对包装**；噪声单测为验收闸门。

**5.6 异构 judge**（`judges.py`，池=Claude+Codex 两家）：**Codex（非 proposer 家族，走 codex skill 最强模型，禁其 browser/playwright、只用 web_search）= 主独立 judge；Claude = 去偏次 judge**。两判官配对一致性 α：α 过低→人审；α 异常高且 frozen 锚不涨→人审+计自欺。judge 只对挂可核验 span 的断言计分，无 span 篇幅零/负权重；位置/长度去偏；**judge↔锚相关性校准改用独立 holdout/人审标注集（不用进 e-process 的 visible 锚）**；judge 走独立联网进程（与 candidate 物理隔离，prompt 无真值，纳入出站审查）。**Codex 不可用（限速/故障）→ 只剩 Claude（proposer 家族）：禁止 Claude 单家自动 ACCEPT，降级为'程序化锚为唯一裁决信号 + 升人审'**。judge 异构性薄是已知取舍，故防自欺重心放程序化锚（§5.3/§5.7）。

**5.7 自欺指数**（`selfdeception.py`）：=`judge 增益 − frozen 锚真实增益`。**多闸防合谋**：① 新增锚不计当轮增益（只算 frozen visible 留存锚）；② visible 留存锚增益<ε 禁 ACCEPT；③ **visible 涨而 holdout 不涨→过拟合报警**；④ **累计漂移预算**：同 lineage 上 visible 累计涨幅 > holdout 累计涨幅×容差→判过拟合漂移、强制人审；态9 独立熔断计数器"连续 ACCEPT 但 holdout/全量回归不涨"。status 分报硬维/软维趋势，软涨硬平→报警。

---

## 6. 安全与自治

- **沙箱**：全程 worktree+隔离目录；评测子进程禁网，仅经白名单审查代理出网。
- **出站（M2 起完整，M1 仅禁网）**：① M1=禁网硬门(allowlist 空，任何出站拒+告警)；② M2+ 完整审查：**出站改 harness 代发**（参数白名单枚举+结果回填，candidate 不能自选发哪个 ticker、不能控时序）；代理审查完整 URL/header/body+熵阈值+体积上限+base64/hex 检测+结构化白名单参数(CIK/ticker/日期正则)+DNS 经代理；**跨请求序列异常检测**（同 run 出站参数序列异常打分）。**残余风险（明示）**：低带宽时序信道无法完全封闭，仅靠禁网+harness 代发缓解，不依赖审查。
- **凭证隔离**：评测子进程最小化环境（清非白名单 env，尤其 token/key）；`~`/`.credentials.json` 不可读；`notify.py`/discord 只由 harness 主进程调用，candidate 禁 import discord_relay。
- **沙箱边界**：gate 路径 realpath 解析后比对沙箱根（canonical 前缀），拒 symlink/`..` 穿越；落沙箱外的写/删一律 GATED 不受 `--mode` 影响（IMMUTABLE）。
- **action 分级（IMMUTABLE）**：canonical-在沙箱内=auto；outward(出沙箱写/删、push、合主分支、对外发送)=GATED；`--mode auto` 仅免审沙箱内。
- **archive/回滚**：lineage append-only；任意版本一键 rollback；每 K 轮全量回归防能力侵蚀；重写版须 acceptor 打赢原始版；Pareto 硬维门。
- **自举（D3/M4，默认关）**：IMMUTABLE 从内容哈希锁定 frozen 副本加载+启动校验+不从 candidate import；patch 命中 IMMUTABLE 硬拒；**自举禁 candidate 自定义 grade()**（用 frozen/外部 grader）；递归隔离独立 worktree；负向用例进验收。
- **熔断/kill-switch**：哨兵文件放 candidate 不可写区（主进程持有）；主进程轮询+子进程 wall-clock 硬超时由父进程 kill。

---

## 7. 数据/状态布局

```
run/<run_id>/  state.json(原子) ; events.jsonl(真相源,可重放) ; target.json(冻结 tier/score/visible+holdout 锚)
  reflections/<r>/*.json ; proposals/*.json ; traces/<task>/*.json(只读)
  evals/<r>.json(分向量 + visible 锚明细{claim,span,source_url,fetched_at,verified,marginal_gain} + holdout 抽检 + judge 原始分)
  acceptor/<r>.json(e-process wealth/threshold/decision/per-tier/continue_count)
  pending_actions.jsonl({aid,run_id,round,action_type,payload,created_at,status,ttl})
archive/  versions/<vid>/ ; lineage.json ; pareto.json ; retired.jsonl(冷藏)
```
> 注：frozen 锚 verified 值/holdout 锚物理隔离存储，proposer/反思进程无读权限（铁律5）。

---

## 8. 接口

**CLI**：`python -m sie.cli {init|run|status|review|land|replay|rollback|diff}`（同 v2，新增 `land`）。`status` 报态+Pareto+真提交率+假提交拦截数+自欺指数(硬维/软维+holdout 背离)+三计数器+待审队列。

**target_contract**（升级）：`grade(task)→{ task_passed:bool, grader_exit_code:int, dimensions:[{name,tier:A|B|C,score,weight}], anchors:[{claim,span,source_url,fetched_at,verified,marginal_gain}], verifiable_coverage:float }`。**tier=A 的 score∈{0,1} 由 grader_exit_code 映射**；A 档 PACE 配对消费 `task_passed`。judge 主观分由 `evaluate.py` 在 contract 外注入（非 candidate 提供）。`regression_set()` 区分固定回归 vs 历史失败 replay（replay 失败判定标准明确）。自举时 grade() 用 frozen/外部版（铁律5/§6）。

---

## 9. 测试策略（含对抗/负向）

- **acceptor 噪声回归（验收闸门）**：纯噪声拒绝率≈1、真增益采纳率高、误提交≤α；对抗序列：主观正漂移+锚每轮+0.5%微涨→拒；**小相关锚集**(8 同源锚每轮微涨→拒)；**长期微涨过拟合序列**(visible 持续+ε 但 holdout 平→拒/人审)。
- **profiler fixtures**：有效 test repo / 全 skip 假 test / 带锚字段调研产物 / 纯文风；对抗：改 docstring 塑造放水自建题→抓；塑造内容影响 PROFILE 探针→抓（resume 不重跑/在 frozen base 上做）。
- **安全负向**：patch 含 subprocess/socket→拒；答案塞 GET query→拦；跨请求 ticker 选择序列编码→序列异常检测/harness 代发阻断；candidate 读 `.credentials.json`→失败；candidate 调 notify.py / import discord→拒；symlink/`..` 穿越→GATED；自举 patch 改 gate_human/acceptor→拒、改 grade()→不采信。
- **活性/计数**：持续强制人审→`forced_review` 熔断（不空转）；态4空/态5全拒→`static_reject` 计数正确；CONTINUE 达上限→REJECT；A 档禁 CONTINUE。
- **边界**：纯 C 档每轮人审；worktree 冲突→该 patch REJECT；backend 不可用→fallback；judge 不可用→人审；冷启动首轮。
- **端到端**：M1a A 档真 pytest repo 全闭环(no-regression 兜底)+崩溃重放；M1b 同 repo 换 PACE+安全门全开；M2 B 档 small-cap-deepdive+coverage/holdout；M3 C 档不退化+自欺合谋报警；M4 自举负向用例。

---

## 10. 借鉴溯源

PACE(2606.08106)·DGM(2505.22954)·GEPA(2507.19457)·OpenEvolve·MARS(2509.20502)·BenchTrace(2605.29225)·HarnessFix(2606.06324)·Library Drift(2605.19576)·Useful Memories(2605.12978)·CPE(2605.09315)·MOSS(2605.22794)·OpenSkill(2606.06741)+EVE(2605.22905)·Meta-Agent Challenge(2606.04455)·SICA·Panickssery(2404.13076)·obra/superpowers。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 状态非原子崩溃 | events.jsonl 真相源+tmp+rename+重放 |
| acceptor 橡皮图章 | 噪声+对抗+小相关锚集+长期微涨单测锁参 |
| **frozen 锚过拟合** | holdout 锚集旁路抽检+visible/holdout 背离报警+锚文本隔离(铁律5)+锚集规模/独立性下限 |
| **缓慢漂移累积过阈** | 累计漂移预算(holdout 背书)+独立熔断计数器 |
| 锚 judge 合谋 | 自欺多闸+judge 校准用独立 holdout 集 |
| 出站隐蔽信道(GET/时序/分包) | M2 harness 代发+序列异常检测；时序信道列残余风险 |
| patch 危险调用 | AST 拒绝门(IMMUTABLE) |
| 自举改裁决/自定义 grade() | IMMUTABLE frozen 哈希加载+禁 candidate grade()+负向用例 |
| 凭证泄漏 | 最小化环境+home 不可读+禁 import discord |
| 路径穿越/symlink | realpath canonical 边界(IMMUTABLE) |
| **CONTINUE 死循环/活性漏洞** | CONTINUE 限随机档+上限+落点；forced_review 熔断 |
| **计数口径矛盾** | 三计数器分离(no_progress/static_reject/forced_review)各自熔断阈 |
| tier 被画淡 | tier 冻结(铁律4)+上调仅新 run |
| Pareto 刷软维 | 硬维门+软涨硬平计自欺 |
| 24h 无人 gate 卡死 | 人审非阻塞+forced_review 熔断 |
| git/worktree 层失败 | INIT_FAILED 可 resume；patch 冲突=REJECT；run_id 锁 |

---

## 12. 校准参数（给初值，跑一轮后校准）

`α=0.05` · `n_min=8` · `anchor_set_min=24` · `effective_independent_anchor_min=12` · `holdout_fraction=0.3` · `continue_count_cap=5` · `no_progress_circuit N=8` · `no_progress_release M=3` · `static_reject_circuit N_sr=6` · `forced_review_circuit N_fr=5` · `drift_circuit N_drift=4` · `cumulative_drift_tolerance=1.5×` · `frozen_anchor_effective_gain_ε=0.02` · `selfdeception_alert_band=0.15` · `evalue_max_step` · `N_reflectors 1(M1)→3(M3)` · `reflection_correctness_threshold=0.5` · `judge_pool=Claude+Codex(2 家)` · `judge_agreement α_low=0.4/α_high=0.85` · `active_cap=64` · `K=5`(全量回归/holdout 抽检周期) · `per_round_walltime_cap`。

---

## 13. 里程碑与验收（全光谱，~50-70h）

> **M1 第 0 步硬前置**：confseq(或等价库)能给 e-process wealth 接口 + 写最小 spike(纯噪声序列看拒绝率)；失败则停下重选 acceptor 方案，不进编码。

- **M1a 端到端骨架（~14-18h）**：INIT(worktree+run_id 锁+resume)/PROFILE(A/C 二分+变异测试)/SELECT/REFLECT(串行)/PROPOSE(builtin)/PATCH(基础 apply+import 白名单)/EVALUATE(verifiable+最小化环境)/**acceptor=no-regression 硬门(兜底)**/ARCHIVE(lineage+rollback)/events 重放/禁网+realpath 边界+凭证隔离/人审队列(基础)。**验收**：真 pytest repo 全闭环能跑能采纳能回滚、崩溃重放一致。
- **M1b 防自欺/安全门加硬（~10-14h）**：AST 危险门全清单+变异测试有效性门+**PACE A 档 e-process+噪声/对抗单测(纯噪声拒绝率≈1)**+人审非阻塞队列+三计数器+熔断。**验收**：acceptor 正确采纳/拒绝、安全负向用例全过、活性/计数用例过。
- **M2 B 档（~14-18h）**：anchors(EDGAR+visible/holdout 拆分+frozen 趋势+EVE 边际增益)+锚集规模/独立性下限+coverage 门+PACE B 档配对+完整出站审查(harness 代发+序列检测)+fact 探针。**自建练习题不在 M2 硬验收**。**验收**：small-cap-deepdive 跑通 B 档、coverage/holdout 背离门生效、小相关锚集+长期微涨对抗序列被拒。
- **M3 C 档+异构 judge+自欺（~12-16h）**：judge 池=Claude+Codex（Codex skill 适配器，最强模型，禁 browser/playwright、只用 web_search）+双向 α 门(两判官配对)+C 不退化门+释放阀(仅升人审)+自欺多闸+累计漂移熔断+Pareto 多维硬维门+Library Drift 退役+MARS 并行反思。**验收**：C 不退化门生效、自欺指数对"锚 judge 合谋"报警（以 holdout 背离为主信号、Codex↔Claude 配对 α 为辅）、纯 C 档强制人审、Codex 不可用时不降级单 Claude 自动提交。无 R3 前置。
- **M4 自举隔离（~6-10h，默认关）**：IMMUTABLE frozen 哈希加载+supervisor+禁 candidate grade()。**验收**：自举负向用例（改裁决码被拒、改 grade() 不采信）过。

---

## 14. 前置交接项

- **confseq spike**（M1 第 0 步硬前置，见 §13）。
- **Codex judge 适配**：judges.py 走 codex skill（最强模型，禁 browser/playwright、只用 web_search）；无登录/付费前置。**不安装 gemini/minimax**。
- **edgartools 缓存锁**：M2 前清 `~/.edgar` 或设独立 cache 避 WinError 145。
- **旧目录清理**：`CodesSelf/self-improving-research-agent`（句柄锁）会话结束后删除。
