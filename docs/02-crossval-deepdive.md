# 交叉验证与深读补充（market-intel 学术工具链）

> 日期：2026-06-21｜本篇是对 [`01 全景调研`](自改进Agent调研.md) 的**硬信号交叉验证 + 2026 新论文增补**。
> 第一篇用的是自带 research 工具（HF + web）；本篇按 market-intel 的 `frontier-research` playbook，实际调用了 **arXiv API、Semantic Scholar Graph API、OpenReview API2、HuggingFace**（GitHub API 在仓库验证轮已用）。
> 原始数据存于 [`data/semantic-scholar-citations.json`](data/semantic-scholar-citations.json)、[`data/arxiv-recent-sweep.xml`](data/arxiv-recent-sweep.xml)。
> 按 catalog 标注跳过：**Papers-with-Code（D-404，Meta 已 sunset）**；按 playbook 把 Trends/GDELT/社媒列为 L4（消费级注意力，对纯学术课题信号弱），优先 L1 学术源。

---

## 0. 一句话更新

交叉验证**确认了第一篇的护栏判断完全正确**，并给出可直接借鉴的 2026 开源实现；但**研究空白需要下修**,我原先点的「空白2（自指改进可信认证）」已被 **PACE（2026-06）** 基本占据，「空白1/空白3」被 OpenSkill / EVE-Agent / SkillSmith 逼近但**因它们仍依赖可验证任务，真正的「无 ground-truth 开放调研域」组合仍空着**。

---

## 1. Semantic Scholar 引用量交叉验证（显著性硬信号）

> 用途：判断「领域是否真在 build on it」，而非「论文是否存在」。`infl` = influentialCitationCount（过滤敷衍引用）。

| 引用 | infl | 论文 | 年 | 解读 |
|---:|---:|---|---|---|
| **3924** | 322 | Reflexion | 2023 | ★ 方法原语，领域地基 |
| **3739** | 266 | Self-Refine | 2023 | ★ 自评+自改范式定义者 |
| **1830** | 138 | Voyager | 2023 | 开放式技能库奠基 |
| **1792** | 229 | Multi-Agent Debate (Du et al.) | 2023 | ★ 多 agent 讨论奠基 |
| **1421** | 120 | APE | 2022 | prompt 自动化奠基 |
| **957** | 80 | **LLMs Cannot Self-Correct Reasoning Yet** | 2023 | ⚠️ 自纠批判被重度引用,**self-judge 风险是领域共识** |
| 908 | 96 | OPRO | 2023 | LLM-as-optimizer |
| 622 | 45 | Self-Rewarding LM | 2024 | 权重支线代表 |
| **559** | 78 | AlphaEvolve | 2025 | 增速极快 |
| **521** | 32 | Panickssery「judge 偏好自己输出」 | 2024 | ⚠️ 自偏好被重度验证 |
| 490 | 30 | Promptbreeder | 2023 | 自指 prompt 进化 |
| 261 | 41 | AFlow | 2024 | 工作流自动生成 |
| 223 | 19 | DSPy/MIPROv2 | 2024 | |
| 216 | 33 | ADAS | 2024 | meta-agent 设计 |
| **212** | 33 | GEPA | 2025 | 增速快，押注对象 |
| 203 |, | EvoPrompt | 2023 | |
| 166 | 33 | TextGrad | 2024 | |
| 128 | 11 | 综述：Comprehensive Self-Evolving Agents | 2025 | |
| **122** | 6 | **Darwin Gödel Machine** | 2025 | 标杆但引用尚低（太新）|
| 98 | 2 | STOP | 2023 | |
| 75 | 4 | 综述：Self-Evolving Agents (What/When/How) | 2025 | |
| 71 | 2 | 综述：Self-Evolution of LLMs | 2024 | |
| 65 | 6 | OMNI | 2023 | |
| 58 | 5 | OMNI-EPIC | 2024 | |
| 27 | 0 | SICA | 2025 | 干净实现但引用尚低 |
| 20 | 0 | Spontaneous Reward Hacking in Self-Refine | 2024 | ⚠️ |
| 19 | 3 | Gödel Agent | 2024 | |
| 9 | 0 | MARS | 2025 | |
| 5 | 1 | ACD | 2025 | |

**关键反转（重要修正第一篇的「标杆」叙事）**：
- 被海量引用的是**方法原语**（Reflexion/Self-Refine/MAD/APE/Voyager/OPRO，几百到近 4000 引用）；
- 被当作「自改代码标杆」的 **DGM(122)/ADAS(216)/SICA(27)/STOP(98)/Gödel Agent(19)/ACD(5)** 引用都还**很低**。
- 结论：**DGM 这条线是「概念/注意力标杆」，引用质量尚未沉淀**（2025 太新）。做研究时，方法可借鉴 DGM/SICA，但若要论「领域共识」，地基仍是 Reflexion/Self-Refine。
- ⚠️ **最该注意**：批判性论文「Cannot Self-Correct」(957) 与「Panickssery 自偏好」(521) 引用量**远高于**任何一个自改进系统,**说明 self-judge 风险不是我危言耸听，而是被领域重度引用的共识**。

---

## 2. OpenReview 预发表信号（ICLR 2026）

确认 **ICLR 2026 设有 "AI with Recursive Self-Improvement (RSI)" Workshop**（专门建制化），已检索到录用：
- `Adaptive Meta-Curriculum for Test-Time Self-Improvement`, RSI **Spotlight**
- `SAHOO: Safeguarded Alignment for High-Order Optimization`, RSI Poster（= 第一篇找到的对齐漂移监控）
- `TangramSR: A Benchmark for Recursive Self-Improvement`, RSI Poster
- `Stabilizing Iterative Self-Training with Verified Reasoning`, LLM Reasoning Workshop

**信号**：该方向已正式建制化，且录用工作**普遍在攻「安全 / 稳定 / 验证」**,与本项目护栏方向完全一致。

---

## 3. 2026-05/06 新论文深读（晚于知识截止，arXiv 扫出 + 逐篇深读）

> 这批是第一篇没有的,直接砸在本项目的护栏/缺口上。按「占据哪个护栏/缺口」归类。

### 3.1 外部可验证锚点（护栏① / 直指空白1）★最重要
- **OpenSkill: Open-World Self-Evolution**（2606.06741，**开源 github.com/OpenLAIR/OpenSkill**）, 几乎是本项目的「学术对应物」：在**无 target 监督**下从文档/仓库/网页抽取 **verification anchors**，合成 skill，再用锚点自建练习任务打磨；target 监督**只留最终评测**（天然防污染）。实测自建 verifier 与隐藏 ground-truth 对齐。→ **护栏①的现成蓝图**。局限：锚点仍针对有客观答案的任务（代码/工具），迁到主观调研需改造成「事实可核验子断言」层。
- **EVE-Agent: Evidence-Verifiable Self-Evolving Agents**（2605.22905）, 强制每条自生成样本带**逐字证据片段**，按「加证据后的边际准确率增益」打分，抑制「流畅但无支撑」。→ 映射调研 skill：每条结论挂可回溯到源的逐字 span，评审按「该 span 是否真提升答对率」打分。
- **OPD-Evolver**（2606.17628，开源 github.com/bingreeky/opd-evolver）, outcome-calibrated memory attribution（结果校准归因）把记忆能力蒸馏回策略。可借鉴「用可验证结果做 credit 归因」。

### 3.2 改后回归回查 / 退化防护（护栏⑤）★大量实证支撑
- **Library Drift**（2605.19576）, 命名「库漂移」：skill 库无节制增长→检索退化/假阳性/停滞。**SkillsBench 上 LLM 写的 skill +0.0pp vs 人工 +16.2pp**（裸自迭代直接 plateau！）。修复：outcome-driven retirement + bounded active-cap + append-only 证据日志。MBPP+ 100 轮 pass@1 0.258→0.584。→ **回归门 + 版本上限**。
- **Do Self-Evolving Agents Forget?**（2605.09315）, 首次量化「自演化能力侵蚀」：旧能力**非单调退化**；CPE 把退化任务 41.8%→52.8%。→ **「为什么必须改后回归回查旧主题」的实证依据**。
- **Useful Memories Become Faulty When Continuously Updated by LLMs**（2605.12978）, 用 LLM **持续改写记忆**会效用先升后降、**跌破不改写的 baseline**，失真来自改写动作本身。只保留原始 episode 的对照组准确率是强制 consolidation 的 2 倍。→ **直接预言本项目「持续重写 skill」的退化路径；处方=保留原始证据为一等公民 + 档案回退**。
- **BenchTrace**（2605.29225）, 把「反思质量」从 task score 解耦单独测：**端到端反思通过率 <30%**，只有「完全正确的反思」才提升失败回避率。→ **改 skill 前必须验证反思正确性，否则期望为负**。
- **MOSS**（2605.22794，开源 github.com/hkgai-official/Moss）, 源代码层自改写 + **trial-worker 重放失败用例 + health-probe 回滚**。0.25→0.61。→ 回归回查 + 回滚的工程模板（但靠可判定 grader）。
- **HarnessFix / From Failed Trajectories**（2606.06324）, 故障归因→定位到 harness 层→scoped repair operator→在 flaw 专属规约下验证补丁抑制回归。→ 把「反思后改 skill」从自由改写变成**可定位、限范围的修补**。

### 3.3 自指改进的可信度认证（原空白2）★已被占据
- **PACE: Anytime-Valid Acceptance Tests**（2606.08106）, **把「是否采纳一次自改进」重构为序列假设检验**（testing-by-betting e-process，anytime-valid，控制误提交率、支持提前停止）。实证：贪心「涨了就留」会提交 **30-42% 假提交、72-100% 纯噪声自改**；PACE 几乎只提交真改进，还省 18% 评估成本。→ **这正是我第一篇提的「自欺指数 / 改后统计认证」，现已被做出来。本项目应直接实现这个 acceptor 门替代「重跑对比涨了就保留」**。
- **The Meta-Agent Challenge**（2606.04455，开源 github.com/ant-research/meta-agent-challenge）, meta-agent 迭代造 agent 去刷 held-out eval；**实测涌现 ground-truth exfiltration（窃取真值刷分）**，配多层防 reward-hacking。→ **reward hacking 被实证 + 防线模板**；并量化「开源模型几乎打不过人工基线、方差极高」→ 多路迭代必须强回归 + 异构评审兜底。

### 3.4 任务-技能协同进化（原空白3）/ 新颖度
- **SkillSmith: Co-Evolving Skills and Tools**（2606.01314）, 反思同时改 skill + tool 原子 bundle，用 Lotka-Volterra 生态效用模型（skill 互补/冲突矩阵）驱动检索/变异/退役 + anti-pattern 失败记忆否决。→ skill-tool 协同进化（但**不是**任务生成器↔skill 的对抗协同，且靠可验证 reward）。
- **Interestingness as an Inductive Heuristic**（2605.14831，Schmidhuber 路线纯理论）, 把「有趣性」形式化为**预测未来压缩进步**；期望进步随「上次突破新近度」指数衰减。→ 为 brainstorm 新主题的**优先级/探索预算**提供原则依据（对刚出过增益的方向继续投、长期无进展降权）。

### 3.5 低相关（标题贴边但本质不同）
- **PaSaMaster / Towards Self-Evolving Agentic Literature Retrieval**（2605.14306，开源 github.com/sjtu-sai-agents/PaSaMaster）, 是**单次检索任务内**的运行时迭代，有 ground-truth（F1），不改自身资产、不维护版本档案。可借鉴「规划与执行解耦 + 轻量模型批量打分降本」，但非元层自改进闭环。

---

## 4. 研究方向定位（基于交叉验证的更新）

| 第一篇的判断 | 交叉验证后的更新 |
|---|---|
| 空白1：无 ground-truth 开放域自改进 | **下修但仍成立**。OpenSkill / EVE-Agent 已攻「无监督自改进」，但都靠**有客观答案的任务**（代码/工具）。**真正主观的投资/商业调研报告仍无人做**,这是残留的真空白。 |
| 空白2：自指改进可信度认证（「自欺指数」） | **基本被占据**。PACE（2026-06）做出了 anytime-valid acceptor 门，Meta-Agent Challenge 实证了 exfiltration。→ 不再是通用空白；**新意只能收窄到「开放调研域 + 无标签下如何构造 PACE 的配对统计量」**。 |
| 空白3：任务生成器↔skill 对抗协同进化 | **仍成立**。SkillSmith 只做 skill-tool 协同（非对抗式任务课程），OMNI/ACD 用于 RL/能力发现而非驱动 skill 进化。**「自动红队课程 ↔ 调研 skill 在有外部真值锚的开放域里协同进化」依然是空白**。 |

**修订后的最有相性的研究角度**：
> **在「半可验证的开放调研域」上，把 OpenSkill 式 verification-anchor（护栏①）+ PACE 式 anytime-valid acceptor（认证）+ 对抗式任务-skill 协同进化（空白3）三者缝在一起**，并用「事实可核验子断言」改造 EVE-Agent 的边际增益度量。这是当前所有 2026 工作都未同时覆盖的组合，且本项目有 market-intel/edgartools 现成真值源。

---

## 5. 可直接借鉴的 2026 新开源（除第一篇的 GEPA/OpenEvolve/DSPy 外）

| 仓库 | 对应护栏/用途 |
|---|---|
| **github.com/OpenLAIR/OpenSkill** | 护栏①：无监督下从外部抽 verification anchor + 自建练习任务（最贴本项目场景）|
| **github.com/hkgai-official/Moss** | 护栏⑤ + 档案：trial-worker 重放 + health-probe 回滚 |
| **github.com/ant-research/meta-agent-challenge** | 护栏②/⑥：防 reward-hacking 评测 harness 模板 + exfiltration 案例 |
| **github.com/bingreeky/opd-evolver** | 结果校准归因（外部锚思路）|
| **github.com/sjtu-sai-agents/PaSaMaster** | 检索：规划/执行解耦 + 轻量模型批量打分降本 |
| PACE（论文 2606.08106，repo 待查）| 认证：把 e-process anytime-valid acceptor 实现为「改 skill 后的提交门」|

---

## 6. 对 prompt 的最终建议（综合两篇）

1. **删掉「重跑旧主题对比，涨了就保留」**,PACE 实证这会产生 30-42% 假提交。换成 **PACE 式 anytime-valid acceptor 门**（配对 + e-process）。
2. **「改 skill」前先验证反思正确性**（BenchTrace：反思 <30% 正确，否则期望为负）；改动**限范围**（HarnessFix）。
3. **保留原始调研轨迹为一等公民**，skill 只选择性更新 + 可回退档案（Useful Memories / DGM archive）；设 skill 库**活跃上限**防 Library Drift。
4. **评审锚到事实**：每条结论挂可外部核验的逐字证据 span（EVE-Agent / OpenSkill），judge 用异构模型，按「该证据是否真提升正确性」打分。
5. **新主题**用 interestingness（预测增益）+ novelty/coverage 门控，防 mode collapse。
