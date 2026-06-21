# self-evolve 设计规格（Design Spec v2）

- **日期**：2026-06-21（v2：纳入 4 路对抗式 subagent 校验的全部修订）
- **状态**：架构获批 + 范围确定（全光谱，预算 ~50-70h ≈ 3 天自动构建，内部分 M1-M4 里程碑）；本版已闭合校验发现的 2 blocking + 2 needs-fix → 待用户复核 → writing-plans
- **依据**：本仓 `docs/自改进Agent调研.md`、`docs/02-crossval-deepdive.md`

---

## 1. 目标与非目标

**目标**：用于 agent 自我迭代开发**工程工具**（skill/仓库/项目）的 Claude Code skill `self-evolve`。把"读历史→反思→改→评测→采纳→归档"做成**确定性、可复现、不自欺**的闭环：指向任意目标，它在沙箱里自动多轮改进该目标，用不可 game 的提交门保证"被采纳的改动是真改进"。现实工程效果为唯一标准（无发表包袱），公开发布 + 自用。

**非目标**：不追发表新意；不做权重训练；不替代人对"把改动落地到真仓库"的最终判断（落地永远人审）。

---

## 2. 锁定决策

| # | 决策 |
|---|---|
| D1 | 范围=工程工具进化（skill/仓库/项目），分层 A/B/C 信号。**全光谱一次到位**，预算 ~50-70h，内部 M1-M4 里程碑（§13）。 |
| D2 | 形态=方法论 skill（SKILL.md 门控）+ 确定性 Python harness（**代码裁决**）+ subagent 编排；搜索环节可选接 GEPA/OpenEvolve，默认内置。 |
| D3 | 迭代对象=主改外部目标；自举 `--self` 默认关、递归隔离（M4）。 |
| D4 | 安全=worktree 沙箱内全自动；**对外落地（push/合主分支/删文件/对外发送）= 人审发起的独立子流程，不在自动循环内**（见 §4/§6）。 |
| R1 | 部署=`self-evolve` 仓内 skill，junction 到 `~/.claude/skills/self-evolve`，加进 SyncClaudeSkills。仓库已重命名为 `self-evolve`。 |
| R2 | 人审=待审队列 + Discord 推送 + CLI/slash 回执，**非阻塞**（见 §6）。 |
| **R3（新）** | **前置交接项**：异构 judge 需 ≥2 非 proposer 家族；本机仅 `codex`(gpt-5.5)，`gemini`/`minimax` CLI 未装。我负责配置，登录/付费由用户完成（M3 前置）。在依赖就绪前，异构 judge 降级为"codex 单异构 + 程序化锚为主信号"，judge 一致性门挂起。 |

---

## 3. 设计铁律（防自欺地基，全局适用）

1. **LLM 只提议，代码裁决**：反思/候选生成/主观评审由 LLM；采纳/拒绝/回滚/分档由 harness 确定性代码。搜索引擎只进候选生成步，**绝不评判自己的产出**。
2. **原始证据一等公民**：trace/反思 append-only 只读，永不被 LLM 改写（Useful Memories 实证：持续改写会跌破不改基线）。
3. **IMMUTABLE 裁决代码集**：`statemachine / acceptor / judges / verifiable / anchors / selfdeception / gate_human / profiler 的探针判定 / supervisor loader / 沙箱边界判定`——这些从 **frozen base ref 按内容哈希加载**，不在任何 candidate 可写 glob 内；patch 命中即硬拒（自举时尤其，见 §6/M4）。
4. **tier 一旦定档冻结**：`verifiability_score`/tier 在 PROFILE 态定，后续轮不可下调（只能发现新硬信号时上调 A，且需人审）；防"把目标画淡落 C 档绕开硬信号"。

---

## 4. 门控主循环（确定性状态机，10 态，含显式转移）

> 主循环**全程在 worktree 沙箱内**，只产出"归档的候选版本"，**不对真目标落地**。落地=人审发起的独立子流程（见末尾）。

| 态 | 动作（谁做） | 产出 | → 下一态（条件） |
|---|---|---|---|
| 0 INIT | 读 target+contract；建 worktree 沙箱（失败→写 `INIT_FAILED` 干净退出，可 resume）；run_id 唯一锁（worktree 路径含 run_id 防并发抢占）（代码） | `state.json` | →1 |
| 1 PROFILE | 跑 `profile.py`+探针→`verifiability_score`→**冻结 tier(A/B/C，可叠加)**；exec 探针二次校验（变异测试：注入已知 bug 测试须变红，杀不死则该信号作废）；fact 探针锚字段由代码判定（非 LLM 自报）（代码；锚抽取用异构≠proposer）| `target.json` | →2 |
| 2 SELECT_PARENT | DGM 加权采样选 parent（**冷启动**：archive 空→parent=base ref）（代码）| — | →3 |
| 3 REFLECT | N 个反思（M1 串行单次；M3 升 N=3 并行 MARS 独立互不可见）读历史 trace(只读)+上轮失败 replay（**首轮无历史**→退化为对 target 当前内容+contract 的静态审查）；逐条过 `check_reflection`（M1 弱校验=结构+是否指向真实失败 task；M3 升 BenchTrace 正确性）（LLM 提议→代码校验）| `reflections/<r>/*.json` | →4 |
| 4 PROPOSE | meta 汇总→scoped patch 规约（HarnessFix 限文件/段+声明修哪条失败）；可选 backend（GEPA/OpenEvolve）**失败/超时/空返回→warning+fallback builtin**；**proposals 为空→按无进展计**（LLM）| `proposals/*.json` | →5；空→9(no_progress++) |
| 5 PATCH | worktree 内逐 patch 应用（临时 branch，可逐个回退）；**AST 危险调用拒绝门**（os.system/subprocess/popen/socket/ctypes/eval/exec/compile/`__import__`/动态导入/open 沙箱外路径/网络库直连→拒该 patch；import 默认拒白名单 allow）；contract 静态检查（语法/import/SKILL schema）；**apply 冲突→该 patch REJECT(reason=conflict)，不影响其他**（代码）| patched worktree | →6；全 patch 被拒→9(no_progress++) |
| 6 EVALUATE | 按冻结 tier 分层评测：A 跑 grader（干净一次性环境+清 env 白名单+禁缓存复用）；B 抽锚核查+EVE 边际增益；C 内部一致性+历史成功 replay；含固定回归集+历史失败 replay+novelty 门控新主题。算 per-dim 分向量 + anchor_coverage + judge 分 + **自欺指数**。只产数据不裁决（代码；judge 是异构 LLM 子调用）| `evals/<r>.json` | →7 |
| 7 ACCEPT | **PACE per-tier acceptor**（§5.5）：三态。no-regression 任一回退→硬 REJECT。**强制人审触发**（任一）：anchor_coverage<floor 且欲 ACCEPT / frozen 锚集有效增益<ε / judge α 异常高且锚不涨 / 自欺指数报警 / 纯 C 档欲 ACCEPT（代码）| `acceptor/<r>.json` | ACCEPT→8；REJECT→9；CONTINUE→6(累积证据,有上限);强制人审→9.5 |
| 8 ARCHIVE | 进 archive（lineage append-only + Pareto 多目标；**硬维门**：进前沿者 A/frozen 锚维不得低于前沿中位，纯软维优胜只冷藏不可选 parent）；Library Drift 活跃上限+outcome-driven 退役(冷藏不删)；写回 learnings.md（代码）| `archive/` | →9 |
| 9 LOOP/STOP | 停止判定（达标/预算/自欺报警/熔断）；**计数口径**：no_progress 只数 ACCEPTOR 的 REJECT/CONTINUE 轮（态5 静态拒单独计）；连续 M 轮无进展→释放阀（仅升人审频率，见 §5.4），连续 N>M 轮→熔断停机（代码）| events | →2 或 终止 |
| 9.5 PAUSE_FOR_HUMAN | 仅由态7 强制人审触发进入：写 `pending_actions.jsonl`(schema 见 §7)+Discord 推送；**非阻塞**——标该决策 pending、跳过、继续下一轮其余沙箱内迭代；不卡死整 run（代码）| pending 条目 | →2（auto 模式纯 C 档强制人审且无人→熔断停机等人）|

**对外落地子流程（人审发起，独立于主循环）**：人用 `review --approve <aid>` 或 `land --vid <v>` → harness 把指定 archive 版本应用回真 target 并执行 GATED 动作（commit/push/合主分支/删文件）。这些动作**只在此子流程发生，永不在自动循环内**，从根上消除"自动循环产生外向动作"的矛盾。

---

## 5. 评测与防自欺脊柱（全光谱，已闭合校验漏洞）

**5.1 信号发现/画像**（`profile.py`+`probes/`，态1）：探针(exec/ci/fact/self-test 合成)→`verifiability_score`→A/C 二分(M1)→A/B/C 三档可叠加(M2+)。⚠️ exec 探针**变异测试二次校验**（注入 bug 测试须变红）防假 grader；锚字段代码判定+异构抽取，**抽锚进程≠改 patch 进程**（改 patch 者拿不到完整锚清单，防选择性满足）；tier 冻结(§3.4)。

**5.2 A 档**（`verifiable.py`）：真实 test/build/CI/grader 退出码=硬 reward；测试集快照哈希锁定+**变异测试有效性门**（杀不死注入 bug 的测试作废）；评测子进程**最小化环境**（清 env 白名单、home/.credentials 不可读、禁缓存、grade() 只读快照）；MOSS trial-worker 重放+health-probe 回滚。

**5.3 B 档**（`anchors.py`）：抽可外部核验子断言→edgartools/EDGAR/价格核查（先清 `~/.edgar` 缓存锁/设独立 cache 避 WinError 145）；**frozen 锚集**算趋势（新锚只入库不计当轮增益分母，防堆水货）；EVE 边际增益（加该证据是否真提升正确率）；前瞻断言挂日历异步回查（**机制就位+队列写入即算通过**，不进短期验收）；OpenSkill 自建练习题把部分 B 升 A——**自建题与固定回归集分离计分**，只作探索、不进 PACE 主权重，且新题须在"已知会失败的旧版本"上确实失败(难度探针)+覆盖度熵监控防坍缩。

**5.4 C 档兜底**（`evaluate.py`）：无客观信号时硬门=**不退化**（内部一致性+改后回跑历史成功轨迹）；acceptor conservative。**纯 C 档(coverage=0)：每轮 ACCEPT 必经人审**；`--mode auto` 对纯 C 档报错或强制 gated。**释放阀语义=只降人审触发频率，绝不在 auto 模式自动降阈采纳**（消除"自我拆除"）；降阈仅 gated 模式、设硬下限+次数上限、降阈期 C 主观分 e-value 额外加罚、降过阈的采纳标 `needs human audit`。

**5.5 PACE acceptor**（`acceptor.py`+`reference/acceptor_math.md`）：anytime-valid e-process 配对检验替代"涨了就留"。**每档配对单元与最小样本门写死**：A=per-task grader 退出码配对；B=per-anchor 边际增益配对，`n_anchor<n_min(默认8)`→禁 ACCEPT 只 CONTINUE；C=per-regression-task 一致性配对，须改前/改后双跑零均值化。**主观分进 e-process 前按历史方差缩放**（方差越大增量越小）+**单轮最大 e-value 增量上限**（防一次大波动过阈）。配对统计量优先级 A>B>C，C 极低权重、绝不单独触发。控误提交率 α=0.05。**优先站在现成 testing-by-betting 库（confseq 等）上做配对包装，非从零推公式**；噪声单测是验收闸门（含"纯噪声+主观正漂移+锚每轮+0.5%微涨"对抗序列，断言拒绝率≈1）。

**5.6 异构 judge**（`judges.py`+`review-fanout.js`）：强制≠proposer 家族（codex/gemini/minimax，R3 前置）；**双向 α 门**：α 过低→升人审；**α 异常高 且 frozen 锚增益≈0→也升人审+计入自欺指数**（高一致+无真增益=共同偏置）。judge 只对"挂可核验 span 的断言"计分，未挂 span 的篇幅/结构给零/负权重；位置/长度去偏；定期人在环抽样校准 judge↔锚相关性，掉阈则该 judge 降权。**judge 走独立联网进程**（与 candidate 物理隔离，prompt 不得携带测试真值，纳入出站审查）；可用 judge 家族<下限→该轮不自动 ACCEPT、升人审或 CONTINUE，**绝不降级单 judge 自动提交**。

**5.7 自欺指数**（`selfdeception.py`）：=`judge 报告增益 − frozen 锚真实增益`。**双闸防合谋**：① judge 增益>阈但锚增益主要来自新增锚(非 frozen 锚集准确率提升)→报警；② frozen 锚集留存锚上增益<ε→禁 ACCEPT。报警→态7 强制人审；持续放大→熔断。status 分别报"硬维趋势/软维趋势"，软涨硬平→计入报警。

---

## 6. 安全与自治（已闭合 blocking 逃逸）

- **沙箱**：全程 git worktree+隔离目录；评测子进程禁网，仅经**白名单审查代理**出网。
- **出站内容级审查（闭合隐蔽信道）**：代理审查每个出站 GET 的完整 URL(含 query)/header/body；query/path 可变部分做**熵阈值+体积上限+base64/hex 编码检测**，超阈阻断入人审；豁免端点只允许结构化白名单参数(CIK/ticker/日期正则)，拒自由文本 query；DNS 经代理统一解析，禁 candidate 直接发 DNS。**"只读 API 豁免"= 仅豁免结构化白名单读，不豁免任意 GET**。
- **凭证隔离**：评测子进程最小化环境（清除非白名单 env，尤其 token/key）；`~`/`.credentials.json` 对沙箱进程不可读；`notify.py`/discord send 只能由 harness 主进程调用，**candidate 进程禁 import discord_relay**。
- **沙箱边界判定**：gate 路径用 **realpath 解析后比对沙箱根**（canonical 前缀匹配），拒符号链接逃逸与 `..` 穿越；任何解析后落在 worktree 外的写/删一律 GATED，不受 `--mode` 影响。边界判定函数属 IMMUTABLE。
- **action 分级表（IMMUTABLE）**：sandbox-internal(canonical 在沙箱内)=auto；outward(解析后出沙箱的写/删、push、合主分支、对外发送)=GATED。`--mode auto` 仅免审 canonical-在沙箱内动作。
- **archive/回滚**：DGM lineage append-only；任意版本一键 rollback(MOSS health-probe)；每 K 轮全量回归防能力侵蚀(CPE)；重写版须在 acceptor 上打赢原始版才生效；Pareto 硬维门(§4 态8)。
- **自举隔离（D3/M4）**：`--self` 默认关；**IMMUTABLE 代码集从内容哈希锁定的 frozen 副本加载，启动校验哈希，不从 candidate worktree import**；patch 命中 IMMUTABLE 路径硬拒；**自举时 grade() 不可由 candidate 提供**（用 frozen grade() 或外部 A 档 grader，禁 candidate 定义自身奖励）；递归隔离独立 worktree；负向用例（patch 改 gate_human/acceptor 被拒、candidate 改 grade() 不被采信）进验收。
- **熔断/kill-switch**：哨兵文件放 candidate 不可写区（主进程持有）；主进程轮询 + **子进程 wall-clock 硬超时由父进程 kill**（不依赖子进程自检）；连续无 accept 熔断(§4 态9)。

---

## 7. 数据/状态布局

```
run/<run_id>/
  state.json            # 原子 tmp+rename
  events.jsonl          # append-only 真相源,可重放
  target.json           # tier/verifiability_score/探针证据(冻结)
  reflections/<r>/*.json
  proposals/*.json
  traces/<task>/*.json  # 只读
  evals/<r>.json        # 分向量+anchor 明细(claim/span/source_url/fetched_at/verified/marginal_gain)+judge 原始分
  acceptor/<r>.json     # e-process wealth/threshold/decision/per-tier
  pending_actions.jsonl # 条目 schema: {aid, run_id, round, action_type, payload, created_at, status, ttl}
archive/
  versions/<vid>/ ; lineage.json ; pareto.json ; retired.jsonl(冷藏)
```

---

## 8. 接口

**CLI**：`python -m sie.cli {init|run|status|review|land|replay|rollback|diff}`
- `run --run-id <id> [--rounds N] [--budget H] [--backend builtin|gepa|openevolve] [--mode auto|gated] [--self]`
- `status`（态+Pareto+真提交率+假提交拦截数+自欺指数(硬维/软维趋势)+待审队列）
- `review --approve/--reject <aid>`；`land --vid <v>`（人审发起的对外落地子流程）
- `replay --round R`；`rollback --to <vid>`；`diff --a --b`

**slash**：`/self-evolve <target> [...]`、`/self-evolve-status`、`/self-evolve-resume <run-id>`

**target_contract**（`reference/target_contract.md`，升级 schema）：`probe()`；`tasks()`；`grade(task)→{dimensions:[{name,tier:A|B|C,score,weight}], anchors:[{claim,span,source_url,fetched_at,verified,marginal_gain}], verifiable_coverage:float}`；`regression_set()`（区分固定回归 vs 历史失败 replay，replay 失败判定标准）。judge 主观分由 `evaluate.py` 在 contract 外注入（非 candidate 提供）。

---

## 9. 测试策略（`tests/`，含对抗/负向用例）

- **acceptor 噪声回归（最高优先，验收闸门）**：纯噪声拒绝率≈1、真增益采纳率高、误提交率≤α；**新增 B/C 对抗序列**（真增益=0 但主观正漂移+锚每轮+0.5%微涨→仍拒）。
- **profiler fixtures**：有效 test repo / 全 skip 假 test / 带锚字段调研产物 / 纯文风文本；**对抗**：candidate 改 docstring 塑造放水自建题→被抓。
- **安全负向（blocking 修复必测）**：patch 含 subprocess/socket→拒；把答案塞进 GET query→代理拦；candidate 读 `.credentials.json`→失败；candidate 调 notify.py→拒；symlink/`..` 路径穿越→GATED；自举 patch 改 gate_human/acceptor→拒、改 grade()→不采信。
- **anchors**：mock edgartools，验事实准确率/边际增益/frozen 锚趋势/覆盖率门。
- **边界**：纯 C 档每轮人审；全拒计数口径；worktree 冲突→该 patch REJECT；backend 不可用→fallback builtin；judge 不可用→升人审；冷启动首轮。
- **端到端**：M1 收尾跑通 A 档真 pytest repo 全闭环+崩溃重放；M2 跑通 B 档(以 small-cap-deepdive 为样例,复用 edgartools)；M3 跑通 C 档不退化门+异构 judge+自欺指数；M4 自举隔离负向用例。

---

## 10. 借鉴溯源

PACE(2606.08106)=acceptor · DGM(2505.22954)=lineage+采样 · GEPA(2507.19457)=Pareto+反思变异 backend · OpenEvolve=island backend · MARS(2509.20502)=独立反思+异构 judge · BenchTrace(2605.29225)=反思校验 · HarnessFix(2606.06324)=scoped patch · Library Drift(2605.19576)=活跃上限+退役 · Useful Memories(2605.12978)=原始证据只读 · CPE(2605.09315)=全量回归 · MOSS(2605.22794)=trial-worker+回滚 · OpenSkill(2606.06741)+EVE(2605.22905)=锚+边际增益 · Meta-Agent Challenge(2606.04455)=exfiltration 防线 · SICA=自举 overseer · Panickssery(2404.13076)=异构防自偏好 · obra/superpowers=门控+learnings.md/stop-hook。

---

## 11. 风险与缓解（新增 git/worktree 层 + 出站信道 + 自举裁决）

| 风险 | 缓解 |
|---|---|
| 状态非原子崩溃 | events.jsonl 真相源+tmp+rename+重放 |
| acceptor 橡皮图章 | 噪声+对抗序列单测锁参数(§9 首项) |
| 锚覆盖率低/堆水货锚 | frozen 锚集趋势+覆盖率门+EVE 边际增益+换血 |
| 出站隐蔽信道(GET query/DNS) | 代理内容级审查+熵检测+结构化白名单参数 |
| patch 危险调用 | AST 拒绝门(IMMUTABLE) |
| 自举改裁决代码/自定义 grade() | IMMUTABLE frozen 加载+哈希校验+禁 candidate grade()+负向用例 |
| 凭证泄漏 | 最小化环境+home 不可读+candidate 禁 import discord |
| 路径穿越/symlink 逃逸 | realpath canonical 边界判定(IMMUTABLE) |
| judge 共谋高 α | 双向 α 门(高 α+锚不涨也报警) |
| tier 被画淡绕硬信号 | tier 冻结(§3.4)+下调需人审 |
| Pareto 刷软维假曲线 | 硬维门+软涨硬平计入自欺报警 |
| 释放阀自我拆除 | 只升人审频率、auto 禁自动降阈 |
| git/worktree 层失败 | INIT_FAILED 干净退出可 resume；patch 冲突=该 patch REJECT；run_id 锁 |
| 无人值守误差累积 | 自欺刹车+每轮回归+熔断+人在环抽样校准 |
| 24h 无人时 gate 卡死 | 人审非阻塞(标 pending 跳过继续) |

---

## 12. 校准参数（给初值，跑一轮后校准）

`α=0.05` · `n_min=8`(B 档锚配对) · `N_reflectors=1(M1)→3(M3)` · `reflection_correctness_threshold=0.5(M1 弱校验)` · `anchor_coverage_floor=0.30` · `frozen_anchor_effective_gain_ε=0.02` · `selfdeception_alert_band=0.15` · `judge_families≥2(R3 就绪后)` · `judge_agreement: α_low=0.4 / α_high=0.85` · `active_cap=64`(skill 库) · `K=5`(全量回归周期) · `no_progress_release(M)=3` · `no_progress_circuit(N)=8` · `evalue_max_step`(单轮上限) · `per_round_walltime_cap`。

---

## 13. 里程碑与验收（全光谱，~50-70h；M1-M4 顺序建）

- **M1 A 档可信内核端到端（~18-22h）**：INIT/PROFILE(A/C 二分+变异测试)/SELECT_PARENT/REFLECT(串行)/PROPOSE(builtin)/PATCH(+AST 危险门)/EVALUATE(verifiable)/ACCEPT(PACE A 档+**噪声单测过**)/ARCHIVE(lineage+rollback)/events 重放/沙箱+凭证隔离+realpath 边界+出站审查/人审非阻塞。**验收**：真 pytest repo 全闭环、acceptor 正确采纳/拒绝、纯噪声拒绝率≈1、崩溃重放一致、全部安全负向用例通过。
- **M2 B 档（~14-18h）**：anchors(edgartools+frozen 锚集+EVE 边际增益)+覆盖率门+PACE B 档配对(n_min)+自建练习题(防 game)+fact 探针。**验收**：以 small-cap-deepdive 为目标跑通 B 档、覆盖率门生效、B/C 对抗噪声序列被拒。
- **M3 C 档+异构 judge+自欺指数（~12-16h，前置 R3）**：异构 judge 适配器(codex+gemini+minimax)+双向 α 门+C 档不退化门+释放阀(仅升人审)+自欺指数双闸+Pareto 多维+硬维门+Library Drift 退役+熔断+MARS 并行反思。**验收**：C 档不退化门生效、自欺指数对"锚 judge 合谋"报警、纯 C 档强制人审。
- **M4 自举隔离（~6-10h，默认关）**：IMMUTABLE frozen 加载+哈希校验+frozen supervisor+candidate 不裁决自己。**验收**：自举负向用例（改裁决代码被拒、改 grade() 不采信）通过。

---

## 14. 前置交接项（writing-plans / 开工前）

- **R3 异构 judge**：我配置 `gemini`/`minimax` CLI 接入，**登录/付费由用户完成**（M3 前置；未就绪则 M3 judge 降级 codex 单异构 + 程序化锚为主，异构≥2 延后）。
- **PACE 库确认**：开工前 30min 确认 confseq 等 testing-by-betting 库可用，站库做配对包装而非从零。
- **edgartools 缓存锁**：M2 前清 `~/.edgar` 或设独立 cache dir 避 WinError 145。
- **旧目录清理**：`CodesSelf/self-improving-research-agent`（句柄锁）会话结束后删除。
