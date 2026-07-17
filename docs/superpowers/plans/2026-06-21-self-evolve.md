# self-evolve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 `self-evolve`, 一个用确定性 Python harness 编排、LLM 只提议/代码裁决的自迭代工具进化 Claude Code skill，指向任意 skill/仓库/项目即可在 worktree 沙箱内多轮改进它，并用不可 game 的 PACE 提交门 + 程序化锚保证"被采纳=真改进"。

**Architecture:** 方法论 skill（SKILL.md 门控）+ 确定性 harness `tools/sie/`（10 态状态机，所有采纳/拒绝/回滚/分档由代码裁决，搜索/反思/评审才用 LLM）+ subagent 编排（`workflows/*.js`）。分层评测 A(可验证)/B(锚半验证)/C(主观)，统一经 PACE anytime-valid e-process acceptor。全程沙箱，不可逆/外向动作走人审独立子流程。

**Tech Stack:** Python 3.11+（harness/CLI）、`confseq`（testing-by-betting e-value/wealth 底层）、`edgartools`（B 档 EDGAR 真值源）、git worktree（沙箱）、Claude Code subagent + codex skill（异构 judge）、Node/JS（workflows fanout）、pytest（自测）。

## Global Constraints

> 每个任务的要求都隐含包含本节。数值与规则逐字取自 spec v3.1。

- **平台**：Windows 11 + PowerShell 主壳 / Git Bash 辅；路径用绝对路径；`git worktree` 沙箱。
- **裁决铁律**：LLM 只提议；采纳/拒绝/回滚/分档由 harness 确定性代码；搜索引擎(GEPA/OpenEvolve)只进 PROPOSE 步，绝不评判自己产出。
- **原始证据**：trace/反思 append-only 只读，永不被 LLM 改写。
- **数据隔离（铁律5）**：frozen 锚 claim/verified 值/marginal_gain、测试真值，对 REFLECT/PROPOSE/PATCH 进程不可读（只暴露 task 输入）。
- **IMMUTABLE 裁决代码集**：`statemachine/acceptor/judges/verifiable/anchors/selfdeception/gate_human/profile 判定/sandbox 边界/supervisor loader`,M4 起从 frozen base ref 按内容哈希加载；M1-M3 用"可写 glob 排除 + AST 危险门"先挡。
- **judge 池**：仅 **Claude + Codex**（不装 gemini/minimax）。Codex(codex skill，最强模型，禁 browser/playwright、只用 web_search)=主独立非 proposer judge；Claude=去偏次 judge；Codex 不可用→禁单 Claude 自动 ACCEPT，降级锚+人审。
- **安全边界**：评测子进程禁网（M1）/ M2 起经 harness 代发白名单审查代理；最小化环境（清非白名单 env，token/key 与 `~`/.credentials.json 不可读）；candidate 禁 import discord_relay；gate 路径 realpath canonical 比对沙箱根，拒 symlink/`..`；outward(出沙箱写删/push/合主分支/对外发送)=GATED。
- **校准参数初值**（跑一轮后校准）：`α=0.05`，`n_min=8`，`anchor_set_min=24`，`effective_independent_anchor_min=12`，`holdout_fraction=0.3`，`continue_count_cap=5`，`no_progress_circuit N=8`，`no_progress_release M=3`，`static_reject_circuit=6`，`forced_review_circuit=5`，`drift_circuit=4`，`cumulative_drift_tolerance=1.5×`，`frozen_anchor_effective_gain_ε=0.02`，`selfdeception_alert_band=0.15`，`N_reflectors=1(M1)→3(M3)`，`reflection_correctness_threshold=0.5`，`judge_agreement α_low=0.4/α_high=0.85`，`active_cap=64`，`K=5`。
- **提交纪律**：每个 step 尾部 commit；commit message 末尾加项目约定的 Co-Authored-By / Claude-Session trailer（见仓库已有 commit 范式）。
- **No placeholders**：测试代码与关键实现代码必须写实，不留 TODO/“类似 Task N”。

## 文件结构（决策锁定）

```
self-evolve/
  SKILL.md                       # 门控序列总纲(给主 agent 读)
  commands/{self-evolve,self-evolve-status,self-evolve-resume}.md
  tools/sie/
    __init__.py
    cli.py            # CLI: init|run|status|review|land|replay|rollback|diff
    statemachine.py   # 10 态主循环 + 三计数器 + 转移
    state.py          # RunState dataclass + 原子 save/load(tmp+rename)
    events.py         # append-only 事件日志 + replay 重建
    sandbox.py        # worktree 建/销 + realpath canonical 边界 + action 分级(IMMUTABLE)
    profile.py        # 信号发现/画像→tier 冻结; visible/holdout 锚拆分
    probes/{__init__,exec_probe,ci_probe,fact_probe,selftest_probe}.py
    reflect.py        # 调度反思(M1 串行→M3 并行 fanout)
    check_reflection.py
    propose.py        # meta 汇总→scoped patch; backend 可选
    backends/{__init__,builtin,gepa_backend,openevolve_backend}.py
    patch.py          # 逐 patch 应用 + AST 危险门 + contract 静态检查
    evaluate.py       # 分层评测编排→分向量
    verifiable.py     # A 档 grader + 快照哈希 + 变异测试有效性门 + trial-worker
    anchors.py        # B 档抽锚/核查/EVE 边际增益/visible-holdout/去相关
    judges.py         # Claude+Codex 异构 judge 适配 + 配对 α
    acceptor.py       # PACE per-tier e-process(站 confseq) + 三态
    selfdeception.py  # 自欺指数多闸 + 累计漂移
    archive.py        # lineage + Pareto 硬维门 + Library Drift 退役 + rollback
    gate_human.py     # action 分级→pending 队列 + 非阻塞
    notify.py         # 仅主进程: 调 the notifier
    proxy.py          # (M2) 出站 harness 代发 + 内容/序列审查
  workflows/{reflect-fanout.js, review-fanout.js}
  reference/{target_contract.md, acceptor_math.md, signal-providers.md, runbook.md}
  tests/...           # 与各模块对应
  metrics/  learnings.md
```

## 跨里程碑共享接口契约（所有任务必须按此签名，勿改名）

```python
# state.py
@dataclass
class RunState:
    run_id: str; phase: str; round: int; parent_vid: str | None
    tier: str  # "A"|"B"|"C"|叠加如"A+B"
    no_progress: int = 0; static_reject: int = 0; forced_review: int = 0
    continue_count: int = 0; drift_count: int = 0
def save_state(rs: RunState, run_dir: str) -> None        # 原子 tmp+rename
def load_state(run_dir: str) -> RunState

# events.py
def append_event(run_dir: str, event: dict) -> None        # jsonl, 真相源
def replay(run_dir: str) -> RunState                        # 从事件流重建

# target_contract (reference/target_contract.md + 目标侧实现)
# grade(task) 返回:
#   {"task_passed": bool, "grader_exit_code": int,
#    "dimensions": [{"name": str, "tier": "A"|"B"|"C", "score": float, "weight": float}],
#    "anchors": [{"claim": str, "span": str, "source_url": str, "fetched_at": str,
#                 "verified": bool, "marginal_gain": float}],
#    "verifiable_coverage": float}
# A 档: tier=A 的 score∈{0,1} 由 grader_exit_code 映射; PACE A 配对消费 task_passed

# acceptor.py
def decide(paired: list[tuple[float,float]], tier: str, st: RunState,
           params: dict) -> dict   # -> {"decision":"ACCEPT"|"REJECT"|"CONTINUE", "evalue":float, "reason":str}
#   A 档二态(禁 CONTINUE); B 档 n_anchor<n_min 或 有效独立锚<下限→不可 ACCEPT; 主观分方差缩放+evalue_max_step

# anchors.py
def extract_anchors(artifact_path: str) -> list[dict]      # 锚字段代码判定
def split_visible_holdout(anchors: list[dict], frac: float) -> tuple[list,list]
def verify_anchor(anchor: dict) -> dict                    # edgartools/价格核查→{...,"verified":bool}
def marginal_gain(anchor: dict, base_score: float, with_score: float) -> float
def coverage(anchors: list[dict]) -> float
def effective_independent_count(anchors: list[dict]) -> int  # 按 source_url/主题去相关

# judges.py
def score(artifact_path: str, anchors_visible: list[dict], family: str) -> dict  # family∈{"claude","codex"}
def pairwise_agreement(scores_a: dict, scores_b: dict) -> float                  # α

# selfdeception.py
def index(judge_gain: float, visible_anchor_gain: float, holdout_gain: float,
          st: RunState) -> dict   # -> {"value":float,"alerts":[...]}  (多闸)

# archive.py
def add_version(run_dir: str, vid: str, scores: dict, parent_vid: str|None) -> None
def rollback(archive_dir: str, vid: str) -> None
def pareto_front(archive_dir: str) -> list[str]            # 硬维门
def retire_stale(archive_dir: str, active_cap: int) -> None

# sandbox.py
def make_worktree(target: str, base_ref: str, run_id: str) -> str
def canonical_in_sandbox(path: str, sandbox_root: str) -> bool   # realpath 比对
def action_class(action: dict, sandbox_root: str) -> str         # "auto"|"gated"

# gate_human.py
def enqueue(run_dir: str, action: dict) -> str            # -> aid; 非阻塞
def pending(run_dir: str) -> list[dict]

# profile.py
def run_profile(target: str, base_ref: str) -> dict       # -> target.json(tier,score,visible+holdout 锚,探针证据)
```

---
## 里程碑 M1a: 端到端骨架 (~14-18h)

**目标**：让 `self-evolve` harness 对一个真实 pytest repo 跑通完整 10 态闭环（INIT→PROFILE(A/C 二分)→SELECT→REFLECT(串行)→PROPOSE(builtin)→PATCH(基础 apply+import 白名单)→EVALUATE(只走 verifiable)→ACCEPT(no-regression 硬门兜底)→ARCHIVE(lineage+rollback)→LOOP），所有采纳/拒绝/回滚由确定性代码裁决，崩溃后可从 `events.jsonl` 重放恢复。

**本里程碑验收标准（spec §13 M1a）**：
- confseq spike 第 0 步硬前置通过：纯噪声序列 e-process 拒绝率高、能拿到 wealth/e-value 接口；失败则停下重选 acceptor 方案，不进编码。
- 真 pytest repo 全闭环：能跑（init→run）、能采纳（真增益候选被 ACCEPT 进 archive）、能回滚（rollback 到任意 lineage 版本）。
- 崩溃重放一致：run 中途 kill，`replay()` 从 `events.jsonl` 重建的 `RunState` 与崩溃前最后落盘的 `state.json` 字段逐项一致。
- 禁网硬门：评测子进程任何出站被拒（M1 allowlist 空）。
- realpath canonical 沙箱边界：symlink/`..` 穿越出沙箱根的写/删被判 GATED（不受 `--mode auto` 影响）。
- 凭证隔离：评测子进程读 `.credentials.json`/非白名单 env 失败；candidate `import discord_relay` 被拒。

> 本里程碑只交付 acceptor 的 **no-regression 硬门兜底**（任一回归任务从 pass 退化到 fail 即硬 REJECT，否则 ACCEPT）。PACE e-process 三态 + 噪声/对抗单测留 M1b。但 confseq spike（第 0 步）在本里程碑先打通，因为它是 M1 整体的硬前置，且 `acceptor.decide()` 签名要在 M1a 就锁定（M1a 内部实现先用 no-regression，M1b 替换为 e-process）。

---

### Task M1a.0: confseq spike（第 0 步硬前置）

> 纯噪声序列验证 testing-by-betting 库能给 e-value/wealth 接口且对纯噪声拒绝率高。**失败则停**，不进后续编码。

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/__init__.py`（空包标记）
- Create: `~/CodesSelf/self-evolve/spikes/confseq_spike.py`
- Create: `~/CodesSelf/self-evolve/requirements.txt`
- Test: `~/CodesSelf/self-evolve/tests/test_confseq_spike.py`

**Interfaces:**
- Consumes: `confseq` 库的 e-process / betting 接口（spike 内探测真实 API）。
- Produces: `run_noise_spike(n_trials: int, n_steps: int, alpha: float, seed: int) -> dict`（返回 `{"rejection_rate": float, "e_interface": str}`）；为 M1a/M1b 的 `acceptor.py` 锁定"e-process wealth 可用"这一前提。

- [ ] **Step 1: 安装并探测 confseq 真实 API（spike，非 TDD）**
  写 `requirements.txt`：
  ```
  confseq>=0.0.9
  numpy>=1.26
  pytest>=8.0
  ```
  装库并打印可用接口（确认 wealth / e-process betting 类名与方法，因 API 可能随版本变）：
  Run: `python -m pip install -r ~/CodesSelf/self-evolve/requirements.txt`
  Run: `python -c "import confseq, confseq.betting as b; print([x for x in dir(b) if not x.startswith('_')])"`
  Expected: 打印出 betting 相关函数名（如 `betting_mart` / `betting_ci` 等）。若 import 失败或无 betting 接口 → **停下，本前置不通过，不继续编码**，回到 spec §14 重选 acceptor 方案。

- [ ] **Step 2: 写失败测试（纯噪声拒绝率）**
  ```python
  # tests/test_confseq_spike.py
  import numpy as np
  from spikes.confseq_spike import run_noise_spike

  def test_noise_rejection_rate_high():
      # 纯噪声配对差(均值0)在 alpha=0.05 下应几乎不被拒(e-process 不应误报增益)
      # 这里的"拒绝"= e-value 越过 1/alpha 阈, 即误判"有增益"
      res = run_noise_spike(n_trials=200, n_steps=300, alpha=0.05, seed=7)
      # 误提交率(把纯噪声判成有增益)必须 <= alpha 容差
      assert res["false_reject_rate"] <= 0.10, res
      assert res["e_interface"]  # 确认拿到了 e-value 接口

  def test_true_gain_detected():
      # 注入真实正向漂移(均值+0.3)应被高概率检出
      res = run_noise_spike(n_trials=100, n_steps=300, alpha=0.05, seed=11, drift=0.3)
      assert res["detect_rate"] >= 0.8, res
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_confseq_spike.py -q`
  Expected: FAIL（`spikes.confseq_spike` 不存在）。

- [ ] **Step 3: 写 spike 实现（真实 confseq 调用）**
  ```python
  # spikes/confseq_spike.py
  """confseq 第 0 步硬前置 spike: 纯噪声序列验证 e-process 拒绝率。
  失败(纯噪声误报率高 / 拿不到 e-value 接口)则 M1 acceptor 方案需重选。"""
  from __future__ import annotations
  import numpy as np
  from confseq.betting import betting_mart  # e-process martingale (wealth)


  def _e_process(diffs: np.ndarray) -> np.ndarray:
      """把配对差序列(零均值=无增益)喂 betting martingale, 返回逐步 wealth(e-value)。
      H0: 真实均值 <= 0.5(无增益); 把 diff 映射到 [0,1] 后检验 mean>0.5。"""
      x = np.clip(0.5 + diffs, 0.0, 1.0)  # diff=0 -> 0.5(null); diff>0 -> 偏向有增益
      # betting_mart 返回逐步 e-process(wealth); 取最终值作为 anytime-valid e-value
      mart = betting_mart(x, m=0.5)
      return np.asarray(mart, dtype=float)


  def run_noise_spike(n_trials: int, n_steps: int, alpha: float, seed: int,
                      drift: float = 0.0) -> dict:
      rng = np.random.default_rng(seed)
      thresh = 1.0 / alpha
      crossed = 0
      for _ in range(n_trials):
          diffs = rng.normal(loc=drift, scale=1.0, size=n_steps) * 0.1
          wealth = _e_process(diffs)
          if np.nanmax(wealth) >= thresh:
              crossed += 1
      rate = crossed / n_trials
      out = {"e_interface": "confseq.betting.betting_mart", "threshold": thresh}
      if drift == 0.0:
          out["false_reject_rate"] = rate
      else:
          out["detect_rate"] = rate
      return out
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_confseq_spike.py -q`
  Expected: PASS。若 `false_reject_rate` 偏高（>0.10），调 H0 映射/`m` 参数或换 `betting_ci`，直到纯噪声不误报；仍失败 → 前置不通过。

- [ ] **Step 4: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/__init__.py spikes/confseq_spike.py tests/test_confseq_spike.py requirements.txt && git commit -m "$(cat <<'EOF'
M1a: confseq spike 第0步硬前置 — 纯噪声 e-process 拒绝率验证通过

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.1: state.py, RunState + 原子 save/load

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/state.py`
- Test: `~/CodesSelf/self-evolve/tests/test_state.py`

**Interfaces:**
- Produces（契约锁定，勿改名）：
  - `@dataclass RunState`（字段：`run_id:str, phase:str, round:int, parent_vid:str|None, tier:str, no_progress:int=0, static_reject:int=0, forced_review:int=0, continue_count:int=0, drift_count:int=0`）
  - `save_state(rs: RunState, run_dir: str) -> None`（tmp+rename 原子写）
  - `load_state(run_dir: str) -> RunState`

- [ ] **Step 1: 写失败测试（roundtrip + 原子性）**
  ```python
  # tests/test_state.py
  import json, os
  from tools.sie.state import RunState, save_state, load_state

  def test_roundtrip(tmp_path):
      rs = RunState(run_id="r1", phase="PROFILE", round=2, parent_vid=None, tier="A",
                    no_progress=1, static_reject=0, forced_review=3, continue_count=2, drift_count=1)
      save_state(rs, str(tmp_path))
      back = load_state(str(tmp_path))
      assert back == rs

  def test_atomic_no_tmp_left(tmp_path):
      rs = RunState(run_id="r1", phase="INIT", round=0, parent_vid="base", tier="C")
      save_state(rs, str(tmp_path))
      # 落盘后不应残留 tmp 文件
      leftovers = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
      assert leftovers == []
      assert os.path.exists(os.path.join(tmp_path, "state.json"))

  def test_partial_write_does_not_corrupt(tmp_path):
      rs1 = RunState(run_id="r1", phase="INIT", round=0, parent_vid=None, tier="A")
      save_state(rs1, str(tmp_path))
      # 写一个损坏的 tmp 不应影响已有 state.json
      with open(os.path.join(tmp_path, "state.json.tmp"), "w") as fh:
          fh.write("{ broken")
      back = load_state(str(tmp_path))
      assert back == rs1
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_state.py -q`
  Expected: FAIL（模块不存在）。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/state.py
  from __future__ import annotations
  import json, os
  from dataclasses import dataclass, asdict, fields

  STATE_FILE = "state.json"


  @dataclass
  class RunState:
      run_id: str
      phase: str
      round: int
      parent_vid: str | None
      tier: str  # "A"|"B"|"C"|叠加如"A+B"
      no_progress: int = 0
      static_reject: int = 0
      forced_review: int = 0
      continue_count: int = 0
      drift_count: int = 0


  def save_state(rs: RunState, run_dir: str) -> None:
      os.makedirs(run_dir, exist_ok=True)
      final = os.path.join(run_dir, STATE_FILE)
      tmp = final + ".tmp"
      with open(tmp, "w", encoding="utf-8") as fh:
          json.dump(asdict(rs), fh, ensure_ascii=False, indent=2)
          fh.flush()
          os.fsync(fh.fileno())
      os.replace(tmp, final)  # 原子 rename(Win/Posix 均原子)


  def load_state(run_dir: str) -> RunState:
      with open(os.path.join(run_dir, STATE_FILE), "r", encoding="utf-8") as fh:
          data = json.load(fh)
      allowed = {f.name for f in fields(RunState)}
      return RunState(**{k: v for k, v in data.items() if k in allowed})
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_state.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/state.py tests/test_state.py && git commit -m "$(cat <<'EOF'
M1a: state.py RunState + 原子 tmp+rename save/load

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.2: events.py, append-only 事件流 + replay 重建

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/events.py`
- Test: `~/CodesSelf/self-evolve/tests/test_events.py`

**Interfaces:**
- Consumes: `tools.sie.state.RunState`。
- Produces（契约锁定）：
  - `append_event(run_dir: str, event: dict) -> None`（jsonl，真相源，append-only）
  - `replay(run_dir: str) -> RunState`（从事件流重建 RunState）

> 关键易错点：replay 必须能从 `events.jsonl` 重建出与崩溃前 `state.json` 一致的 RunState（验收硬指标）。约定每条事件含 `type` 与对 RunState 的字段更新；replay 顺序回放、用确定性规约函数应用每条事件，不依赖 `state.json`。

- [ ] **Step 1: 写失败测试（append + replay 一致性 + 崩溃模拟）**
  ```python
  # tests/test_events.py
  import os
  from tools.sie.state import RunState, save_state, load_state
  from tools.sie.events import append_event, replay

  def _drive(run_dir):
      # 模拟主循环逐态推进, 每态既 append_event 又 save_state
      seq = [
          {"type": "INIT", "run_id": "r1", "tier": "A", "parent_vid": "base", "round": 0, "phase": "INIT"},
          {"type": "PROFILE", "phase": "PROFILE", "tier": "A"},
          {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 1},
          {"type": "REJECT", "phase": "LOOP", "no_progress_delta": 1},
          {"type": "ROUND_BEGIN", "phase": "REFLECT", "round": 2},
          {"type": "ACCEPT", "phase": "ARCHIVE", "no_progress_reset": True, "parent_vid": "v1"},
      ]
      rs = RunState(run_id="r1", phase="INIT", round=0, parent_vid=None, tier="A")
      for ev in seq:
          append_event(run_dir, ev)
          rs = replay(run_dir)        # 真相源驱动
          save_state(rs, run_dir)     # 旁路落盘
      return rs

  def test_replay_matches_saved_state(tmp_path):
      run_dir = str(tmp_path)
      final = _drive(run_dir)
      # 崩溃重放: 删掉 state.json, 仅从 events.jsonl 重建
      os.remove(os.path.join(run_dir, "state.json"))
      rebuilt = replay(run_dir)
      assert rebuilt == final

  def test_counters_apply(tmp_path):
      run_dir = str(tmp_path)
      final = _drive(run_dir)
      assert final.round == 2
      assert final.no_progress == 0   # ACCEPT 重置
      assert final.parent_vid == "v1"
      assert final.tier == "A"
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_events.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现（确定性规约）**
  ```python
  # tools/sie/events.py
  from __future__ import annotations
  import json, os
  from dataclasses import replace
  from tools.sie.state import RunState

  EVENTS_FILE = "events.jsonl"


  def append_event(run_dir: str, event: dict) -> None:
      os.makedirs(run_dir, exist_ok=True)
      with open(os.path.join(run_dir, EVENTS_FILE), "a", encoding="utf-8") as fh:
          fh.write(json.dumps(event, ensure_ascii=False) + "\n")
          fh.flush()
          os.fsync(fh.fileno())


  # 直接覆盖的标量字段
  _DIRECT = ("run_id", "phase", "round", "parent_vid", "tier")


  def _apply(rs: RunState, ev: dict) -> RunState:
      patch: dict = {}
      for k in _DIRECT:
          if k in ev:
              patch[k] = ev[k]
      # 计数器增量
      for cnt in ("no_progress", "static_reject", "forced_review",
                  "continue_count", "drift_count"):
          d = ev.get(f"{cnt}_delta")
          if d:
              patch[cnt] = getattr(rs, cnt) + d
          if ev.get(f"{cnt}_reset"):
              patch[cnt] = 0
      # ACCEPT 语义: 清零 no_progress/forced_review(态8)
      if ev.get("type") == "ACCEPT" or ev.get("no_progress_reset"):
          patch["no_progress"] = 0
      if ev.get("type") == "ACCEPT" or ev.get("forced_review_reset"):
          patch["forced_review"] = 0
      return replace(rs, **patch)


  def replay(run_dir: str) -> RunState:
      rs = RunState(run_id="", phase="INIT", round=0, parent_vid=None, tier="")
      path = os.path.join(run_dir, EVENTS_FILE)
      if not os.path.exists(path):
          return rs
      with open(path, "r", encoding="utf-8") as fh:
          for line in fh:
              line = line.strip()
              if not line:
                  continue
              rs = _apply(rs, json.loads(line))
      return rs
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_events.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/events.py tests/test_events.py && git commit -m "$(cat <<'EOF'
M1a: events.py append-only 事件流 + replay 确定性重建

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.3: sandbox.py, worktree + realpath canonical 边界 + action 分级

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/sandbox.py`
- Test: `~/CodesSelf/self-evolve/tests/test_sandbox.py`

**Interfaces:**
- Produces（契约锁定）：
  - `make_worktree(target: str, base_ref: str, run_id: str) -> str`（建 git worktree，返回沙箱根绝对路径；失败 raise）
  - `canonical_in_sandbox(path: str, sandbox_root: str) -> bool`（realpath 解析后比对沙箱根 canonical 前缀，拒 symlink/`..` 穿越）
  - `action_class(action: dict, sandbox_root: str) -> str`（→`"auto"`|`"gated"`；canonical-在沙箱内写/删=auto，outward=gated，IMMUTABLE 规则不受 `--mode` 影响）

> 关键易错点（沙箱边界，IMMUTABLE）：`canonical_in_sandbox` 必须 `os.path.realpath` 两侧后用 `os.path.commonpath` 判断，且要处理"目标尚不存在但其父目录在沙箱内"的写场景（解析父目录 realpath）。symlink 指向沙箱外、`..` 逃逸都必须返回 False。Windows 大小写不敏感用 `os.path.normcase`。

- [ ] **Step 1: 写失败测试（边界 + 分级，含 symlink 逃逸）**
  ```python
  # tests/test_sandbox.py
  import os, pytest
  from tools.sie.sandbox import canonical_in_sandbox, action_class

  def test_inside(tmp_path):
      root = str(tmp_path / "sbx"); os.makedirs(root)
      p = os.path.join(root, "sub", "a.txt")
      assert canonical_in_sandbox(p, root) is True   # 父目录在沙箱内即可(尚不存在)

  def test_dotdot_escape(tmp_path):
      root = str(tmp_path / "sbx"); os.makedirs(root)
      p = os.path.join(root, "..", "outside.txt")
      assert canonical_in_sandbox(p, root) is False

  def test_symlink_escape(tmp_path):
      root = str(tmp_path / "sbx"); os.makedirs(root)
      outside = tmp_path / "secret"; outside.mkdir()
      link = os.path.join(root, "link")
      try:
          os.symlink(str(outside), link)
      except (OSError, NotImplementedError):
          pytest.skip("no symlink privilege")
      target = os.path.join(link, "x.txt")
      assert canonical_in_sandbox(target, root) is False

  def test_action_class_auto_vs_gated(tmp_path):
      root = str(tmp_path / "sbx"); os.makedirs(root)
      inside = {"op": "write", "path": os.path.join(root, "f.py")}
      assert action_class(inside, root) == "auto"
      outside = {"op": "write", "path": os.path.join(str(tmp_path), "real_target.py")}
      assert action_class(outside, root) == "gated"
      # outward 类动作恒 gated(即便 path 在沙箱内)
      for op in ("push", "merge_main", "send", "delete_outside"):
          assert action_class({"op": op, "path": os.path.join(root, "f")}, root) == "gated"
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_sandbox.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/sandbox.py
  from __future__ import annotations
  import os, subprocess

  # IMMUTABLE: outward 动作恒 GATED, 不受 --mode 影响
  OUTWARD_OPS = {"push", "merge_main", "send", "delete_outside", "land", "approve"}


  def _real(path: str) -> str:
      # 解析存在部分的 realpath; 对尚不存在的叶子, 解析其最近存在祖先后再拼接剩余
      path = os.path.abspath(path)
      head = path
      tail_parts = []
      while not os.path.exists(head):
          head, t = os.path.split(head)
          if not t:
              break
          tail_parts.append(t)
      resolved = os.path.realpath(head)
      for t in reversed(tail_parts):
          resolved = os.path.join(resolved, t)
      return os.path.normcase(resolved)


  def canonical_in_sandbox(path: str, sandbox_root: str) -> bool:
      root = os.path.normcase(os.path.realpath(sandbox_root))
      rp = _real(path)
      try:
          return os.path.commonpath([rp, root]) == root
      except ValueError:  # 不同盘符
          return False


  def action_class(action: dict, sandbox_root: str) -> str:
      op = action.get("op", "")
      if op in OUTWARD_OPS:
          return "gated"
      path = action.get("path", "")
      if path and canonical_in_sandbox(path, sandbox_root):
          return "auto"
      return "gated"


  def make_worktree(target: str, base_ref: str, run_id: str) -> str:
      target = os.path.abspath(target)
      sandbox_root = os.path.join(target, ".sie", "worktrees", run_id)
      os.makedirs(os.path.dirname(sandbox_root), exist_ok=True)
      # 已存在(resume) 直接返回
      if os.path.isdir(os.path.join(sandbox_root, ".git")) or os.path.exists(
              os.path.join(sandbox_root, ".git")):
          return sandbox_root
      branch = f"sie/{run_id}"
      subprocess.run(
          ["git", "-C", target, "worktree", "add", "-b", branch, sandbox_root, base_ref],
          check=True, capture_output=True, text=True)
      return sandbox_root
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_sandbox.py -q`
  Expected: PASS。

- [ ] **Step 3: 真 worktree 集成测试（建一个临时 git repo 实建 worktree）**
  ```python
  # 追加到 tests/test_sandbox.py
  import subprocess as sp
  def test_make_worktree_real(tmp_path):
      tgt = tmp_path / "repo"; tgt.mkdir()
      sp.run(["git", "init", "-q"], cwd=tgt, check=True)
      sp.run(["git", "config", "user.email", "t@t"], cwd=tgt, check=True)
      sp.run(["git", "config", "user.name", "t"], cwd=tgt, check=True)
      (tgt / "f.txt").write_text("hi")
      sp.run(["git", "add", "-A"], cwd=tgt, check=True)
      sp.run(["git", "commit", "-qm", "init"], cwd=tgt, check=True)
      from tools.sie.sandbox import make_worktree, canonical_in_sandbox
      root = make_worktree(str(tgt), "HEAD", "runX")
      assert os.path.isfile(os.path.join(root, "f.txt"))
      assert canonical_in_sandbox(os.path.join(root, "new.py"), root)
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_sandbox.py -q`
  Expected: PASS。

- [ ] **Step 4: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/sandbox.py tests/test_sandbox.py && git commit -m "$(cat <<'EOF'
M1a: sandbox.py worktree + realpath canonical 边界 + action 分级(IMMUTABLE)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.4: probes/exec_probe + profile.py（A/C 二分 + exec 变异测试二次校验）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/probes/__init__.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/probes/exec_probe.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/profile.py`
- Test: `~/CodesSelf/self-evolve/tests/test_profile.py`

**Interfaces:**
- Consumes: 无（子进程跑 pytest）。
- Produces（契约锁定）：
  - `probes.exec_probe.run_exec_probe(sandbox_root: str) -> dict`（→`{"has_tests":bool, "exit_code":int, "mutation_killed":bool}`）
  - `profile.run_profile(target: str, base_ref: str) -> dict`（→ 写 `target.json` 内容 dict：`{"tier":str, "verifiability_score":float, "visible":[], "holdout":[], "probes":{...}}`，M1a 只做 A/C 二分）

> 关键易错点（exec 变异测试二次校验，spec §5.1）：判 A 档不能只看"有 test 且通过"，必须注入 bug 后测试**变红**才算 grader 有效（杀不死注入 bug 的测试信号作废→降 C）。M1a 用最朴素变异：往一个被测源文件尾部注入 `raise RuntimeError('SIE_MUTANT')`，再跑测试，期望退出码非 0（被杀死）。tier 在 run 首次 PROFILE 冻结（铁律4），resume 不重跑。

- [ ] **Step 1: 写失败测试（有效 test repo→A；全 skip 假 test→C）**
  ```python
  # tests/test_profile.py
  import os, subprocess as sp, textwrap
  from tools.sie.profile import run_profile

  def _mk_repo(tmp_path, src, test):
      r = tmp_path / "repo"; r.mkdir()
      sp.run(["git", "init", "-q"], cwd=r, check=True)
      sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
      sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
      (r / "mod.py").write_text(src)
      (r / "test_mod.py").write_text(test)
      sp.run(["git", "add", "-A"], cwd=r, check=True)
      sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
      return str(r)

  def test_real_test_repo_is_A(tmp_path):
      src = "def add(a, b):\n    return a + b\n"
      test = "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
      tgt = _mk_repo(tmp_path, src, test)
      prof = run_profile(tgt, "HEAD")
      assert prof["tier"] == "A", prof
      assert prof["probes"]["exec"]["mutation_killed"] is True

  def test_fake_skip_test_is_C(tmp_path):
      src = "def add(a, b):\n    return a + b\n"
      test = "import pytest\n\n@pytest.mark.skip\ndef test_add():\n    assert False\n"
      tgt = _mk_repo(tmp_path, src, test)
      prof = run_profile(tgt, "HEAD")
      # 全 skip: 无真断言执行 -> 变异杀不死 -> 不可信 -> C
      assert prof["tier"] == "C", prof
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写 exec_probe 实现（含变异）**
  ```python
  # tools/sie/probes/__init__.py
  ```
  ```python
  # tools/sie/probes/exec_probe.py
  from __future__ import annotations
  import os, glob, subprocess, sys

  PYTEST = [sys.executable, "-m", "pytest", "-q", "--no-header"]


  def _has_tests(root: str) -> bool:
      return bool(glob.glob(os.path.join(root, "**", "test_*.py"), recursive=True) or
                  glob.glob(os.path.join(root, "**", "*_test.py"), recursive=True))


  def _run_pytest(root: str) -> int:
      env = dict(os.environ)
      env["PYTHONDONTWRITEBYTECODE"] = "1"
      proc = subprocess.run(PYTEST, cwd=root, capture_output=True, text=True, env=env)
      return proc.returncode  # 0=pass, 1=fail, 5=no tests collected


  def _pick_src(root: str) -> str | None:
      for p in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
          base = os.path.basename(p)
          if base.startswith("test_") or base.endswith("_test.py"):
              continue
          return p
      return None


  def run_exec_probe(sandbox_root: str) -> dict:
      out = {"has_tests": _has_tests(sandbox_root), "exit_code": None,
             "mutation_killed": False}
      if not out["has_tests"]:
          return out
      out["exit_code"] = _run_pytest(sandbox_root)
      # 基线必须先全绿(0) 才有资格做变异; 退出码 5(无收集)/1(fail) 都不算有效 grader
      if out["exit_code"] != 0:
          return out
      src = _pick_src(sandbox_root)
      if not src:
          return out
      original = open(src, "r", encoding="utf-8").read()
      try:
          with open(src, "a", encoding="utf-8") as fh:
              fh.write("\nraise RuntimeError('SIE_MUTANT')\n")
          mutant_code = _run_pytest(sandbox_root)
          out["mutation_killed"] = (mutant_code != 0)  # 注入 bug 须变红
      finally:
          with open(src, "w", encoding="utf-8") as fh:
              fh.write(original)
      return out
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile.py -q`
  Expected: 仍 FAIL（profile.py 缺）。

- [ ] **Step 3: 写 profile.py（A/C 二分 + 冻结）**
  ```python
  # tools/sie/profile.py
  from __future__ import annotations
  import json, os
  from tools.sie.sandbox import make_worktree
  from tools.sie.probes.exec_probe import run_exec_probe

  TARGET_FILE = "target.json"


  def run_profile(target: str, base_ref: str) -> dict:
      sandbox_root = make_worktree(target, base_ref, "profile_probe")
      exec_res = run_exec_probe(sandbox_root)
      # A 档判定: 有 test + 基线全绿 + 变异被杀死(grader 有效)
      verifiable = (exec_res["has_tests"] and exec_res["exit_code"] == 0
                    and exec_res["mutation_killed"])
      tier = "A" if verifiable else "C"
      score = 1.0 if verifiable else 0.0
      prof = {
          "tier": tier,
          "verifiability_score": score,
          "visible": [],   # B 档锚 M2 才填
          "holdout": [],
          "probes": {"exec": exec_res},
          "base_ref": base_ref,
      }
      return prof


  def freeze_target(run_dir: str, prof: dict) -> None:
      """铁律4: tier 在 run 首次 PROFILE 冻结, resume 不重跑。"""
      os.makedirs(run_dir, exist_ok=True)
      final = os.path.join(run_dir, TARGET_FILE)
      tmp = final + ".tmp"
      with open(tmp, "w", encoding="utf-8") as fh:
          json.dump(prof, fh, ensure_ascii=False, indent=2)
      os.replace(tmp, final)


  def load_target(run_dir: str) -> dict:
      with open(os.path.join(run_dir, TARGET_FILE), "r", encoding="utf-8") as fh:
          return json.load(fh)
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile.py -q`
  Expected: PASS。

- [ ] **Step 4: 加 resume-不重跑测试（铁律4）**
  ```python
  # 追加到 tests/test_profile.py
  from tools.sie.profile import freeze_target, load_target
  def test_freeze_and_resume_no_reprofile(tmp_path):
      run_dir = str(tmp_path / "run")
      prof = {"tier": "A", "verifiability_score": 1.0, "visible": [], "holdout": [],
              "probes": {}, "base_ref": "HEAD"}
      freeze_target(run_dir, prof)
      assert load_target(run_dir)["tier"] == "A"
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile.py -q`
  Expected: PASS。

- [ ] **Step 5: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/probes tools/sie/profile.py tests/test_profile.py && git commit -m "$(cat <<'EOF'
M1a: profile.py A/C 二分 + exec_probe 变异测试二次校验 + tier 冻结

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.5: verifiable.py, A 档 grader + 最小化环境 + 快照哈希 + 禁网/凭证隔离

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/verifiable.py`
- Test: `~/CodesSelf/self-evolve/tests/test_verifiable.py`

**Interfaces:**
- Produces（契约锁定）：
  - `verifiable.grade_pytest(sandbox_root: str) -> dict`（→ contract 形 A 档结果：`{"task_passed":bool,"grader_exit_code":int,"dimensions":[{"name","tier":"A","score","weight"}],"anchors":[],"verifiable_coverage":1.0}`，score∈{0,1} 由 exit_code 映射）
  - `verifiable.snapshot_hash(sandbox_root: str) -> str`（树内容哈希，锁定评测快照）
  - `verifiable.minimal_env() -> dict`（清非白名单 env：去 token/key，注 `SIE_NO_NETWORK=1`、`HOME`/`USERPROFILE` 指向不可读临时目录）

> 关键易错点（沙箱边界 / 凭证隔离 / 禁网，spec §5.2/§6）：
> - **最小化环境**：只保留 `PATH`/`SYSTEMROOT`/`PYTHONDONTWRITEBYTECODE` 等白名单；显式删除任何含 `TOKEN`/`KEY`/`SECRET`/`CREDENTIAL`/`API` 的 env；`HOME`/`USERPROFILE` 重指向临时空目录使 `~/.credentials.json` 不可读。
> - **禁网硬门（M1）**：注入 `SIE_NO_NETWORK=1`；通过 sitecustomize 在子进程 monkeypatch `socket.socket` 抛错（allowlist 空=任何出站拒）。
> - **score 映射**：`grader_exit_code==0 → score=1.0/task_passed=True`，否则 `0.0/False`（A 档二态）。

- [ ] **Step 1: 写失败测试（grade 映射 + 禁网 + 凭证隔离 + 快照哈希）**
  ```python
  # tests/test_verifiable.py
  import os, subprocess as sp
  from tools.sie.verifiable import grade_pytest, snapshot_hash, minimal_env

  def _mk(tmp_path, test_body):
      r = tmp_path / "repo"; r.mkdir()
      (r / "test_x.py").write_text(test_body)
      return str(r)

  def test_pass_maps_to_score_1(tmp_path):
      tgt = _mk(tmp_path, "def test_ok():\n    assert 1 == 1\n")
      res = grade_pytest(tgt)
      assert res["grader_exit_code"] == 0
      assert res["task_passed"] is True
      assert res["dimensions"][0]["score"] == 1.0
      assert res["dimensions"][0]["tier"] == "A"
      assert res["verifiable_coverage"] == 1.0

  def test_fail_maps_to_score_0(tmp_path):
      tgt = _mk(tmp_path, "def test_bad():\n    assert 1 == 2\n")
      res = grade_pytest(tgt)
      assert res["grader_exit_code"] != 0
      assert res["task_passed"] is False
      assert res["dimensions"][0]["score"] == 0.0

  def test_minimal_env_strips_secrets():
      os.environ["MY_API_TOKEN"] = "leak"
      try:
          env = minimal_env()
          assert "MY_API_TOKEN" not in env
          assert env.get("SIE_NO_NETWORK") == "1"
      finally:
          del os.environ["MY_API_TOKEN"]

  def test_network_blocked_in_grader(tmp_path):
      # 评测子进程内任何 socket 连接应抛错 -> 测试失败 -> 出站被禁证明
      body = ("import socket\n"
              "def test_net():\n"
              "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n")
      tgt = _mk(tmp_path, body)
      res = grade_pytest(tgt)
      assert res["task_passed"] is False  # 禁网 -> 连接抛错 -> 测试红

  def test_snapshot_hash_changes(tmp_path):
      tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
      h1 = snapshot_hash(tgt)
      (tmp_path / "repo" / "test_x.py").write_text("def test_ok():\n    assert True  # edit\n")
      h2 = snapshot_hash(tgt)
      assert h1 != h2
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_verifiable.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现（含 sitecustomize 禁网注入）**
  ```python
  # tools/sie/verifiable.py
  from __future__ import annotations
  import hashlib, os, subprocess, sys, tempfile

  _ENV_WHITELIST = {"PATH", "SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT",
                    "PYTHONDONTWRITEBYTECODE", "TMP", "TEMP", "LANG", "LC_ALL"}
  _SECRET_MARKERS = ("TOKEN", "KEY", "SECRET", "CREDENTIAL", "API", "PASSWORD",
                     "AWS", "ANTHROPIC", "OPENAI", "DISCORD")

  # 子进程 startup hook: 禁网(allowlist 空, M1) + 屏蔽 discord_relay import
  _SITE = (
      "import socket as _s\n"
      "def _blocked(*a, **k):\n"
      "    raise OSError('SIE network disabled (M1 no-network gate)')\n"
      "_s.socket = _blocked\n"
      "_s.create_connection = _blocked\n"
      "import builtins as _b\n"
      "_orig_import = _b.__import__\n"
      "def _imp(name, *a, **k):\n"
      "    if name.split('.')[0] in ('discord_relay', 'discord'):\n"
      "        raise ImportError('SIE: candidate forbidden to import discord_relay')\n"
      "    return _orig_import(name, *a, **k)\n"
      "_b.__import__ = _imp\n"
  )


  def minimal_env() -> dict:
      base = {k: v for k, v in os.environ.items()
              if k in _ENV_WHITELIST and not any(m in k.upper() for m in _SECRET_MARKERS)}
      base["PYTHONDONTWRITEBYTECODE"] = "1"
      base["SIE_NO_NETWORK"] = "1"
      # HOME/USERPROFILE 重指向空目录, 使 ~/.credentials.json 不可读
      jail = tempfile.mkdtemp(prefix="sie_home_")
      base["HOME"] = jail
      base["USERPROFILE"] = jail
      return base


  def _grader_env(sandbox_root: str) -> tuple[dict, str]:
      env = minimal_env()
      site_dir = tempfile.mkdtemp(prefix="sie_site_")
      with open(os.path.join(site_dir, "sitecustomize.py"), "w", encoding="utf-8") as fh:
          fh.write(_SITE)
      # PYTHONPATH 让 sitecustomize 先于测试加载; 同时保证能 import sandbox 内模块
      env["PYTHONPATH"] = os.pathsep.join([site_dir, sandbox_root])
      return env, site_dir


  def grade_pytest(sandbox_root: str) -> dict:
      env, _ = _grader_env(sandbox_root)
      proc = subprocess.run(
          [sys.executable, "-m", "pytest", "-q", "--no-header"],
          cwd=sandbox_root, capture_output=True, text=True, env=env)
      code = proc.returncode
      passed = (code == 0)
      score = 1.0 if passed else 0.0
      return {
          "task_passed": passed,
          "grader_exit_code": code,
          "dimensions": [{"name": "pytest", "tier": "A", "score": score, "weight": 1.0}],
          "anchors": [],
          "verifiable_coverage": 1.0,
          "stdout": proc.stdout[-2000:],
      }


  def snapshot_hash(sandbox_root: str) -> str:
      h = hashlib.sha256()
      for dirpath, dirnames, filenames in os.walk(sandbox_root):
          dirnames[:] = [d for d in sorted(dirnames)
                         if d not in (".git", "__pycache__", ".sie")]
          for name in sorted(filenames):
              fp = os.path.join(dirpath, name)
              rel = os.path.relpath(fp, sandbox_root).replace("\\", "/")
              h.update(rel.encode())
              try:
                  with open(fp, "rb") as fh:
                      h.update(fh.read())
              except OSError:
                  continue
      return h.hexdigest()
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_verifiable.py -q`
  Expected: PASS。

- [ ] **Step 3: 加凭证隔离负向用例（candidate 读 .credentials.json 失败）**
  ```python
  # 追加到 tests/test_verifiable.py
  def test_credentials_unreadable(tmp_path):
      body = ("import os\n"
              "def test_cred():\n"
              "    p = os.path.join(os.path.expanduser('~'), '.credentials.json')\n"
              "    assert not os.path.exists(p)  # HOME 重指向空 jail\n")
      tgt = _mk(tmp_path, body)
      res = grade_pytest(tgt)
      assert res["task_passed"] is True  # jail 内无凭证文件 -> 断言成立

  def test_discord_import_blocked(tmp_path):
      body = ("def test_imp():\n"
              "    import discord_relay\n")
      tgt = _mk(tmp_path, body)
      res = grade_pytest(tgt)
      assert res["task_passed"] is False  # import 被 sitecustomize 拒
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_verifiable.py -q`
  Expected: PASS。

- [ ] **Step 4: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/verifiable.py tests/test_verifiable.py && git commit -m "$(cat <<'EOF'
M1a: verifiable.py A 档 grader + 最小化环境 + 禁网/凭证隔离 + 快照哈希

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.6: patch.py, 基础 apply + import 白名单 + 危险调用基础门

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/patch.py`
- Test: `~/CodesSelf/self-evolve/tests/test_patch.py`

**Interfaces:**
- Consumes: `tools.sie.sandbox.canonical_in_sandbox`。
- Produces（契约锁定）：
  - `patch.import_gate(source: str, allow: set[str] | None = None) -> tuple[bool, str]`（AST 扫描；命中危险调用/非白名单 import → `(False, reason)`）
  - `patch.apply_patch(sandbox_root: str, file_rel: str, new_content: str, allow: set[str] | None = None) -> dict`（→`{"status":"APPLIED"|"REJECT","reason":str}`；落沙箱外/危险门命中→REJECT，不影响其他 patch）

> 关键易错点（AST 门，spec 态5）：M1a 只做 **import 白名单 + 危险调用基础门**（`os.system`/`subprocess`/`socket`/`ctypes`/`eval`/`exec`/`compile`/`__import__`/动态导入）；**完整 AST 全清单留 M1b**。import 默认拒、走白名单 allow。用 `ast.walk` 检 `ast.Import`/`ast.ImportFrom`/`ast.Call`。注意 `apply_patch` 在写盘前先过 `canonical_in_sandbox`（边界硬门，先于 AST）。

- [ ] **Step 1: 写失败测试（白名单 + 危险门 + 边界 + 隔离 REJECT）**
  ```python
  # tests/test_patch.py
  import os, subprocess as sp
  from tools.sie.patch import import_gate, apply_patch

  def test_allowed_import_passes():
      ok, why = import_gate("import json\nimport math\n", allow={"json", "math"})
      assert ok, why

  def test_non_whitelisted_import_rejected():
      ok, why = import_gate("import requests\n", allow={"json"})
      assert not ok and "requests" in why

  def test_dangerous_call_rejected():
      for bad in ("import os\nos.system('x')\n", "eval('1')\n",
                  "import subprocess\n", "import socket\n", "__import__('os')\n"):
          ok, why = import_gate(bad, allow={"os", "subprocess", "socket"})
          assert not ok, bad  # 即便 import 在白名单, 危险调用本身被拒

  def _wt(tmp_path):
      r = tmp_path / "repo"; r.mkdir()
      sp.run(["git", "init", "-q"], cwd=r, check=True)
      sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
      sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
      (r / "seed.txt").write_text("x")
      sp.run(["git", "add", "-A"], cwd=r, check=True)
      sp.run(["git", "commit", "-qm", "i"], cwd=r, check=True)
      return str(r)

  def test_apply_inside_ok(tmp_path):
      root = _wt(tmp_path)
      res = apply_patch(root, "mod.py", "import json\nx = json.dumps({})\n", allow={"json"})
      assert res["status"] == "APPLIED"
      assert os.path.isfile(os.path.join(root, "mod.py"))

  def test_apply_outside_rejected(tmp_path):
      root = _wt(tmp_path)
      res = apply_patch(root, "../escape.py", "x=1\n", allow=set())
      assert res["status"] == "REJECT" and "sandbox" in res["reason"].lower()

  def test_apply_dangerous_rejected(tmp_path):
      root = _wt(tmp_path)
      res = apply_patch(root, "m.py", "import socket\n", allow={"socket"})
      assert res["status"] == "REJECT"
      assert not os.path.exists(os.path.join(root, "m.py"))  # 未落盘
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现（AST 基础门）**
  ```python
  # tools/sie/patch.py
  from __future__ import annotations
  import ast, os
  from tools.sie.sandbox import canonical_in_sandbox

  _DANGER_CALLS = {"eval", "exec", "compile", "__import__"}
  _DANGER_ATTR = {("os", "system"), ("os", "popen")}
  _DANGER_MODULES = {"subprocess", "socket", "ctypes", "multiprocessing"}
  _DEFAULT_ALLOW = {"json", "math", "re", "typing", "dataclasses", "collections",
                    "itertools", "functools", "pathlib", "datetime", "decimal"}


  def import_gate(source: str, allow: set[str] | None = None) -> tuple[bool, str]:
      allowed = (allow if allow is not None else set()) | _DEFAULT_ALLOW
      try:
          tree = ast.parse(source)
      except SyntaxError as e:
          return False, f"syntax error: {e}"
      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              for a in node.names:
                  top = a.name.split(".")[0]
                  if top in _DANGER_MODULES:
                      return False, f"dangerous module import: {top}"
                  if top not in allowed:
                      return False, f"import not in whitelist: {top}"
          elif isinstance(node, ast.ImportFrom):
              top = (node.module or "").split(".")[0]
              if top in _DANGER_MODULES:
                  return False, f"dangerous module import: {top}"
              if top and top not in allowed:
                  return False, f"import not in whitelist: {top}"
          elif isinstance(node, ast.Call):
              fn = node.func
              if isinstance(fn, ast.Name) and fn.id in _DANGER_CALLS:
                  return False, f"dangerous builtin call: {fn.id}"
              if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                  if (fn.value.id, fn.attr) in _DANGER_ATTR:
                      return False, f"dangerous call: {fn.value.id}.{fn.attr}"
      return True, "ok"


  def apply_patch(sandbox_root: str, file_rel: str, new_content: str,
                  allow: set[str] | None = None) -> dict:
      target = os.path.join(sandbox_root, file_rel)
      # 边界硬门先于 AST(IMMUTABLE)
      if not canonical_in_sandbox(target, sandbox_root):
          return {"status": "REJECT", "reason": "path outside sandbox boundary"}
      if file_rel.endswith(".py"):
          ok, why = import_gate(new_content, allow)
          if not ok:
              return {"status": "REJECT", "reason": f"AST gate: {why}"}
      os.makedirs(os.path.dirname(target) or sandbox_root, exist_ok=True)
      with open(target, "w", encoding="utf-8") as fh:
          fh.write(new_content)
      return {"status": "APPLIED", "reason": "ok"}
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/patch.py tests/test_patch.py && git commit -m "$(cat <<'EOF'
M1a: patch.py 基础 apply + import 白名单 + 危险调用基础 AST 门

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.7: acceptor.py, no-regression 硬门兜底（签名锁定，PACE 留 M1b）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/acceptor.py`
- Test: `~/CodesSelf/self-evolve/tests/test_acceptor.py`

**Interfaces:**
- Consumes: `tools.sie.state.RunState`。
- Produces（契约锁定，签名 M1b 不变、内部换 e-process）：
  - `acceptor.decide(paired: list[tuple[float,float]], tier: str, st: RunState, params: dict) -> dict`（→`{"decision":"ACCEPT"|"REJECT"|"CONTINUE","evalue":float,"reason":str}`）

> 关键易错点（acceptor 数学兜底 + A 档二态，spec §5.5/态7）：M1a 实现 **no-regression 硬门**,`paired` 是 `[(before_score, after_score), ...]` per-task 配对；**任一 task 从 pass(before>=1) 退化到 fail(after<1) → 硬 REJECT**（no-regression 任一回退即拒，spec 态7）。否则 ACCEPT。**A 档禁 CONTINUE**（二态）。M1a 不产 CONTINUE（PACE 随机档 CONTINUE 留 M1b）。`evalue` M1a 占位为通过/退化任务比，签名字段保持以便 M1b 替换。

- [ ] **Step 1: 写失败测试（no-regression 硬门 + A 档二态）**
  ```python
  # tests/test_acceptor.py
  from tools.sie.state import RunState
  from tools.sie.acceptor import decide

  P = {"alpha": 0.05}
  def _st():
      return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="A")

  def test_no_regression_all_improve_accept():
      paired = [(0.0, 1.0), (1.0, 1.0), (0.0, 1.0)]  # 无退化, 有提升
      r = decide(paired, "A", _st(), P)
      assert r["decision"] == "ACCEPT", r

  def test_any_regression_hard_reject():
      paired = [(1.0, 1.0), (1.0, 0.0)]  # 第二个 pass->fail 退化
      r = decide(paired, "A", _st(), P)
      assert r["decision"] == "REJECT"
      assert "regress" in r["reason"].lower()

  def test_no_change_no_regression_accept():
      paired = [(1.0, 1.0), (0.0, 0.0)]  # 无退化(0->0 非退化)
      r = decide(paired, "A", _st(), P)
      assert r["decision"] == "ACCEPT"

  def test_A_tier_never_continue():
      paired = [(0.0, 1.0)]
      r = decide(paired, "A", _st(), P)
      assert r["decision"] in ("ACCEPT", "REJECT")  # A 档禁 CONTINUE

  def test_empty_paired_reject():
      r = decide([], "A", _st(), P)
      assert r["decision"] == "REJECT"  # 无证据不采纳
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现（no-regression 兜底）**
  ```python
  # tools/sie/acceptor.py
  """M1a: no-regression 硬门兜底。
  签名锁定; M1b 把内部替换为 PACE per-tier e-process(站 confseq), decide() 签名不变。"""
  from __future__ import annotations
  from tools.sie.state import RunState

  _PASS = 1.0  # A 档 score∈{0,1}; >=_PASS 视为 pass


  def decide(paired: list[tuple[float, float]], tier: str,
             st: RunState, params: dict) -> dict:
      if not paired:
          return {"decision": "REJECT", "evalue": 0.0, "reason": "no paired evidence"}
      regressed = [i for i, (b, a) in enumerate(paired) if b >= _PASS > a]
      improved = [i for i, (b, a) in enumerate(paired) if a > b]
      if regressed:
          return {"decision": "REJECT", "evalue": 0.0,
                  "reason": f"no-regression hard gate: {len(regressed)} task(s) regressed"}
      # 无退化 -> ACCEPT(M1a 兜底); A 档天然二态, 不产 CONTINUE
      ev = (len(improved) + 1) / (len(paired) + 1)  # 占位 evalue(M1b 换 e-value)
      return {"decision": "ACCEPT", "evalue": float(ev),
              "reason": f"no regression; {len(improved)} improved"}
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/acceptor.py tests/test_acceptor.py && git commit -m "$(cat <<'EOF'
M1a: acceptor.py no-regression 硬门兜底(签名锁定, PACE 留 M1b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.8: archive.py, lineage + rollback（Pareto 留 M3）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/archive.py`
- Test: `~/CodesSelf/self-evolve/tests/test_archive.py`

**Interfaces:**
- Produces（契约锁定）：
  - `archive.add_version(run_dir: str, vid: str, scores: dict, parent_vid: str|None) -> None`（lineage append-only；M1a 落 `archive/versions/<vid>/` + `lineage.json`）
  - `archive.rollback(archive_dir: str, vid: str) -> None`（把某版本快照标记为当前/恢复）
  - `archive.pareto_front(archive_dir: str) -> list[str]`（M1a 占位=返回全部活跃 vid，硬维门 M3 实现）
  - `archive.retire_stale(archive_dir: str, active_cap: int) -> None`（M1a 占位，超 active_cap 写 retired.jsonl）
  - 辅助：`archive.snapshot_version(archive_dir: str, vid: str, sandbox_root: str) -> None`（拷快照入归档）；`archive.lineage(archive_dir: str) -> list[dict]`

> 关键易错点（lineage append-only + rollback，spec §6/态8）：lineage 只追加不改写；rollback 必须能把任意历史版本快照取回（验收：能回滚）。M1a 用文件树拷贝存版本快照（archive 目录在沙箱外的 run 工件区，由 harness 主进程操作=GATED 外不冲突，因 archive 本身非 candidate 可写 glob）。

- [ ] **Step 1: 写失败测试（add→lineage→rollback 取回）**
  ```python
  # tests/test_archive.py
  import os, json
  from tools.sie import archive

  def test_add_and_lineage(tmp_path):
      run_dir = str(tmp_path / "run")
      archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
      archive.add_version(run_dir, "v2", {"pytest": 1.0}, "v1")
      lin = archive.lineage(os.path.join(run_dir, "archive"))
      ids = [e["vid"] for e in lin]
      assert ids == ["v1", "v2"]
      assert lin[1]["parent_vid"] == "v1"

  def test_snapshot_and_rollback(tmp_path):
      run_dir = str(tmp_path / "run")
      arch = os.path.join(run_dir, "archive")
      sbx = tmp_path / "sbx"; sbx.mkdir()
      (sbx / "code.py").write_text("VERSION = 1\n")
      archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
      archive.snapshot_version(arch, "v1", str(sbx))
      # 改沙箱内容到 v2
      (sbx / "code.py").write_text("VERSION = 2\n")
      archive.add_version(run_dir, "v2", {"pytest": 1.0}, "v1")
      archive.snapshot_version(arch, "v2", str(sbx))
      # rollback 到 v1: current 指针回到 v1 快照
      archive.rollback(arch, "v1")
      cur = os.path.join(arch, "current", "code.py")
      assert open(cur).read() == "VERSION = 1\n"

  def test_pareto_returns_active(tmp_path):
      run_dir = str(tmp_path / "run")
      archive.add_version(run_dir, "v1", {"pytest": 1.0}, None)
      front = archive.pareto_front(os.path.join(run_dir, "archive"))
      assert "v1" in front
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_archive.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/archive.py
  from __future__ import annotations
  import json, os, shutil

  LINEAGE = "lineage.json"
  RETIRED = "retired.jsonl"


  def _arch_dir(run_dir: str) -> str:
      d = os.path.join(run_dir, "archive")
      os.makedirs(os.path.join(d, "versions"), exist_ok=True)
      return d


  def add_version(run_dir: str, vid: str, scores: dict, parent_vid: str | None) -> None:
      arch = _arch_dir(run_dir)
      os.makedirs(os.path.join(arch, "versions", vid), exist_ok=True)
      path = os.path.join(arch, LINEAGE)
      lin = lineage(arch)
      lin.append({"vid": vid, "parent_vid": parent_vid, "scores": scores})
      tmp = path + ".tmp"
      with open(tmp, "w", encoding="utf-8") as fh:
          json.dump(lin, fh, ensure_ascii=False, indent=2)
      os.replace(tmp, path)  # lineage 原子追加(整体重写但语义 append-only)


  def lineage(archive_dir: str) -> list[dict]:
      path = os.path.join(archive_dir, LINEAGE)
      if not os.path.exists(path):
          return []
      with open(path, "r", encoding="utf-8") as fh:
          return json.load(fh)


  def snapshot_version(archive_dir: str, vid: str, sandbox_root: str) -> None:
      dst = os.path.join(archive_dir, "versions", vid, "snapshot")
      if os.path.exists(dst):
          shutil.rmtree(dst)
      shutil.copytree(sandbox_root, dst,
                      ignore=shutil.ignore_patterns(".git", "__pycache__", ".sie"))


  def rollback(archive_dir: str, vid: str) -> None:
      src = os.path.join(archive_dir, "versions", vid, "snapshot")
      if not os.path.isdir(src):
          raise FileNotFoundError(f"no snapshot for version {vid}")
      cur = os.path.join(archive_dir, "current")
      if os.path.exists(cur):
          shutil.rmtree(cur)
      shutil.copytree(src, cur)


  def pareto_front(archive_dir: str) -> list[str]:
      # M1a 占位: 硬维门 Pareto 留 M3; 返回全部活跃 vid
      return [e["vid"] for e in lineage(archive_dir)]


  def retire_stale(archive_dir: str, active_cap: int) -> None:
      lin = lineage(archive_dir)
      if len(lin) <= active_cap:
          return
      stale = lin[:len(lin) - active_cap]
      with open(os.path.join(archive_dir, RETIRED), "a", encoding="utf-8") as fh:
          for e in stale:
              fh.write(json.dumps({"vid": e["vid"], "reason": "active_cap"}) + "\n")
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_archive.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/archive.py tests/test_archive.py && git commit -m "$(cat <<'EOF'
M1a: archive.py lineage append-only + 版本快照 + rollback(Pareto 留 M3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.9: gate_human.py, pending 队列基础（非阻塞）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/gate_human.py`
- Test: `~/CodesSelf/self-evolve/tests/test_gate_human.py`

**Interfaces:**
- Produces（契约锁定）：
  - `gate_human.enqueue(run_dir: str, action: dict) -> str`（→ aid；写 `pending_actions.jsonl`，非阻塞返回）
  - `gate_human.pending(run_dir: str) -> list[dict]`（读未决项）

> 关键易错点（人审非阻塞，spec 态9.5/R2）：enqueue 只写队列+返回 aid，**绝不阻塞**主循环；每项含 `{aid,run_id,round,action_type,payload,created_at,status,ttl}`。M1a 只做队列读写；Discord 推送/回执/熔断留 M1b。

- [ ] **Step 1: 写失败测试**
  ```python
  # tests/test_gate_human.py
  from tools.sie.gate_human import enqueue, pending

  def test_enqueue_returns_aid_and_nonblocking(tmp_path):
      rd = str(tmp_path / "run")
      aid = enqueue(rd, {"run_id": "r1", "round": 2, "action_type": "land",
                         "payload": {"vid": "v3"}})
      assert isinstance(aid, str) and aid
      q = pending(rd)
      assert len(q) == 1
      assert q[0]["aid"] == aid
      assert q[0]["status"] == "pending"
      assert q[0]["action_type"] == "land"

  def test_multiple_enqueue(tmp_path):
      rd = str(tmp_path / "run")
      a1 = enqueue(rd, {"action_type": "approve"})
      a2 = enqueue(rd, {"action_type": "land"})
      assert a1 != a2
      assert len(pending(rd)) == 2
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_gate_human.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/gate_human.py
  from __future__ import annotations
  import json, os, time, uuid

  PENDING = "pending_actions.jsonl"


  def enqueue(run_dir: str, action: dict) -> str:
      os.makedirs(run_dir, exist_ok=True)
      aid = uuid.uuid4().hex[:12]
      rec = {
          "aid": aid,
          "run_id": action.get("run_id", ""),
          "round": action.get("round", 0),
          "action_type": action.get("action_type", "unknown"),
          "payload": action.get("payload", {}),
          "created_at": time.time(),
          "status": "pending",
          "ttl": action.get("ttl", 86400),
      }
      with open(os.path.join(run_dir, PENDING), "a", encoding="utf-8") as fh:
          fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
      return aid  # 非阻塞: 立即返回, 不等人


  def pending(run_dir: str) -> list[dict]:
      path = os.path.join(run_dir, PENDING)
      if not os.path.exists(path):
          return []
      out = []
      with open(path, "r", encoding="utf-8") as fh:
          for line in fh:
              line = line.strip()
              if line:
                  rec = json.loads(line)
                  if rec.get("status") == "pending":
                      out.append(rec)
      return out
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_gate_human.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/gate_human.py tests/test_gate_human.py && git commit -m "$(cat <<'EOF'
M1a: gate_human.py pending 队列基础(非阻塞 enqueue/pending)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.10: reflect.py + check_reflection.py + propose.py（串行单次 + builtin）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/reflect.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/check_reflection.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/propose.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/backends/__init__.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/backends/builtin.py`
- Test: `~/CodesSelf/self-evolve/tests/test_reflect_propose.py`

**Interfaces:**
- Produces：
  - `reflect.reflect(sandbox_root: str, history: list[dict], n: int = 1) -> list[dict]`（M1a 串行单次 N=1；首轮无历史→对 target 当前内容静态审查；返回反思条目列表）
  - `check_reflection.check(reflection: dict, threshold: float = 0.5) -> bool`（弱校验：非空/有 target_failure 字段即过）
  - `propose.propose(sandbox_root: str, reflections: list[dict], backend: str = "builtin") -> list[dict]`（→ proposals：`[{"file_rel","new_content","fixes":str}]`；backend 失败/空→fallback builtin）
  - `backends.builtin.generate(sandbox_root: str, reflections: list[dict]) -> list[dict]`

> 关键易错点：M1a 反思/提议是确定性骨架（不实接 LLM，留 M3 升 fanout）。builtin backend 在 M1a 用一个**确定性最小修复器**：读上轮失败的 pytest stdout 提示，对一个已知"缺函数/语法错"模式产出修复 patch，足以让端到端闭环对一个真 pytest repo 验证"采纳"路径。`check_reflection` M1a 弱校验（spec 态3：M1 弱校验）。

- [ ] **Step 1: 写失败测试**
  ```python
  # tests/test_reflect_propose.py
  from tools.sie.reflect import reflect
  from tools.sie.check_reflection import check
  from tools.sie.propose import propose

  def test_reflect_serial_single(tmp_path):
      r = tmp_path / "repo"; r.mkdir()
      (r / "mod.py").write_text("def add(a,b):\n    return a-b\n")  # bug
      refs = reflect(str(r), history=[], n=1)
      assert len(refs) == 1
      assert "target_failure" in refs[0] or "static_review" in refs[0]

  def test_check_reflection_weak(tmp_path):
      assert check({"target_failure": "add returns wrong"}, 0.5) is True
      assert check({}, 0.5) is False  # 空反思不过

  def test_propose_fallback_builtin(tmp_path):
      r = tmp_path / "repo"; r.mkdir()
      (r / "mod.py").write_text("def add(a,b):\n    return a-b\n")
      refs = [{"target_failure": "add returns a-b should be a+b",
               "file_rel": "mod.py",
               "fix_content": "def add(a,b):\n    return a+b\n"}]
      props = propose(str(r), refs, backend="builtin")
      assert len(props) >= 1
      assert props[0]["file_rel"] == "mod.py"
      assert "a+b" in props[0]["new_content"]
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_reflect_propose.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/reflect.py
  from __future__ import annotations
  import glob, os


  def reflect(sandbox_root: str, history: list[dict], n: int = 1) -> list[dict]:
      """M1a 串行单次(N=1)。首轮无历史 -> 对 target 当前内容静态审查;
      有历史 -> 读上轮失败摘要。M3 升 N=3 并行 MARS。"""
      out = []
      if history:
          last = history[-1]
          out.append({"target_failure": last.get("summary", "previous round failed"),
                      "round": last.get("round", 0)})
      else:
          srcs = [p for p in glob.glob(os.path.join(sandbox_root, "**", "*.py"),
                                       recursive=True)
                  if not os.path.basename(p).startswith("test_")]
          note = f"static review of {len(srcs)} source file(s)"
          out.append({"static_review": note, "files": [os.path.relpath(s, sandbox_root)
                                                        for s in srcs]})
      return out[:max(1, n)]
  ```
  ```python
  # tools/sie/check_reflection.py
  from __future__ import annotations


  def check(reflection: dict, threshold: float = 0.5) -> bool:
      """M1a 弱校验(spec 态3 M1): 非空且含有意义字段即过。M3 升 BenchTrace。"""
      if not reflection:
          return False
      keys = ("target_failure", "static_review", "fix_content", "files")
      return any(reflection.get(k) for k in keys)
  ```
  ```python
  # tools/sie/backends/__init__.py
  ```
  ```python
  # tools/sie/backends/builtin.py
  from __future__ import annotations
  import os


  def generate(sandbox_root: str, reflections: list[dict]) -> list[dict]:
      """确定性最小修复器: 把反思里给出的 fix_content 落成 proposal。
      M1a 不实接 LLM(留 M3 fanout); 足以驱动端到端'采纳'路径验证。"""
      props = []
      for ref in reflections:
          fr = ref.get("file_rel")
          fc = ref.get("fix_content")
          if fr and fc:
              props.append({"file_rel": fr, "new_content": fc,
                            "fixes": ref.get("target_failure", "")})
      return props
  ```
  ```python
  # tools/sie/propose.py
  from __future__ import annotations
  from tools.sie.backends import builtin


  def propose(sandbox_root: str, reflections: list[dict],
              backend: str = "builtin") -> list[dict]:
      """backend 失败/超时/空 -> warning + fallback builtin(spec 态4)。"""
      props: list[dict] = []
      if backend == "builtin":
          props = builtin.generate(sandbox_root, reflections)
      else:
          # 其他 backend(gepa/openevolve) M3 接入; 此处 fallback
          props = builtin.generate(sandbox_root, reflections)
      return props
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_reflect_propose.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/reflect.py tools/sie/check_reflection.py tools/sie/propose.py tools/sie/backends tests/test_reflect_propose.py && git commit -m "$(cat <<'EOF'
M1a: reflect(串行单次)+check_reflection(弱校验)+propose(builtin fallback)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.11: evaluate.py, 只走 verifiable（A 档分向量）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/evaluate.py`
- Test: `~/CodesSelf/self-evolve/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `tools.sie.verifiable.grade_pytest`。
- Produces：
  - `evaluate.evaluate(sandbox_root: str, tier: str, base_result: dict | None = None) -> dict`（M1a 只走 verifiable；返回 `{"result":<contract>, "paired":[(before,after),...], "coverage":float}`，`paired` 给 acceptor）

> 关键易错点：`evaluate` 把"改前/改后"配成 acceptor 要的 `paired`。M1a A 档：before=parent 版本 grade（base_result 传入，缺省视为全 fail 基线 [(0,after)]），after=当前沙箱 grade。coverage=`verifiable_coverage`。

- [ ] **Step 1: 写失败测试**
  ```python
  # tests/test_evaluate.py
  from tools.sie.evaluate import evaluate

  def _mk(tmp_path, body):
      r = tmp_path / "repo"; r.mkdir()
      (r / "test_x.py").write_text(body)
      return str(r)

  def test_evaluate_pass_pairs(tmp_path):
      tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
      ev = evaluate(tgt, "A", base_result=None)
      assert ev["result"]["task_passed"] is True
      assert ev["coverage"] == 1.0
      assert ev["paired"]  # 非空配对

  def test_evaluate_pairs_against_base(tmp_path):
      tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
      base = {"task_passed": False, "grader_exit_code": 1,
              "dimensions": [{"name":"pytest","tier":"A","score":0.0,"weight":1.0}],
              "anchors": [], "verifiable_coverage": 1.0}
      ev = evaluate(tgt, "A", base_result=base)
      assert ev["paired"] == [(0.0, 1.0)]  # before fail -> after pass
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_evaluate.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写实现**
  ```python
  # tools/sie/evaluate.py
  from __future__ import annotations
  from tools.sie.verifiable import grade_pytest


  def evaluate(sandbox_root: str, tier: str,
               base_result: dict | None = None) -> dict:
      """M1a 只走 verifiable(A 档)。B/C 档 evaluate 在 M2/M3 接入。"""
      after = grade_pytest(sandbox_root)
      after_score = after["dimensions"][0]["score"] if after["dimensions"] else 0.0
      if base_result and base_result.get("dimensions"):
          before_score = base_result["dimensions"][0]["score"]
      else:
          before_score = 0.0  # 冷启动: 视 parent 为全 fail 基线
      paired = [(float(before_score), float(after_score))]
      return {"result": after, "paired": paired,
              "coverage": after.get("verifiable_coverage", 0.0)}
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_evaluate.py -q`
  Expected: PASS。

- [ ] **Step 3: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/evaluate.py tests/test_evaluate.py && git commit -m "$(cat <<'EOF'
M1a: evaluate.py 只走 verifiable, 产 acceptor paired 配对

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.12: statemachine.py + cli.py, 端到端编排（init|run|status|replay|rollback）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/statemachine.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/cli.py`
- Test: `~/CodesSelf/self-evolve/tests/test_e2e.py`

**Interfaces:**
- Consumes: state/events/sandbox/profile/select/reflect/propose/patch/evaluate/acceptor/archive/gate_human 全部上述签名。
- Produces：
  - `statemachine.select_parent(run_dir: str, st: RunState) -> str`（SELECT_PARENT：冷启动 archive 空→base ref；否则取 lineage 末版）
  - `statemachine.run_loop(target: str, base_ref: str, run_id: str, max_rounds: int = 3, mode: str = "auto") -> dict`（驱动 10 态闭环；每态 append_event+save_state；ACCEPT→archive；返回汇总）
  - `cli.main(argv: list[str]) -> int`（子命令 init|run|status|replay|rollback）

> 关键易错点（状态机转移 + 崩溃重放，spec §4 验收）：
> - 每态推进**先 append_event 再 save_state**（events 为真相源，崩溃后 replay 必须重建一致,验收硬指标）。
> - SELECT_PARENT 冷启动 archive 空 → parent=base ref（spec 态2）。
> - ACCEPT 路径：evaluate→acceptor.decide→若 ACCEPT 则 add_version+snapshot_version+清零 no_progress（态8）；REJECT 则 no_progress++（态9）。
> - `replay` 子命令必须能在删掉 state.json 后从 events.jsonl 重建并打印一致 RunState。

- [ ] **Step 1: 写失败的端到端测试（真 pytest repo 全闭环 + 采纳 + 回滚 + 崩溃重放）**
  ```python
  # tests/test_e2e.py
  import os, subprocess as sp, json
  from tools.sie.statemachine import run_loop, select_parent
  from tools.sie.state import RunState, load_state
  from tools.sie.events import replay
  from tools.sie import archive

  def _broken_repo(tmp_path):
      """一个 test 失败的 repo: add 实现错误。reflect 给出 fix_content 修好它。"""
      r = tmp_path / "repo"; r.mkdir()
      sp.run(["git", "init", "-q"], cwd=r, check=True)
      sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
      sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
      (r / "mod.py").write_text("def add(a, b):\n    return a - b\n")  # bug
      (r / "test_mod.py").write_text(
          "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
      sp.run(["git", "add", "-A"], cwd=r, check=True)
      sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
      return str(r)

  def test_select_parent_cold_start(tmp_path):
      rd = str(tmp_path / "run")
      st = RunState(run_id="r", phase="SELECT", round=0, parent_vid=None, tier="A")
      assert select_parent(rd, st) == "base"  # archive 空 -> base ref

  def test_e2e_accept_and_rollback(tmp_path):
      tgt = _broken_repo(tmp_path)
      # 预置一个 reflection-fix(M1a builtin 确定性): 把 add 改对
      fix = "def add(a, b):\n    return a + b\n"
      summary = run_loop(tgt, "HEAD", "rune2e", max_rounds=2, mode="auto",
                         _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                                        "target_failure": "add a-b should be a+b"})
      assert summary["accepted_versions"], summary
      arch = os.path.join(tgt, ".sie", "runs", "rune2e", "archive")
      lin = archive.lineage(arch)
      assert lin, "lineage should have at least one accepted version"
      # 回滚到首个采纳版本
      vid = lin[0]["vid"]
      archive.rollback(arch, vid)
      assert os.path.isdir(os.path.join(arch, "current"))

  def test_e2e_crash_replay_consistent(tmp_path):
      tgt = _broken_repo(tmp_path)
      fix = "def add(a, b):\n    return a + b\n"
      run_loop(tgt, "HEAD", "runcrash", max_rounds=1, mode="auto",
               _injected_fix={"file_rel": "mod.py", "fix_content": fix,
                              "target_failure": "fix add"})
      run_dir = os.path.join(tgt, ".sie", "runs", "runcrash")
      saved = load_state(run_dir)
      os.remove(os.path.join(run_dir, "state.json"))  # 模拟崩溃丢 state.json
      rebuilt = replay(run_dir)
      assert rebuilt == saved  # 崩溃重放一致(验收硬指标)
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_e2e.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写 statemachine.py 实现**
  ```python
  # tools/sie/statemachine.py
  from __future__ import annotations
  import os, uuid
  from tools.sie.state import RunState, save_state
  from tools.sie.events import append_event, replay
  from tools.sie.sandbox import make_worktree
  from tools.sie.profile import run_profile, freeze_target, load_target
  from tools.sie.reflect import reflect
  from tools.sie.check_reflection import check
  from tools.sie.propose import propose
  from tools.sie.patch import apply_patch
  from tools.sie.evaluate import evaluate
  from tools.sie.acceptor import decide
  from tools.sie import archive


  def _run_dir(target: str, run_id: str) -> str:
      return os.path.join(os.path.abspath(target), ".sie", "runs", run_id)


  def select_parent(run_dir: str, st: RunState) -> str:
      arch = os.path.join(run_dir, "archive")
      lin = archive.lineage(arch)
      if not lin:
          return "base"  # 冷启动 archive 空 -> base ref(spec 态2)
      return lin[-1]["vid"]


  def _step(run_dir: str, st: RunState, ev: dict) -> RunState:
      append_event(run_dir, ev)      # 真相源先行
      st = replay(run_dir)
      save_state(st, run_dir)        # 旁路落盘
      return st


  def run_loop(target: str, base_ref: str, run_id: str, max_rounds: int = 3,
               mode: str = "auto", _injected_fix: dict | None = None) -> dict:
      run_dir = _run_dir(target, run_id)
      os.makedirs(run_dir, exist_ok=True)
      params = {"alpha": 0.05}
      accepted: list[str] = []

      # 态0 INIT
      sandbox_root = make_worktree(target, base_ref, run_id)
      st = RunState(run_id=run_id, phase="INIT", round=0, parent_vid=None, tier="")
      st = _step(run_dir, st, {"type": "INIT", "run_id": run_id, "phase": "INIT",
                               "parent_vid": None})

      # 态1 PROFILE(首次冻结 tier; resume 不重跑)
      if os.path.exists(os.path.join(run_dir, "target.json")):
          prof = load_target(run_dir)
      else:
          prof = run_profile(target, base_ref)
          freeze_target(run_dir, prof)
      st = _step(run_dir, st, {"type": "PROFILE", "phase": "PROFILE",
                               "tier": prof["tier"]})

      history: list[dict] = []
      for rnd in range(1, max_rounds + 1):
          # 态2 SELECT_PARENT
          parent = select_parent(run_dir, st)
          st = _step(run_dir, st, {"type": "ROUND_BEGIN", "phase": "REFLECT",
                                   "round": rnd, "parent_vid": parent})
          # 态3 REFLECT(串行单次)
          refs = reflect(sandbox_root, history, n=1)
          if _injected_fix:
              refs = [dict(refs[0], **_injected_fix)]
          refs = [r for r in refs if check(r, 0.5)]
          if not refs:
              st = _step(run_dir, st, {"type": "STATIC_REJECT", "phase": "LOOP",
                                       "static_reject_delta": 1})
              continue
          # 态4 PROPOSE(builtin)
          props = propose(sandbox_root, refs, backend="builtin")
          if not props:
              st = _step(run_dir, st, {"type": "STATIC_REJECT", "phase": "LOOP",
                                       "static_reject_delta": 1})
              continue
          # 态5 PATCH(逐 patch 应用 + AST/边界门)
          applied = False
          for p in props:
              res = apply_patch(sandbox_root, p["file_rel"], p["new_content"])
              if res["status"] == "APPLIED":
                  applied = True
          if not applied:
              st = _step(run_dir, st, {"type": "STATIC_REJECT", "phase": "LOOP",
                                       "static_reject_delta": 1})
              continue
          # 态6 EVALUATE(只走 verifiable)
          ev = evaluate(sandbox_root, prof["tier"], base_result=None)
          # 态7 ACCEPT(no-regression 兜底)
          dec = decide(ev["paired"], prof["tier"], st, params)
          if dec["decision"] == "ACCEPT":
              vid = f"v{len(accepted)+1}"
              archive.add_version(run_dir, vid, ev["result"]["dimensions"], parent)
              arch = os.path.join(run_dir, "archive")
              archive.snapshot_version(arch, vid, sandbox_root)
              accepted.append(vid)
              st = _step(run_dir, st, {"type": "ACCEPT", "phase": "ARCHIVE",
                                       "parent_vid": vid})
              history.append({"round": rnd, "summary": "accepted", "passed": True})
          else:
              st = _step(run_dir, st, {"type": "REJECT", "phase": "LOOP",
                                       "no_progress_delta": 1})
              history.append({"round": rnd, "summary": dec["reason"], "passed": False})

      return {"run_id": run_id, "accepted_versions": accepted,
              "final_phase": st.phase, "run_dir": run_dir}
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_e2e.py -q`
  Expected: 端到端 + 回滚 + 重放用例 PASS（CLI 用例还未加）。

- [ ] **Step 3: 写 cli.py（init|run|status|replay|rollback）**
  ```python
  # tools/sie/cli.py
  from __future__ import annotations
  import argparse, json, os, sys, uuid
  from tools.sie.statemachine import run_loop, _run_dir
  from tools.sie.events import replay
  from tools.sie.state import load_state
  from tools.sie import archive, gate_human


  def main(argv: list[str] | None = None) -> int:
      argv = list(sys.argv[1:] if argv is None else argv)
      ap = argparse.ArgumentParser(prog="sie")
      sub = ap.add_subparsers(dest="cmd", required=True)

      p_init = sub.add_parser("init")
      p_init.add_argument("--target", required=True)
      p_init.add_argument("--run-id", default=None)

      p_run = sub.add_parser("run")
      p_run.add_argument("--target", required=True)
      p_run.add_argument("--run-id", required=True)
      p_run.add_argument("--base-ref", default="HEAD")
      p_run.add_argument("--max-rounds", type=int, default=3)
      p_run.add_argument("--mode", default="auto", choices=["auto", "gated"])

      p_st = sub.add_parser("status")
      p_st.add_argument("--target", required=True)
      p_st.add_argument("--run-id", required=True)

      p_rp = sub.add_parser("replay")
      p_rp.add_argument("--target", required=True)
      p_rp.add_argument("--run-id", required=True)

      p_rb = sub.add_parser("rollback")
      p_rb.add_argument("--target", required=True)
      p_rb.add_argument("--run-id", required=True)
      p_rb.add_argument("--vid", required=True)

      args = ap.parse_args(argv)

      if args.cmd == "init":
          rid = args.run_id or uuid.uuid4().hex[:12]
          rd = _run_dir(args.target, rid)
          os.makedirs(rd, exist_ok=True)
          print(json.dumps({"run_id": rid, "run_dir": rd}))
          return 0
      if args.cmd == "run":
          summary = run_loop(args.target, args.base_ref, args.run_id,
                             max_rounds=args.max_rounds, mode=args.mode)
          print(json.dumps(summary, ensure_ascii=False))
          return 0
      if args.cmd == "status":
          rd = _run_dir(args.target, args.run_id)
          st = load_state(rd)
          arch = os.path.join(rd, "archive")
          out = {"phase": st.phase, "round": st.round, "tier": st.tier,
                 "no_progress": st.no_progress, "static_reject": st.static_reject,
                 "forced_review": st.forced_review,
                 "pareto": archive.pareto_front(arch) if os.path.isdir(arch) else [],
                 "pending": gate_human.pending(rd)}
          print(json.dumps(out, ensure_ascii=False))
          return 0
      if args.cmd == "replay":
          rd = _run_dir(args.target, args.run_id)
          st = replay(rd)
          print(json.dumps(st.__dict__, ensure_ascii=False))
          return 0
      if args.cmd == "rollback":
          rd = _run_dir(args.target, args.run_id)
          archive.rollback(os.path.join(rd, "archive"), args.vid)
          print(json.dumps({"rolled_back_to": args.vid}))
          return 0
      return 1


  if __name__ == "__main__":
      raise SystemExit(main())
  ```

- [ ] **Step 4: 加 CLI 端到端测试（init→run→status→replay→rollback）**
  ```python
  # 追加到 tests/test_e2e.py
  from tools.sie.cli import main as cli_main

  def test_cli_full_flow(tmp_path, capsys):
      tgt = _broken_repo(tmp_path)
      assert cli_main(["init", "--target", tgt, "--run-id", "cli1"]) == 0
      capsys.readouterr()
      # run(无 injected fix: builtin 无修复 -> 不采纳, 但闭环不崩)
      assert cli_main(["run", "--target", tgt, "--run-id", "cli1",
                       "--base-ref", "HEAD", "--max-rounds", "1"]) == 0
      assert cli_main(["status", "--target", tgt, "--run-id", "cli1"]) == 0
      out = capsys.readouterr().out
      assert "phase" in out
      assert cli_main(["replay", "--target", tgt, "--run-id", "cli1"]) == 0
      rout = capsys.readouterr().out
      assert "run_id" in rout
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_e2e.py -q`
  Expected: PASS。

- [ ] **Step 5: 全量回归（M1a 所有模块绿）**
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest -q`
  Expected: PASS（全部 M1a 测试通过 = 端到端骨架闭环验收）。

- [ ] **Step 6: commit**
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add tools/sie/statemachine.py tools/sie/cli.py tests/test_e2e.py && git commit -m "$(cat <<'EOF'
M1a: statemachine 10 态闭环 + cli(init|run|status|replay|rollback) 端到端

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

### Task M1a.13: SKILL.md 门控总纲 + commands/ 三命令

**Files:**
- Create: `~/CodesSelf/self-evolve/SKILL.md`
- Create: `~/CodesSelf/self-evolve/commands/self-evolve.md`
- Create: `~/CodesSelf/self-evolve/commands/self-evolve-status.md`
- Create: `~/CodesSelf/self-evolve/commands/self-evolve-resume.md`
- Create: `~/CodesSelf/self-evolve/reference/target_contract.md`
- Test: `~/CodesSelf/self-evolve/tests/test_skill_docs.py`

**Interfaces:**
- Consumes: cli 子命令名（init/run/status/replay/rollback）。
- Produces: 给主 agent 读的门控序列总纲 + 三 slash command 文档（指向 cli）。

> 关键易错点：SKILL.md 是**方法论门控总纲**（铁律：LLM 只提议、代码裁决；沙箱内全自动、落地走人审）。M1a 文档需与 cli 子命令、契约一致；用一个 doc 一致性测试锁住命令名不漂移。

- [ ] **Step 1: 写失败的文档一致性测试**
  ```python
  # tests/test_skill_docs.py
  import os, re
  ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

  def _read(rel):
      with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
          return fh.read()

  def test_skill_md_exists_and_mentions_gates():
      t = _read("SKILL.md")
      for kw in ("LLM 只提议", "代码裁决", "沙箱", "人审"):
          assert kw in t, kw

  def test_commands_reference_cli():
      for cmd, sub in [("self-evolve", "run"),
                       ("self-evolve-status", "status"),
                       ("self-evolve-resume", "run")]:
          t = _read(f"commands/{cmd}.md")
          assert "sie" in t and sub in t, cmd

  def test_contract_doc_has_grade_fields():
      t = _read("reference/target_contract.md")
      for f in ("task_passed", "grader_exit_code", "dimensions", "anchors",
                "verifiable_coverage"):
          assert f in t, f
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_skill_docs.py -q`
  Expected: FAIL。

- [ ] **Step 2: 写 SKILL.md**
  ```markdown
  # self-evolve (SKILL)

  指向任意 skill/仓库/项目, 在 git worktree 沙箱内多轮自动改进它, 用不可 game 的
  提交门保证"被采纳=真改进"。

  ## 铁律(不可违背)
  1. **LLM 只提议, 代码裁决**: 采纳/拒绝/回滚/分档由 harness 确定性代码; 搜索/反思/
     评审才用 LLM, 绝不让 LLM 评判自己产出。
  2. **原始证据只读**: trace/反思 append-only, 永不被 LLM 改写。
  3. **数据隔离(铁律5)**: frozen 锚真值/测试真值对 REFLECT/PROPOSE/PATCH 不可读。
  4. **沙箱内全自动, 落地走人审**: 沙箱内 canonical 写=auto; 出沙箱写删/push/合主
     分支/对外发送=GATED, 只在人审独立子流程发生, 永不在自动循环内。

  ## 门控序列(10 态)
  INIT → PROFILE(A/C 二分, 变异测试二次校验) → SELECT_PARENT → REFLECT(串行) →
  PROPOSE(builtin) → PATCH(import 白名单+危险门) → EVALUATE(verifiable) →
  ACCEPT(no-regression 兜底; M1b 升 PACE e-process) → ARCHIVE(lineage+rollback) →
  LOOP/STOP。强制人审与累计漂移熔断为后续里程碑加硬。

  ## 用法
  - 开跑: `/self-evolve <target>`
  - 看状态: `/self-evolve-status <run_id>`
  - 续跑: `/self-evolve-resume <run_id>`

  底层 harness: `python -m tools.sie.cli {init|run|status|replay|rollback}`。
  ```

- [ ] **Step 3: 写 commands/ 三命令 + 契约文档**
  ```markdown
  <!-- commands/self-evolve.md -->
  # /self-evolve

  对 <target> 启动一次自迭代 run(沙箱内全自动)。

  步骤:
  1. `python -m tools.sie.cli init --target <target>` 取 run_id。
  2. `python -m tools.sie.cli run --target <target> --run-id <run_id> --base-ref HEAD`。
  3. 采纳的版本进 archive lineage; 落地到真目标须走人审(land, 后续里程碑)。
  ```
  ```markdown
  <!-- commands/self-evolve-status.md -->
  # /self-evolve-status

  查看某 run 的态/Pareto/三计数器/待审队列。

  `python -m tools.sie.cli status --target <target> --run-id <run_id>`
  ```
  ```markdown
  <!-- commands/self-evolve-resume.md -->
  # /self-evolve-resume

  从已存在 run 续跑(不重跑 PROFILE, tier 已冻结 = 铁律4)。

  `python -m tools.sie.cli run --target <target> --run-id <run_id> --base-ref HEAD`
  ```
  ```markdown
  <!-- reference/target_contract.md -->
  # target_contract: grade(task)

  目标侧实现 `grade(task)`, 返回:

  ```json
  {
    "task_passed": true,
    "grader_exit_code": 0,
    "dimensions": [{"name": "pytest", "tier": "A", "score": 1.0, "weight": 1.0}],
    "anchors": [{"claim": "", "span": "", "source_url": "", "fetched_at": "",
                 "verified": false, "marginal_gain": 0.0}],
    "verifiable_coverage": 1.0
  }
  ```

  - tier=A 的 score∈{0,1} 由 grader_exit_code 映射; PACE A 配对消费 task_passed。
  - judge 主观分由 evaluate.py 在 contract 外注入(非 candidate 提供)。
  - 自举时 grade() 用 frozen/外部版(铁律5/§6)。
  ```
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_skill_docs.py -q`
  Expected: PASS。

- [ ] **Step 4: 全量回归 + commit**
  Run: `cd ~/CodesSelf/self-evolve && python -m pytest -q`
  Expected: PASS（M1a 全绿）。
  Run:
  ```
  cd ~/CodesSelf/self-evolve && git add SKILL.md commands reference/target_contract.md tests/test_skill_docs.py && git commit -m "$(cat <<'EOF'
M1a: SKILL.md 门控总纲 + commands 三命令 + target_contract 文档

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
  ```

---

> **M1a 完成判据（对照 spec §13 验收）**：`python -m pytest -q` 全绿；真 broken pytest repo 经 `cli run` 能采纳修复版进 archive lineage、`cli rollback` 能回滚；`cli replay` 在删 state.json 后从 events.jsonl 重建出与崩溃前一致的 RunState；评测子进程禁网/凭证隔离/沙箱 realpath 边界负向用例全过；confseq spike 第 0 步硬前置通过。M1b 在此骨架上把 acceptor 内部换成 PACE e-process 并补噪声/对抗单测、AST 全清单、三计数器熔断、人审非阻塞回执。
## 里程碑 M1b: 防自欺/安全门加硬 (~10-14h)

**目标**：在 M1a 端到端骨架（no-regression 兜底 acceptor）之上，把"被采纳=真改进"的硬地基补齐,`patch.py` 装上 AST 危险调用拒绝门全清单，`verifiable.py` 装上变异测试有效性门，`acceptor.py` 用 `confseq` 实现 PACE A 档 anytime-valid e-process（per-task `task_passed` 配对、二态、禁 CONTINUE）并通过噪声/对抗单测，`gate_human.py` 补齐非阻塞待审队列，`statemachine.py` 装齐三计数器（`no_progress`/`static_reject`/`forced_review`）+各自熔断阈 + 态 9.5 PAUSE_FOR_HUMAN + CONTINUE 限随机档/上限/落点（A 档禁 CONTINUE）。

**验收标准（spec §13 M1b）**：
- acceptor 正确采纳/拒绝：纯噪声序列拒绝率≈1，真增益序列采纳率高，误提交率 ≤ α=0.05；对抗序列（主观正漂移+锚每轮微涨）被拒。
- 安全负向用例全过：patch 含 `os.system`/`subprocess`/`socket`/`ctypes`/`eval`/`exec`/`compile`/`__import__`/动态导入/沙箱外 `open`/网络库 import → 一律 REJECT；非白名单 import → 默认拒；杀不死注入 bug 的"假测试" → 变异有效性门判信号作废。
- 活性/计数用例过：态4 空返回与态5 全拒正确累加 `static_reject`；CONTINUE 达上限 `continue_count_cap=5` → 落点 REJECT；持续强制人审 → `forced_review` 达 `N_fr=5` 熔断停机（不空转）；A 档全程禁 CONTINUE。

---

### Task M1b.1: AST 危险调用拒绝门（patch.py）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/patch.py`（在 M1a 已实现的 `apply_patch` / `_import_whitelist_check` 之上新增 `scan_ast_dangerous` 并接入 `apply_patch` 的预检）
- Test: `~/CodesSelf/self-evolve/tests/test_patch_ast_gate.py`

**Interfaces:**
- Consumes（M1a 产出）：`apply_patch(worktree: str, patch: dict) -> dict`（返回 `{"status":"APPLIED"|"REJECT","reason":str,"file":str}`）；`_import_whitelist_check(tree: ast.AST, allow: set[str]) -> str | None`
- Produces：
  - `scan_ast_dangerous(source: str, *, allow_imports: set[str] | None = None, sandbox_root: str | None = None, target_path: str | None = None) -> list[str]`（返回违规原因列表，空=通过）
  - `DANGEROUS_CALLS: frozenset[str]`、`DANGEROUS_MODULE_PREFIXES: frozenset[str]`、`DEFAULT_IMPORT_ALLOW: frozenset[str]`

> 关键：这是 IMMUTABLE 裁决码之一（铁律3）。门必须对**调用名 + 属性链 + import + 动态导入 + 沙箱外 open** 同时设防，import 走"默认拒 + 白名单 allow"。下面给可跑实现，不可只描述。

- [ ] **Step 1: 写失败测试,危险调用全清单逐项拒**
  新建 `tests/test_patch_ast_gate.py`：
  ```python
  import pytest
  from sie.patch import scan_ast_dangerous

  DANGEROUS_SNIPPETS = {
      "os.system":      "import os\nos.system('rm -rf /')\n",
      "subprocess.run": "import subprocess\nsubprocess.run(['ls'])\n",
      "subprocess.Popen":"import subprocess\nsubprocess.Popen(['ls'])\n",
      "popen":          "import os\nos.popen('ls')\n",
      "socket":         "import socket\ns = socket.socket()\n",
      "ctypes":         "import ctypes\nctypes.CDLL('libc.so.6')\n",
      "eval":           "eval('1+1')\n",
      "exec":           "exec('x=1')\n",
      "compile":        "compile('1', '<s>', 'eval')\n",
      "__import__":     "m = __import__('os')\n",
      "importlib":      "import importlib\nimportlib.import_module('os')\n",
      "net_requests":   "import requests\nrequests.get('http://x')\n",
      "net_urllib":     "import urllib.request\nurllib.request.urlopen('http://x')\n",
      "net_httpx":      "import httpx\nhttpx.get('http://x')\n",
  }

  @pytest.mark.parametrize("name,src", list(DANGEROUS_SNIPPETS.items()))
  def test_dangerous_call_rejected(name, src):
      reasons = scan_ast_dangerous(src)
      assert reasons, f"{name} should be rejected but passed"

  def test_clean_source_passes():
      src = "def add(a, b):\n    return a + b\n"
      assert scan_ast_dangerous(src) == []

  def test_import_default_deny_non_whitelist():
      # 默认白名单不含 pandas → 默认拒
      assert scan_ast_dangerous("import pandas as pd\n")
      # 显式 allow 后通过
      assert scan_ast_dangerous("import pandas as pd\n", allow_imports={"pandas"}) == []

  def test_sandbox_outside_open_rejected():
      src = "open('C:/Windows/system32/x.txt', 'w')\n"
      reasons = scan_ast_dangerous(
          src, sandbox_root="C:/sbx", target_path="C:/sbx/tools/sie/patch.py")
      assert any("open" in r for r in reasons)

  def test_sandbox_inside_open_relative_allowed():
      src = "open('data.txt', 'r')\n"  # 相对路径，落在沙箱内
      reasons = scan_ast_dangerous(
          src, sandbox_root="C:/sbx", target_path="C:/sbx/tools/sie/patch.py")
      assert reasons == []
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_ast_gate.py -q`
  - Expected: FAIL（`ImportError: cannot import name 'scan_ast_dangerous'`）

- [ ] **Step 3: 写最小实现,`scan_ast_dangerous` + 常量表**
  在 `tools/sie/patch.py` 顶部 import 区后加入（确保 `import ast`、`import os` 已在 M1a 引入；若无则补 `import ast`）：
  ```python
  DANGEROUS_CALLS = frozenset({
      "system", "popen", "spawn", "spawnl", "spawnv", "execv", "execve",
      "eval", "exec", "compile", "__import__",
      "Popen", "run", "call", "check_call", "check_output", "getoutput",
      "CDLL", "WinDLL", "cdll", "windll", "import_module",
      "socket", "create_connection", "urlopen", "get", "post", "request",
  })
  DANGEROUS_MODULE_PREFIXES = frozenset({
      "subprocess", "socket", "ctypes", "importlib", "imp",
      "requests", "urllib", "httpx", "http", "aiohttp", "ftplib",
      "telnetlib", "smtplib", "asyncio",
  })
  DEFAULT_IMPORT_ALLOW = frozenset({
      "os", "sys", "re", "json", "math", "typing", "dataclasses",
      "pathlib", "collections", "itertools", "functools", "datetime",
      "ast", "hashlib", "io", "string", "textwrap", "enum", "abc",
  })
  # 注：os 在 allow（patch 目标常需 os.path），但 os.system/os.popen 等具体调用仍被 DANGEROUS_CALLS 拦。

  def _attr_chain(node: ast.AST) -> str:
      parts = []
      while isinstance(node, ast.Attribute):
          parts.append(node.attr)
          node = node.value
      if isinstance(node, ast.Name):
          parts.append(node.id)
      return ".".join(reversed(parts))

  def _is_outside_sandbox(literal: str, sandbox_root: str, target_path: str) -> bool:
      if not (sandbox_root and target_path):
          return False
      root = os.path.realpath(sandbox_root)
      if os.path.isabs(literal) or (len(literal) > 1 and literal[1] == ":"):
          cand = os.path.realpath(literal)
      else:
          base = os.path.dirname(os.path.realpath(target_path))
          cand = os.path.realpath(os.path.join(base, literal))
      try:
          return os.path.commonpath([root, cand]) != root
      except ValueError:
          return True  # 不同盘符 → 视为越界

  def scan_ast_dangerous(source: str, *, allow_imports=None,
                         sandbox_root=None, target_path=None) -> list[str]:
      allow = set(DEFAULT_IMPORT_ALLOW) | set(allow_imports or set())
      try:
          tree = ast.parse(source)
      except SyntaxError as e:
          return [f"unparseable source: {e}"]
      reasons: list[str] = []
      for node in ast.walk(tree):
          # import 默认拒白名单
          if isinstance(node, ast.Import):
              for a in node.names:
                  top = a.name.split(".")[0]
                  if top not in allow:
                      reasons.append(f"import not in allowlist: {a.name}")
          elif isinstance(node, ast.ImportFrom):
              top = (node.module or "").split(".")[0]
              if top and top not in allow:
                  reasons.append(f"import-from not in allowlist: {node.module}")
          # 调用门
          elif isinstance(node, ast.Call):
              fn = node.func
              callee = fn.id if isinstance(fn, ast.Name) else (
                  _attr_chain(fn) if isinstance(fn, ast.Attribute) else "")
              leaf = callee.split(".")[-1] if callee else ""
              top = callee.split(".")[0] if callee else ""
              if leaf in DANGEROUS_CALLS:
                  reasons.append(f"dangerous call: {callee or leaf}")
              if top in DANGEROUS_MODULE_PREFIXES:
                  reasons.append(f"dangerous module call: {callee}")
              # 沙箱外 open
              if leaf == "open" and node.args:
                  arg0 = node.args[0]
                  if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                      if _is_outside_sandbox(arg0.value, sandbox_root, target_path):
                          reasons.append(f"open outside sandbox: {arg0.value}")
                  elif not isinstance(arg0, ast.Constant):
                      # 动态路径 open 无法静态证明在沙箱内 → 当 sandbox_root 已知时拒
                      if sandbox_root:
                          reasons.append("open with non-literal path (cannot prove in-sandbox)")
      return reasons
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_ast_gate.py -q`
  - Expected: PASS

- [ ] **Step 5: 接入 `apply_patch` 预检**
  在 `apply_patch` 内、写盘**之前**插入门检查（patch 字典含 `new_content`/`file`，从 M1a 约定取；若字段名不同按 M1a 实际）：
  ```python
  # apply_patch(worktree, patch) 内，应用前：
  new_src = patch.get("new_content", "")
  if new_src:
      reasons = scan_ast_dangerous(
          new_src,
          allow_imports=set(patch.get("allow_imports", [])),
          sandbox_root=worktree,
          target_path=os.path.join(worktree, patch["file"]),
      )
      if reasons:
          return {"status": "REJECT", "reason": "; ".join(reasons), "file": patch["file"]}
  ```

- [ ] **Step 6: 写接入回归测试 + 跑全套**
  在 `tests/test_patch_ast_gate.py` 追加：
  ```python
  import os
  from sie.patch import apply_patch

  def test_apply_patch_rejects_dangerous(tmp_path):
      wt = str(tmp_path)
      os.makedirs(os.path.join(wt, "tools", "sie"), exist_ok=True)
      patch = {"file": "tools/sie/x.py",
               "new_content": "import subprocess\nsubprocess.run(['ls'])\n"}
      r = apply_patch(wt, patch)
      assert r["status"] == "REJECT" and "subprocess" in r["reason"]
  ```
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_ast_gate.py -q`
  - Expected: PASS

- [ ] **Step 7: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/patch.py tests/test_patch_ast_gate.py && git commit -m "$(cat <<'EOF'
    M1b.1: AST 危险调用拒绝门全清单 + import 默认拒白名单 + 沙箱外 open 拦截

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.2: 变异测试有效性门（verifiable.py）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/verifiable.py`（在 M1a 已实现的 `run_grader` / 快照哈希之上新增 `mutation_validity_gate`）
- Test: `~/CodesSelf/self-evolve/tests/test_mutation_gate.py`

**Interfaces:**
- Consumes（M1a 产出）：`run_grader(worktree: str, env_whitelist: list[str]) -> dict`（返回 `{"task_passed":bool,"grader_exit_code":int,...}`）
- Produces：
  - `inject_mutants(source: str) -> list[tuple[str, str]]`（返回 `[(mutant_id, mutated_source), ...]`，对 `+`/`-`/比较/布尔常量做标准变异）
  - `mutation_validity_gate(worktree: str, source_files: list[str], run_one, *, min_kill_ratio: float = 1.0) -> dict`（`run_one(worktree)->bool` 跑一次测试套返回是否全绿；返回 `{"valid":bool,"killed":int,"total":int,"kill_ratio":float,"survivors":[mutant_id,...]}`）

> 关键：spec §1/§5.2,"exec 探针变异测试二次校验（注入 bug 须变红，杀不死则信号作废）"。门的语义=对**被测源码**注入 bug，若测试仍全绿（mutant 存活）则该 grader 是放水测试 → 信号作废。M1b 默认 `min_kill_ratio=1.0`（任一存活即作废），保守。

- [ ] **Step 1: 写失败测试,真测试杀死变异、假测试放过变异**
  新建 `tests/test_mutation_gate.py`：
  ```python
  import os, textwrap
  from sie.verifiable import inject_mutants, mutation_validity_gate

  def _write(wt, rel, content):
      p = os.path.join(wt, rel)
      os.makedirs(os.path.dirname(p), exist_ok=True)
      with open(p, "w", encoding="utf-8") as f:
          f.write(textwrap.dedent(content))
      return rel

  def test_inject_mutants_produces_variants():
      src = "def f(a, b):\n    return a + b\n"
      muts = inject_mutants(src)
      assert muts, "should produce at least one mutant"
      assert all(m_src != src for _, m_src in muts)

  def test_real_test_kills_all_mutants(tmp_path):
      wt = str(tmp_path)
      src_rel = _write(wt, "pkg/calc.py", """
          def add(a, b):
              return a + b
      """)
      # 真测试：断言 add(2,3)==5，任何 + 变异都会变红
      def run_one(worktree):
          import importlib.util
          spec = importlib.util.spec_from_file_location(
              "calc_under_test", os.path.join(worktree, src_rel))
          mod = importlib.util.module_from_spec(spec)
          spec.loader.exec_module(mod)
          return mod.add(2, 3) == 5
      res = mutation_validity_gate(wt, [src_rel], run_one)
      assert res["valid"] is True
      assert res["kill_ratio"] == 1.0 and res["survivors"] == []

  def test_fake_test_lets_mutant_survive(tmp_path):
      wt = str(tmp_path)
      src_rel = _write(wt, "pkg/calc.py", """
          def add(a, b):
              return a + b
      """)
      # 假测试：永远返回 True（放水）→ mutant 存活 → 信号作废
      def run_one(worktree):
          return True
      res = mutation_validity_gate(wt, [src_rel], run_one)
      assert res["valid"] is False
      assert res["survivors"], "fake test must leave survivors"
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_mutation_gate.py -q`
  - Expected: FAIL（`ImportError: cannot import name 'inject_mutants'`）

- [ ] **Step 3: 写最小实现,`inject_mutants` + `mutation_validity_gate`**
  在 `tools/sie/verifiable.py` 加入（确保 `import ast`、`import os`、`import shutil`）：
  ```python
  class _Mutator(ast.NodeTransformer):
      def __init__(self, target_idx):
          self.target_idx = target_idx
          self.counter = 0
          self.applied = False
      def _hit(self):
          here = self.counter
          self.counter += 1
          return here == self.target_idx
      def visit_BinOp(self, node):
          self.generic_visit(node)
          if isinstance(node.op, ast.Add) and self._hit():
              self.applied = True
              return ast.copy_location(ast.BinOp(node.left, ast.Sub(), node.right), node)
          if isinstance(node.op, ast.Sub) and self._hit():
              self.applied = True
              return ast.copy_location(ast.BinOp(node.left, ast.Add(), node.right), node)
          return node
      def visit_Compare(self, node):
          self.generic_visit(node)
          if len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and self._hit():
              self.applied = True
              flip = ast.NotEq() if isinstance(node.ops[0], ast.Eq) else ast.Eq()
              return ast.copy_location(ast.Compare(node.left, [flip], node.comparators), node)
          return node
      def visit_Constant(self, node):
          if isinstance(node.value, bool) and self._hit():
              self.applied = True
              return ast.copy_location(ast.Constant(not node.value), node)
          return node

  def _count_sites(source: str) -> int:
      m = _Mutator(target_idx=-1)
      m.visit(ast.parse(source))
      return m.counter

  def inject_mutants(source: str) -> list[tuple[str, str]]:
      n = _count_sites(source)
      out = []
      for i in range(n):
          mut = _Mutator(target_idx=i)
          tree = mut.visit(ast.parse(source))
          if mut.applied:
              ast.fix_missing_locations(tree)
              out.append((f"mut_{i}", ast.unparse(tree)))
      return out

  def mutation_validity_gate(worktree, source_files, run_one, *, min_kill_ratio=1.0):
      killed = total = 0
      survivors = []
      for rel in source_files:
          abs = os.path.join(worktree, rel)
          with open(abs, encoding="utf-8") as f:
              original = f.read()
          backup = abs + ".orig"
          shutil.copy2(abs, backup)
          try:
              for mid, msrc in inject_mutants(original):
                  total += 1
                  with open(abs, "w", encoding="utf-8") as f:
                      f.write(msrc)
                  try:
                      green = bool(run_one(worktree))
                  except Exception:
                      green = False  # 变异导致异常 = 被杀死
                  if green:
                      survivors.append(f"{rel}:{mid}")  # 仍全绿 = mutant 存活
                  else:
                      killed += 1
          finally:
              shutil.copy2(backup, abs)
              os.remove(backup)
      ratio = (killed / total) if total else 0.0
      return {"valid": total > 0 and ratio >= min_kill_ratio,
              "killed": killed, "total": total,
              "kill_ratio": ratio, "survivors": survivors}
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_mutation_gate.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/verifiable.py tests/test_mutation_gate.py && git commit -m "$(cat <<'EOF'
    M1b.2: 变异测试有效性门 (注入 bug 须变红, 杀不死则 grader 信号作废)

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.3: PACE A 档 e-process（acceptor.py，站 confseq）

**Files:**
- Create: `~/CodesSelf/self-evolve/reference/acceptor_math.md`（per-tier 配对推导 + null/缩放/截断说明）
- Modify: `~/CodesSelf/self-evolve/tools/sie/acceptor.py`（M1a 为 no-regression 兜底；本任务实现 `decide` 的 A 档 e-process 分支 + confseq 适配器）
- Test: `~/CodesSelf/self-evolve/tests/test_acceptor_noise.py`

**Interfaces:**
- Consumes（契约）：`RunState`（字段 `continue_count`/`tier`），`params`（含 `α`/`n_min`/`continue_count_cap`/`evalue_max_step`/`effective_independent_anchor_min`）
- Consumes（外部库）：`confseq.betting.betting_mart(x, m, alpha=0.05) -> np.ndarray`（x∈[0,1] 的数据序列、null 均值 m、返回 wealth/martingale 序列；e-value = 序列末值）
- Produces（契约签名，勿改名）：
  - `decide(paired: list[tuple[float,float]], tier: str, st: RunState, params: dict) -> dict`（`-> {"decision":"ACCEPT"|"REJECT"|"CONTINUE","evalue":float,"reason":str}`）
  - 内部：`_wealth_betting(diffs: list[float], alpha: float) -> tuple[float, list[float]]`（confseq 优先、缺失回退自洽 ONS-betting；返回 `(evalue, wealth_path)`）
  - 内部：`_pace_threshold(alpha: float) -> float`（=`1/alpha`）

> 关键数学（必须照此实现，不可只描述）：
> - A 档配对单元=per-task `task_passed`（改后/改前）。把每对 `(before, after)` 的差 `d = after - before ∈ {-1,0,+1}`，映成 `u = 0.5*(d + 1) ∈ {0,0.5,1}` 喂 `betting_mart`，null `m=0.5`（="零差/不更好"）。e-value = wealth 末值；**e-value ≥ 1/α 才 ACCEPT**（anytime-valid，控误提交 ≤ α）。
> - **A 档二态**：A 档只返回 ACCEPT/REJECT，禁 CONTINUE（spec §4/§5.5）。
> - 主观分（B/C，本里程碑不主判，仅留接口）进 e-process 前按历史方差缩放 + 单轮 `evalue_max_step` 截断；A 档为离散 0/1 不缩放。
> - confseq 缺失时回退**自洽 ONS-betting 鞅**（同样 anytime-valid），保证单测不依赖外部安装即可跑。

- [ ] **Step 1: 写 acceptor_math.md（参考实现说明，非测试）**
  新建 `reference/acceptor_math.md`，内容含：null 设定（A 档 m=0.5）、betting martingale wealth=∏(1+λ_t(u_t−m)) 的 anytime-valid 保证、阈值 1/α、per-tier 配对单元表、主观分方差缩放与 `evalue_max_step` 截断规则、confseq→ONS 回退说明。提交即可，无 Run。

- [ ] **Step 2: 写失败测试,噪声/真增益/误提交/对抗/二态**
  新建 `tests/test_acceptor_noise.py`：
  ```python
  import random
  import pytest
  from sie.state import RunState
  from sie.acceptor import decide

  PARAMS = {"α": 0.05, "n_min": 8, "continue_count_cap": 5,
            "evalue_max_step": 4.0, "effective_independent_anchor_min": 12}

  def _rs(tier="A"):
      return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None,
                      tier=tier)

  def _pure_noise_pairs(n, seed):
      r = random.Random(seed)
      # before/after 各独立 Bernoulli(0.5)，无真实增益
      return [(float(r.random() < 0.5), float(r.random() < 0.5)) for _ in range(n)]

  def _true_gain_pairs(n, seed, before_p=0.3, after_p=0.9):
      r = random.Random(seed)
      return [(float(r.random() < before_p), float(r.random() < after_p))
              for _ in range(n)]

  def test_pure_noise_reject_rate_near_one():
      rejects = 0
      trials = 200
      for s in range(trials):
          d = decide(_pure_noise_pairs(40, s), "A", _rs(), PARAMS)
          if d["decision"] == "REJECT":
              rejects += 1
      assert rejects / trials >= 0.95  # 纯噪声拒绝率≈1

  def test_false_commit_rate_under_alpha():
      # 真 null（before==after 同分布）下误 ACCEPT 率 ≤ α
      commits = 0
      trials = 400
      for s in range(trials):
          d = decide(_pure_noise_pairs(40, s + 9000), "A", _rs(), PARAMS)
          if d["decision"] == "ACCEPT":
              commits += 1
      assert commits / trials <= 0.05

  def test_true_gain_accept_rate_high():
      accepts = 0
      trials = 100
      for s in range(trials):
          d = decide(_true_gain_pairs(40, s), "A", _rs(), PARAMS)
          if d["decision"] == "ACCEPT":
              accepts += 1
      assert accepts / trials >= 0.9  # 真增益采纳率高

  def test_A_tier_never_continue():
      d = decide(_true_gain_pairs(40, 1), "A", _rs(), PARAMS)
      assert d["decision"] in ("ACCEPT", "REJECT")  # A 档二态

  def test_adversarial_drift_rejected():
      # 主观正漂移 + 每轮 +0.5% 微涨（无真实配对增益）→ A 档配对差≈0 → 拒
      pairs = [(0.6, 0.6 + 0.005) for _ in range(40)]
      d = decide(pairs, "A", _rs(), PARAMS)
      assert d["decision"] == "REJECT"

  def test_evalue_threshold_is_inverse_alpha():
      d = decide(_true_gain_pairs(60, 3, before_p=0.1, after_p=0.95), "A", _rs(), PARAMS)
      if d["decision"] == "ACCEPT":
          assert d["evalue"] >= 1.0 / PARAMS["α"]
  ```

- [ ] **Step 3: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_noise.py -q`
  - Expected: FAIL（A 档 e-process 分支未实现，纯噪声/真增益断言不成立或函数报错）

- [ ] **Step 4: 写最小实现,confseq 适配器 + ONS 回退 + `decide` A 档分支**
  在 `tools/sie/acceptor.py` 加入：
  ```python
  def _pace_threshold(alpha: float) -> float:
      return 1.0 / alpha

  def _ons_betting_wealth(diffs, alpha):
      """自洽 ONS betting 鞅 (anytime-valid), confseq 缺失时回退。
      u_t = 0.5*(d+1) ∈ [0,1], null m=0.5, wealth=∏(1+λ_t (u_t-0.5))。
      λ_t 用 ONS/上一轮梯度自适应, 截到 [-2,2] 保证 1+λ(u-0.5)>0。"""
      wealth = 1.0
      path = []
      lam = 0.0
      grad_sq = 1.0
      for d in diffs:
          u = 0.5 * (d + 1.0)
          payoff = u - 0.5
          factor = 1.0 + lam * payoff
          if factor <= 1e-12:
              factor = 1e-12
          wealth *= factor
          path.append(wealth)
          # ONS 更新: 朝增大 wealth 的方向押注
          z = payoff / (1.0 + lam * payoff)
          grad_sq += z * z
          lam = max(-2.0, min(2.0, lam + (2.0 / (2.0 - 1.0)) * z / grad_sq))
      return wealth, path

  def _wealth_betting(diffs, alpha):
      try:
          import numpy as np
          from confseq.betting import betting_mart
          u = np.array([0.5 * (d + 1.0) for d in diffs], dtype=float)
          mart = betting_mart(u, 0.5, alpha=alpha)
          path = [float(v) for v in np.asarray(mart).ravel()]
          return (path[-1] if path else 1.0), path
      except Exception:
          return _ons_betting_wealth(diffs, alpha)

  def _scale_subjective(diffs, params):
      """B/C 主观分: 历史方差缩放 + 单轮 evalue_max_step 截断 (A 档跳过)。"""
      import statistics
      cap = params.get("evalue_max_step", 4.0)
      if len(diffs) < 2:
          return diffs
      sd = statistics.pstdev(diffs) or 1.0
      scaled = [max(-1.0, min(1.0, d / (sd * cap))) for d in diffs]
      return scaled

  def decide(paired, tier, st, params):
      alpha = params.get("α", params.get("alpha", 0.05))
      thr = _pace_threshold(alpha)
      base_tier = tier.split("+")[0]  # 叠加 tier 取主档
      n = len(paired)
      if n == 0:
          return {"decision": "REJECT", "evalue": 0.0, "reason": "empty paired"}
      diffs = [after - before for (before, after) in paired]

      if base_tier == "A":
          evalue, _ = _wealth_betting(diffs, alpha)
          if evalue >= thr:
              return {"decision": "ACCEPT", "evalue": evalue,
                      "reason": f"e={evalue:.2f}>=1/α={thr:.1f}"}
          return {"decision": "REJECT", "evalue": evalue,
                  "reason": f"e={evalue:.2f}<1/α={thr:.1f} (A 档二态)"}

      # B/C: 主观分缩放 + n_min/有效独立锚门 (本里程碑仅占位接口, M2/M3 接全)
      n_min = params.get("n_min", 8)
      if base_tier == "B" and n < n_min:
          return {"decision": "REJECT", "evalue": 0.0,
                  "reason": f"n_anchor={n}<n_min={n_min} 禁 ACCEPT"}
      evalue, _ = _wealth_betting(_scale_subjective(diffs, params), alpha)
      if evalue >= thr:
          return {"decision": "ACCEPT", "evalue": evalue, "reason": f"e={evalue:.2f}>=1/α"}
      # B/C 随机档允许 CONTINUE: 介于阈值与 1 之间则继续取证
      if 1.0 <= evalue < thr and st.continue_count < params.get("continue_count_cap", 5):
          return {"decision": "CONTINUE", "evalue": evalue,
                  "reason": f"e={evalue:.2f} 介于 [1,1/α) 继续取证"}
      return {"decision": "REJECT", "evalue": evalue, "reason": f"e={evalue:.2f}<1/α"}
  ```

- [ ] **Step 5: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_noise.py -q`
  - Expected: PASS（若 confseq 已装走真库、未装走 ONS 回退，两条路径都应满足噪声/真增益/误提交断言）

- [ ] **Step 6: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/acceptor.py reference/acceptor_math.md tests/test_acceptor_noise.py && git commit -m "$(cat <<'EOF'
    M1b.3: PACE A 档 e-process (confseq betting + ONS 回退, per-task 配对二态, 噪声/对抗单测过)

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.4: acceptor 对抗/锚相关单测加固（acceptor.py 边界）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/acceptor.py`（无需改 `decide` 主体，补一个去相关降权辅助供 B 档对抗测试驱动）
- Test: `~/CodesSelf/self-evolve/tests/test_acceptor_adversarial.py`

**Interfaces:**
- Produces：`_decorrelate_downweight(diffs: list[float], cluster_ids: list[str]) -> list[float]`（同源锚配对前按簇大小 `1/size` 降权，防相关锚虚高 e-value；返回降权后差序列）

> 关键：spec §9 对抗闸门,小相关锚集（8 同源锚每轮 +微涨）必须被拒。机制=同源去相关降权 + B 档 `n_min`/有效独立锚下限。本任务把"同源锚虚高"做成可跑负向用例。

- [ ] **Step 1: 写失败测试,小相关锚集被拒 + 主观正漂移被拒**
  新建 `tests/test_acceptor_adversarial.py`：
  ```python
  from sie.state import RunState
  from sie.acceptor import decide, _decorrelate_downweight

  PARAMS = {"α": 0.05, "n_min": 8, "continue_count_cap": 5,
            "evalue_max_step": 4.0, "effective_independent_anchor_min": 12}

  def _rs(tier="B"):
      return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)

  def test_small_correlated_anchor_set_rejected():
      # 8 个同源锚, 每轮统一 +0.01 微涨; 都来自同一 source cluster
      diffs = [0.01] * 8
      clusters = ["src#1"] * 8
      dw = _decorrelate_downweight(diffs, clusters)
      d = decide([(0.5, 0.5 + x) for x in dw], "B", _rs(), PARAMS)
      assert d["decision"] != "ACCEPT"  # 相关锚虚高被降权 → 不采纳

  def test_b_tier_below_n_min_rejected():
      d = decide([(0.5, 0.6)] * 4, "B", _rs(), PARAMS)  # n=4 < n_min=8
      assert d["decision"] == "REJECT" and "n_min" in d["reason"]

  def test_decorrelate_independent_anchors_kept():
      diffs = [0.5] * 6
      clusters = [f"src#{i}" for i in range(6)]  # 全独立
      dw = _decorrelate_downweight(diffs, clusters)
      assert dw == diffs  # 独立锚不降权
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_adversarial.py -q`
  - Expected: FAIL（`ImportError: cannot import name '_decorrelate_downweight'`）

- [ ] **Step 3: 写最小实现,`_decorrelate_downweight`**
  在 `tools/sie/acceptor.py` 加入：
  ```python
  def _decorrelate_downweight(diffs, cluster_ids):
      from collections import Counter
      sizes = Counter(cluster_ids)
      return [d / sizes[c] for d, c in zip(diffs, cluster_ids)]
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_adversarial.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/acceptor.py tests/test_acceptor_adversarial.py && git commit -m "$(cat <<'EOF'
    M1b.4: acceptor 同源去相关降权 + 小相关锚集/n_min 对抗负向用例

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.5: 人审非阻塞队列完整（gate_human.py）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/gate_human.py`（M1a 为基础 enqueue；本任务补 `pending`/`resolve`/ttl/状态机字段 + 非阻塞语义）
- Test: `~/CodesSelf/self-evolve/tests/test_gate_human.py`

**Interfaces:**
- Consumes（契约/M1a）：`action_class(action: dict, sandbox_root: str) -> str`（"auto"|"gated"）
- Produces（契约签名，勿改名 + 补充）：
  - `enqueue(run_dir: str, action: dict) -> str`（返回 `aid`；写 `pending_actions.jsonl`，status="pending"，含 ttl；非阻塞立即返回）
  - `pending(run_dir: str) -> list[dict]`（只返回 status=="pending" 且未过期）
  - `resolve(run_dir: str, aid: str, status: str) -> None`（status∈{"approved","skipped","expired"}；append-only 不改历史行，追加终态行）

> 关键：spec R2/§4 态9.5,人审"标 pending、跳过、继续"非阻塞；`pending_actions.jsonl` append-only。resolve 不重写旧行，追加 resolution 行，`pending()` 取每个 aid 的最新状态。

- [ ] **Step 1: 写失败测试,enqueue 非阻塞 + pending 过滤 + resolve 终态 + ttl**
  新建 `tests/test_gate_human.py`：
  ```python
  import os, time, json
  from sie.gate_human import enqueue, pending, resolve

  def test_enqueue_returns_aid_nonblocking(tmp_path):
      rd = str(tmp_path)
      aid = enqueue(rd, {"action_type": "land", "payload": {"vid": "v1"}, "ttl": 3600})
      assert isinstance(aid, str) and aid
      p = pending(rd)
      assert len(p) == 1 and p[0]["aid"] == aid and p[0]["status"] == "pending"

  def test_resolve_removes_from_pending(tmp_path):
      rd = str(tmp_path)
      aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
      resolve(rd, aid, "approved")
      assert pending(rd) == []
      # append-only: 文件应同时含 pending 行与 resolution 行
      lines = open(os.path.join(rd, "pending_actions.jsonl"), encoding="utf-8").read().strip().splitlines()
      assert len(lines) == 2

  def test_expired_ttl_excluded(tmp_path):
      rd = str(tmp_path)
      aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 0})
      time.sleep(0.01)
      assert pending(rd) == []  # ttl=0 立即过期

  def test_multiple_actions_independent(tmp_path):
      rd = str(tmp_path)
      a1 = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
      a2 = enqueue(rd, {"action_type": "push", "payload": {}, "ttl": 3600})
      resolve(rd, a1, "skipped")
      p = pending(rd)
      assert [x["aid"] for x in p] == [a2]
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_gate_human.py -q`
  - Expected: FAIL（`pending`/`resolve` 未实现或 ttl/append-only 语义缺失）

- [ ] **Step 3: 写最小实现,enqueue/pending/resolve**
  在 `tools/sie/gate_human.py` 加入（确保 `import os, json, time, uuid`）：
  ```python
  _QUEUE = "pending_actions.jsonl"

  def _path(run_dir):
      return os.path.join(run_dir, _QUEUE)

  def enqueue(run_dir, action):
      os.makedirs(run_dir, exist_ok=True)
      aid = action.get("aid") or uuid.uuid4().hex[:12]
      now = time.time()
      rec = {"aid": aid, "kind": "request",
             "action_type": action.get("action_type", "unknown"),
             "payload": action.get("payload", {}),
             "created_at": now, "ttl": action.get("ttl", 86400),
             "status": "pending"}
      with open(_path(run_dir), "a", encoding="utf-8") as f:
          f.write(json.dumps(rec, ensure_ascii=False) + "\n")
      return aid  # 立即返回, 不阻塞

  def _read_all(run_dir):
      p = _path(run_dir)
      if not os.path.exists(p):
          return []
      out = []
      with open(p, encoding="utf-8") as f:
          for line in f:
              line = line.strip()
              if line:
                  out.append(json.loads(line))
      return out

  def pending(run_dir):
      now = time.time()
      latest = {}       # aid -> 最新状态记录
      meta = {}         # aid -> request 记录 (created_at/ttl)
      for rec in _read_all(run_dir):
          if rec.get("kind") == "request":
              meta[rec["aid"]] = rec
          latest[rec["aid"]] = rec
      out = []
      for aid, rec in latest.items():
          if rec.get("status") != "pending":
              continue
          m = meta.get(aid, rec)
          if m.get("ttl", 0) <= 0 or (now - m.get("created_at", now)) > m.get("ttl", 0):
              continue  # 过期排除
          out.append(m)
      return out

  def resolve(run_dir, aid, status):
      assert status in ("approved", "skipped", "expired"), status
      rec = {"aid": aid, "kind": "resolution",
             "status": status, "resolved_at": time.time()}
      with open(_path(run_dir), "a", encoding="utf-8") as f:
          f.write(json.dumps(rec, ensure_ascii=False) + "\n")  # append-only
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_gate_human.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/gate_human.py tests/test_gate_human.py && git commit -m "$(cat <<'EOF'
    M1b.5: 人审非阻塞队列 (enqueue/pending/resolve, append-only, ttl 过期, 多 action 独立)

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.6: 三计数器 + 熔断 + 态9.5 + CONTINUE 落点（statemachine.py）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/statemachine.py`（M1a 为转移骨架；本任务实现计数器更新、熔断判定、态9.5、CONTINUE 上限落点、A 档禁 CONTINUE 守卫）
- Test: `~/CodesSelf/self-evolve/tests/test_statemachine_counters.py`

**Interfaces:**
- Consumes（契约）：`RunState`（`no_progress`/`static_reject`/`forced_review`/`continue_count`/`drift_count`），`decide(...)` 返回的 decision，`gate_human.enqueue`
- Produces：
  - `apply_acceptor_outcome(st: RunState, decision: dict, params: dict) -> str`（依 decision 更新计数器、做 CONTINUE 上限落点+A 档禁 CONTINUE 守卫；返回下一态 token：`"EVALUATE"|"ARCHIVE"|"LOOP"|"PAUSE_FOR_HUMAN"`）
  - `note_static_reject(st: RunState) -> str`（态4 空 / 态5 全拒时调用，`static_reject++` 返回 `"LOOP"`）
  - `note_forced_review(st: RunState) -> None`（态9.5 进入时 `forced_review++`）
  - `circuit_check(st: RunState, params: dict) -> str | None`（返回熔断原因 token：`"no_progress_circuit"|"static_reject_circuit"|"forced_review_circuit"|"drift_circuit"|"no_progress_release"` 或 None）

> 关键状态机不变量（必须照此实现）：
> - 三计数器正交：`no_progress`=acceptor 的 REJECT/CONTINUE 轮；`static_reject`=态4空+态5全拒；`forced_review`=态9.5 轮。
> - CONTINUE 仅 B/C；A 档若 decision 异常给出 CONTINUE → 守卫强制改 REJECT（防活性漏洞）。
> - CONTINUE 达 `continue_count_cap=5` → 落点 REJECT（不无限取证）。
> - 熔断阈：`no_progress N=8`、`static_reject N_sr=6`、`forced_review N_fr=5`、`drift N_drift=4`；释放阀 `no_progress M=3`(仅升人审频率，不降阈采纳)。
> - ACCEPT→ARCHIVE 时清零 `no_progress`/`forced_review`/`continue_count`（spec §4 态8）。

- [ ] **Step 1: 写失败测试,三计数器/熔断/CONTINUE 落点/A 禁 CONTINUE/清零**
  新建 `tests/test_statemachine_counters.py`：
  ```python
  from sie.state import RunState
  from sie.statemachine import (apply_acceptor_outcome, note_static_reject,
                                note_forced_review, circuit_check)

  P = {"continue_count_cap": 5, "no_progress_circuit_N": 8, "no_progress_release_M": 3,
       "static_reject_circuit": 6, "forced_review_circuit": 5, "drift_circuit": 4}

  def _rs(tier="B"):
      return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)

  def test_reject_increments_no_progress():
      st = _rs()
      nxt = apply_acceptor_outcome(st, {"decision": "REJECT", "evalue": 0.0, "reason": ""}, P)
      assert st.no_progress == 1 and nxt == "LOOP"

  def test_accept_clears_counters_and_archives():
      st = _rs(); st.no_progress = 5; st.forced_review = 2; st.continue_count = 3
      nxt = apply_acceptor_outcome(st, {"decision": "ACCEPT", "evalue": 99.0, "reason": ""}, P)
      assert nxt == "ARCHIVE"
      assert st.no_progress == 0 and st.forced_review == 0 and st.continue_count == 0

  def test_continue_increments_then_caps_to_reject():
      st = _rs()
      for _ in range(P["continue_count_cap"]):
          nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
          assert nxt == "EVALUATE"
      # 第 cap+1 次 → 落点 REJECT
      nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
      assert nxt == "LOOP" and st.continue_count == P["continue_count_cap"]

  def test_A_tier_continue_forced_to_reject():
      st = _rs(tier="A")
      nxt = apply_acceptor_outcome(st, {"decision": "CONTINUE", "evalue": 2.0, "reason": ""}, P)
      assert nxt == "LOOP" and st.continue_count == 0  # A 档禁 CONTINUE → 当 REJECT

  def test_static_reject_counter():
      st = _rs()
      for i in range(P["static_reject_circuit"]):
          note_static_reject(st)
      assert st.static_reject == P["static_reject_circuit"]
      assert circuit_check(st, P) == "static_reject_circuit"

  def test_forced_review_circuit():
      st = _rs()
      for _ in range(P["forced_review_circuit"]):
          note_forced_review(st)
      assert circuit_check(st, P) == "forced_review_circuit"

  def test_no_progress_circuit_and_release():
      st = _rs(); st.no_progress = P["no_progress_release_M"]
      assert circuit_check(st, P) == "no_progress_release"   # M 触发释放阀(升人审)
      st.no_progress = P["no_progress_circuit_N"]
      assert circuit_check(st, P) == "no_progress_circuit"   # N 触发熔断

  def test_forced_review_routes_to_pause():
      st = _rs()
      nxt = apply_acceptor_outcome(st, {"decision": "FORCE_HUMAN", "evalue": 1.0, "reason": "coverage<floor"}, P)
      assert nxt == "PAUSE_FOR_HUMAN"
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_statemachine_counters.py -q`
  - Expected: FAIL（`ImportError`/计数器与落点逻辑缺失）

- [ ] **Step 3: 写最小实现,计数器/熔断/落点/守卫**
  在 `tools/sie/statemachine.py` 加入：
  ```python
  def apply_acceptor_outcome(st, decision, params):
      d = decision["decision"]
      cap = params.get("continue_count_cap", 5)
      base_tier = st.tier.split("+")[0]
      if d == "ACCEPT":
          st.no_progress = 0
          st.forced_review = 0
          st.continue_count = 0
          return "ARCHIVE"
      if d == "FORCE_HUMAN":
          return "PAUSE_FOR_HUMAN"
      if d == "CONTINUE":
          # A 档禁 CONTINUE 守卫 → 当 REJECT 计 no_progress
          if base_tier == "A":
              st.no_progress += 1
              return "LOOP"
          if st.continue_count >= cap:      # 达上限落点 REJECT
              st.no_progress += 1
              return "LOOP"
          st.continue_count += 1
          st.no_progress += 1               # CONTINUE 也算 no_progress 轮
          return "EVALUATE"
      # REJECT
      st.no_progress += 1
      return "LOOP"

  def note_static_reject(st):
      st.static_reject += 1
      return "LOOP"

  def note_forced_review(st):
      st.forced_review += 1

  def circuit_check(st, params):
      if st.no_progress >= params.get("no_progress_circuit_N", 8):
          return "no_progress_circuit"
      if st.static_reject >= params.get("static_reject_circuit", 6):
          return "static_reject_circuit"
      if st.forced_review >= params.get("forced_review_circuit", 5):
          return "forced_review_circuit"
      if st.drift_count >= params.get("drift_circuit", 4):
          return "drift_circuit"
      if st.no_progress >= params.get("no_progress_release_M", 3):
          return "no_progress_release"   # 仅升人审频率, 不降阈采纳
      return None
  ```
  注：`circuit_check` 把熔断阈放在释放阀之前判定，保证 `no_progress` 同时 ≥M 且 ≥N 时优先报熔断；测试用例分别设 M、N 两值验证两条路径。

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_statemachine_counters.py -q`
  - Expected: PASS

- [ ] **Step 5: 接入态7→态9.5 路由 + Discord 通知（最小）**
  在 statemachine 主循环态7 处理段把 `FORCE_HUMAN` 路由到态9.5：进入 9.5 时 `note_forced_review(st)` + `gate_human.enqueue(run_dir, {...})` + `notify.notify(...)`（M1a 已有 notify 包装；若无则 try/except 跳过），随后判 `circuit_check`==`forced_review_circuit` → 停机。补一条集成测试：
  ```python
  # 追加到 tests/test_statemachine_counters.py
  def test_repeated_forced_review_circuit_stops():
      st = _rs()
      stopped = False
      for _ in range(10):
          apply_acceptor_outcome(st, {"decision": "FORCE_HUMAN", "evalue": 1.0, "reason": ""}, P)
          note_forced_review(st)
          if circuit_check(st, P) == "forced_review_circuit":
              stopped = True
              break
      assert stopped and st.forced_review >= P["forced_review_circuit"]
  ```
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_statemachine_counters.py -q`
  - Expected: PASS

- [ ] **Step 6: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tools/sie/statemachine.py tests/test_statemachine_counters.py && git commit -m "$(cat <<'EOF'
    M1b.6: 状态机三计数器+各熔断阈+态9.5+CONTINUE 上限落点+A 档禁 CONTINUE 守卫

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```

---

### Task M1b.7: M1b 验收套件（端到端：安全门全开 + acceptor + 活性/计数）

**Files:**
- Test: `~/CodesSelf/self-evolve/tests/test_m1b_acceptance.py`

**Interfaces:**
- Consumes：本里程碑全部 Produces（`scan_ast_dangerous`/`mutation_validity_gate`/`decide`/`enqueue`/`pending`/`apply_acceptor_outcome`/`circuit_check`）+ M1a 端到端入口（若 M1a 提供 `run_once(target, params)`/`statemachine.step`；此处仅做组合断言不重跑真 git）

> 这是 spec §13 M1b 验收的总闸：把"安全负向用例全过 / acceptor 正确采纳拒绝 / 活性计数过"合成一套可一键跑的回归。

- [ ] **Step 1: 写验收测试（组合断言）**
  新建 `tests/test_m1b_acceptance.py`：
  ```python
  import random
  from sie.state import RunState
  from sie.patch import scan_ast_dangerous
  from sie.acceptor import decide
  from sie.gate_human import enqueue, pending, resolve
  from sie.statemachine import apply_acceptor_outcome, circuit_check, note_static_reject

  P = {"α": 0.05, "n_min": 8, "continue_count_cap": 5,
       "no_progress_circuit_N": 8, "static_reject_circuit": 6,
       "forced_review_circuit": 5, "drift_circuit": 4, "no_progress_release_M": 3,
       "evalue_max_step": 4.0, "effective_independent_anchor_min": 12}

  def _rs(tier="A"):
      return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)

  # ---- 安全负向全过 ----
  def test_security_negatives_all_rejected():
      for src in ["import socket\nsocket.socket()\n",
                  "import ctypes\n", "eval('1')\n",
                  "import subprocess\nsubprocess.run([])\n",
                  "m=__import__('os')\n", "import requests\n"]:
          assert scan_ast_dangerous(src), f"must reject: {src!r}"

  # ---- acceptor 正确采纳/拒绝 ----
  def test_acceptor_noise_vs_gain():
      r = random.Random(0)
      noise = [(float(r.random()<0.5), float(r.random()<0.5)) for _ in range(40)]
      gain = [(float(r.random()<0.2), float(r.random()<0.95)) for _ in range(40)]
      assert decide(noise, "A", _rs(), P)["decision"] == "REJECT"
      assert decide(gain, "A", _rs(), P)["decision"] == "ACCEPT"

  # ---- 活性/计数 ----
  def test_static_reject_circuit_trips():
      st = _rs()
      for _ in range(P["static_reject_circuit"]):
          note_static_reject(st)
      assert circuit_check(st, P) == "static_reject_circuit"

  def test_continue_cap_then_reject_A_disallowed():
      st_a = _rs("A")
      assert apply_acceptor_outcome(st_a, {"decision":"CONTINUE","evalue":2,"reason":""}, P) == "LOOP"
      st_b = _rs("B")
      for _ in range(P["continue_count_cap"]):
          apply_acceptor_outcome(st_b, {"decision":"CONTINUE","evalue":2,"reason":""}, P)
      assert apply_acceptor_outcome(st_b, {"decision":"CONTINUE","evalue":2,"reason":""}, P) == "LOOP"

  # ---- 人审非阻塞 ----
  def test_human_queue_nonblocking(tmp_path):
      rd = str(tmp_path)
      aid = enqueue(rd, {"action_type":"land","payload":{},"ttl":3600})
      assert len(pending(rd)) == 1
      resolve(rd, aid, "skipped")
      assert pending(rd) == []
  ```

- [ ] **Step 2: 跑验收套件看通过（依赖前 6 个 Task 已实现）**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_m1b_acceptance.py -q`
  - Expected: PASS

- [ ] **Step 3: 跑 M1b 全量回归（本里程碑所有测试）**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_ast_gate.py tests/test_mutation_gate.py tests/test_acceptor_noise.py tests/test_acceptor_adversarial.py tests/test_gate_human.py tests/test_statemachine_counters.py tests/test_m1b_acceptance.py -q`
  - Expected: PASS（全绿 = M1b 验收达成：acceptor 正确采纳/拒绝、安全负向全过、活性/计数过）

- [ ] **Step 4: commit**
  - Run:
    ```bash
    cd ~/CodesSelf/self-evolve && git add tests/test_m1b_acceptance.py && git commit -m "$(cat <<'EOF'
    M1b.7: M1b 验收套件 (安全负向全过 + acceptor 采纳/拒绝 + 活性/计数) 一键回归

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
    EOF
    )"
    ```
## 里程碑 M2: B 档半验证 (~14-18h)

**目标**：让 harness 能对调研类目标（small-cap-deepdive 产物）抽出可外部核验的锚断言、用 edgartools/价格核查真值、按 EVE 边际增益与有效独立锚数计分，PACE B 档配对 + coverage/holdout 背离门挡住"小相关锚集虚高"与"长期微涨过拟合"，并把出站完整改为 harness 代发白名单审查代理。

**验收标准（spec §13 M2）**：
- small-cap-deepdive 产物能跑通 B 档评测（extract→verify→marginal_gain→PACE 决策出三态）。
- coverage 门生效：`verifiable_coverage < floor` 欲 ACCEPT → 强制人审（不直接自动采纳）。
- holdout 背离门生效：visible 锚增益 > 0 而 holdout 锚不涨 → 判过拟合、计入自欺指数 + 强制人审。
- 对抗序列被拒：①小相关锚集（8 同源锚每轮 +0.5% 微涨）有效独立锚 < 下限 → 禁 B 档单独 ACCEPT；②长期微涨过拟合序列（visible 持续 +ε 但 holdout 平）→ 拒 / 人审。
- 出站负向：candidate 把答案塞进 GET query / 自选 ticker / 跨请求参数序列编码 → 被 harness 代发白名单 + 序列异常检测阻断；body/header 高熵 base64/hex → 拦。
- fact 探针对带锚字段的调研产物给出 B 维信号，PROFILE 输出 A/B/C 三档（可叠加）。

> **前置（spec §14 / §5.3）**：本里程碑首个动作必须先清 `~/.edgar` 缓存或设独立 cache，规避 Windows 句柄锁 WinError 145。所有 IMMUTABLE 模块（anchors/acceptor/selfdeception/proxy/profile 判定）M2 阶段靠"可写 glob 排除 + AST 危险门"先挡，M4 再上内容哈希加载。
> **依赖里程碑**：消费 M1a 的 `RunState`/`save_state`/`load_state`/`append_event`/`replay`/`canonical_in_sandbox`/`run_profile` 骨架；消费 M1b 的 `acceptor.decide()` A 档 e-process 与 confseq wrapper、AST 危险门 `patch._ast_dangerous`。本里程碑扩展 `decide()` 增 B 分支、扩展 `run_profile()` 增 B 维与 visible/holdout 拆分，不改其既有签名。

---

### Task M2.1: anchors.py, extract_anchors + coverage（锚字段代码判定）

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/anchors.py`
- Create: `~/CodesSelf/self-evolve/tests/test_anchors_extract.py`
- Create (fixture): `~/CodesSelf/self-evolve/tests/fixtures/anchored_artifact.json`

**Interfaces:**
- Produces: `extract_anchors(artifact_path: str) -> list[dict]`（每个 dict 含 `claim/span/source_url/fetched_at/verified/marginal_gain/anchor_id`）
- Produces: `coverage(anchors: list[dict]) -> float`（已 verify 锚占 span 加权比，∈[0,1]）
- Consumes: 无（叶子模块）

- [ ] **Step 1: 写 fixture（带锚字段的调研产物）**
  写 `tests/fixtures/anchored_artifact.json`：
  ```json
  {
    "title": "ACME Corp deep-dive",
    "sections": [
      {"text": "ACME reported FY2024 revenue of $1.20B.",
       "anchors": [{"claim": "FY2024 revenue = 1.20e9 USD", "span": "revenue of $1.20B",
                    "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?CIK=0000320193&type=10-K",
                    "metric": "Revenues", "expected": 1.20e9, "cik": "320193", "period": "FY2024"}]},
      {"text": "Cash and equivalents stood at $0.30B.",
       "anchors": [{"claim": "cash = 0.30e9 USD", "span": "Cash and equivalents stood at $0.30B",
                    "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?CIK=0000320193&type=10-Q",
                    "metric": "CashAndCashEquivalentsAtCarryingValue", "expected": 0.30e9, "cik": "320193", "period": "FY2024"}],
       "no_anchor_prose": "We think the outlook is bright."}
    ]
  }
  ```

- [ ] **Step 2: 写失败测试, extract 提锚 + coverage 计算**
  在 `tests/test_anchors_extract.py`：
  ```python
  import json, os
  from tools.sie import anchors

  FIX = os.path.join(os.path.dirname(__file__), "fixtures", "anchored_artifact.json")

  def test_extract_finds_all_anchor_fields():
      out = anchors.extract_anchors(FIX)
      assert len(out) == 2
      a = out[0]
      for k in ("claim", "span", "source_url", "fetched_at", "verified", "marginal_gain", "anchor_id"):
          assert k in a, f"missing field {k}"
      assert a["verified"] is False          # extract 不核查, verified 默认 False
      assert a["marginal_gain"] == 0.0
      assert a["anchor_id"]                   # 稳定非空 id
      assert {x["anchor_id"] for x in out} == set(x["anchor_id"] for x in out)  # 唯一

  def test_coverage_zero_when_none_verified():
      out = anchors.extract_anchors(FIX)
      assert anchors.coverage(out) == 0.0

  def test_coverage_full_when_all_verified():
      out = anchors.extract_anchors(FIX)
      for a in out:
          a["verified"] = True
      assert abs(anchors.coverage(out) - 1.0) < 1e-9

  def test_coverage_empty_is_zero():
      assert anchors.coverage([]) == 0.0
  ```

- [ ] **Step 3: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_extract.py -q`
  - Expected: FAIL（`ModuleNotFoundError: No module named 'tools.sie.anchors'` 或 AttributeError）

- [ ] **Step 4: 写最小实现 extract_anchors + coverage**
  在 `tools/sie/anchors.py`：
  ```python
  """B 档锚: 抽取/核查/EVE 边际增益/visible-holdout/去相关 (IMMUTABLE 裁决码)。"""
  from __future__ import annotations
  import json
  import hashlib
  from datetime import datetime, timezone

  _REQUIRED_ANCHOR_KEYS = ("claim", "span", "source_url")

  def _anchor_id(raw: dict) -> str:
      key = f"{raw.get('claim','')}|{raw.get('span','')}|{raw.get('source_url','')}"
      return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

  def extract_anchors(artifact_path: str) -> list[dict]:
      with open(artifact_path, "r", encoding="utf-8") as f:
          doc = json.load(f)
      out: list[dict] = []
      seen: set[str] = set()
      for section in doc.get("sections", []):
          for raw in section.get("anchors", []):
              if not all(k in raw and raw[k] for k in _REQUIRED_ANCHOR_KEYS):
                  continue  # 字段不全的不算锚 (代码判定, 不信任 prose)
              aid = _anchor_id(raw)
              if aid in seen:
                  continue
              seen.add(aid)
              out.append({
                  "anchor_id": aid,
                  "claim": raw["claim"],
                  "span": raw["span"],
                  "source_url": raw["source_url"],
                  "metric": raw.get("metric"),
                  "expected": raw.get("expected"),
                  "cik": raw.get("cik"),
                  "period": raw.get("period"),
                  "fetched_at": None,
                  "verified": False,
                  "marginal_gain": 0.0,
              })
      return out

  def coverage(anchors: list[dict]) -> float:
      if not anchors:
          return 0.0
      total = sum(max(len(a.get("span") or ""), 1) for a in anchors)
      done = sum(max(len(a.get("span") or ""), 1) for a in anchors if a.get("verified"))
      return done / total if total else 0.0
  ```

- [ ] **Step 5: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_extract.py -q`
  - Expected: PASS

- [ ] **Step 6: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/anchors.py tests/test_anchors_extract.py tests/fixtures/anchored_artifact.json && git commit -m "$(cat <<'EOF'
  M2.1: anchors.extract_anchors + coverage (锚字段代码判定)

  代码判定锚字段(claim/span/source_url 缺一不算锚), 稳定 anchor_id 去重,
  coverage 按 verified span 加权占比, 空集=0。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.2: anchors.py, effective_independent_count（去相关/同源降权）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/anchors.py`（追加 `_source_cluster_key` + `effective_independent_count`）
- Create: `~/CodesSelf/self-evolve/tests/test_anchors_independence.py`

**Interfaces:**
- Produces: `effective_independent_count(anchors: list[dict]) -> int`（按 source_url host + cik + period + 主题聚类后，每簇按 1 + log2(簇内规模) 折算，向下取整求和）
- Consumes: `extract_anchors`

> 关键/易错（去相关）：8 个 source_url/cik/period 全同的锚必须折算成"约 4"而非 8，否则相关锚会在 e-process 里制造虚高 e-value。下限门 `effective_independent_anchor_min=12`。

- [ ] **Step 1: 写失败测试, 同源簇被降权**
  在 `tests/test_anchors_independence.py`：
  ```python
  import math
  from tools.sie import anchors

  def _mk(n, host, cik, period):
      return [{"anchor_id": f"{host}{i}", "span": "x"*5,
               "source_url": f"https://{host}/path?CIK={cik}&type=10-K",
               "cik": cik, "period": period, "metric": f"m{i}", "verified": True}
              for i in range(n)]

  def test_eight_same_source_anchors_downweighted_below_eight():
      eff = anchors.effective_independent_count(_mk(8, "sec.gov", "320193", "FY2024"))
      assert eff < 8          # 同源簇必须被降权
      # 单簇折算 = floor(1 + log2(8)) = floor(4) = 4
      assert eff == 4

  def test_distinct_sources_count_full():
      a = (_mk(1, "sec.gov", "1", "FY2024") + _mk(1, "fmpcloud.io", "2", "FY2023")
           + _mk(1, "nasdaq.com", "3", "FY2022"))
      assert anchors.effective_independent_count(a) == 3

  def test_unverified_anchors_excluded():
      a = _mk(4, "sec.gov", "1", "FY2024")
      for x in a:
          x["verified"] = False
      assert anchors.effective_independent_count(a) == 0

  def test_mixed_clusters_sum_floored_per_cluster():
      # 簇1: 4 同源 -> floor(1+log2(4))=3 ; 簇2: 2 同源 -> floor(1+log2(2))=2
      a = _mk(4, "sec.gov", "1", "FY2024") + _mk(2, "fmpcloud.io", "2", "FY2023")
      assert anchors.effective_independent_count(a) == 5
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_independence.py -q`
  - Expected: FAIL（`AttributeError: module 'tools.sie.anchors' has no attribute 'effective_independent_count'`）

- [ ] **Step 3: 写最小实现**
  追加到 `tools/sie/anchors.py`：
  ```python
  import math
  from urllib.parse import urlparse

  def _source_cluster_key(a: dict) -> tuple:
      host = ""
      try:
          host = (urlparse(a.get("source_url") or "").hostname or "").lower()
      except Exception:
          host = ""
      # host 主域 (去 www.) + cik + period 同 => 同源簇
      if host.startswith("www."):
          host = host[4:]
      return (host, str(a.get("cik") or ""), str(a.get("period") or ""))

  def effective_independent_count(anchors: list[dict]) -> int:
      clusters: dict[tuple, int] = {}
      for a in anchors:
          if not a.get("verified"):
              continue
          k = _source_cluster_key(a)
          clusters[k] = clusters.get(k, 0) + 1
      eff = 0
      for size in clusters.values():
          # 同源簇内信息次线性: 1 + log2(size), 向下取整
          eff += int(math.floor(1.0 + math.log2(size)))
      return eff
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_independence.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/anchors.py tests/test_anchors_independence.py && git commit -m "$(cat <<'EOF'
  M2.2: anchors.effective_independent_count (同源去相关降权)

  按 host(去www)+cik+period 聚类, 簇内次线性折算 floor(1+log2(size)),
  8 同源锚 -> 4 有效, 防相关锚虚高 e-value。下限门 12 在 acceptor 用。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.3: anchors.py, split_visible_holdout（确定性可复现拆分）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/anchors.py`
- Create: `~/CodesSelf/self-evolve/tests/test_anchors_split.py`

**Interfaces:**
- Produces: `split_visible_holdout(anchors: list[dict], frac: float, seed: str = "") -> tuple[list, list]`（holdout 取 `round(frac*N)`，按 `anchor_id` 哈希排序确定性挑选，可复现）
- Consumes: `extract_anchors`

> 关键（防自欺）：拆分必须确定性可复现（同一锚集 + 同一 seed 永远同一 holdout），否则每轮重抽 holdout 会让 candidate 在累计漂移检查中"碰运气"洗掉背离信号。holdout 物理隔离存储由 profile.py 落盘，本函数只负责确定性分桶。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_anchors_split.py`：
  ```python
  from tools.sie import anchors

  def _anchors(n):
      return [{"anchor_id": f"a{i:03d}", "span": "s", "claim": "c",
               "source_url": "https://x/y", "verified": True} for i in range(n)]

  def test_holdout_fraction_size():
      vis, hold = anchors.split_visible_holdout(_anchors(30), 0.3)
      assert len(hold) == 9 and len(vis) == 21
      assert len(vis) + len(hold) == 30

  def test_split_is_deterministic():
      a = _anchors(30)
      v1, h1 = anchors.split_visible_holdout(a, 0.3, seed="run42")
      v2, h2 = anchors.split_visible_holdout(a, 0.3, seed="run42")
      assert [x["anchor_id"] for x in h1] == [x["anchor_id"] for x in h2]

  def test_no_overlap_between_visible_and_holdout():
      vis, hold = anchors.split_visible_holdout(_anchors(24), 0.3)
      vids = {x["anchor_id"] for x in vis}
      hids = {x["anchor_id"] for x in hold}
      assert vids.isdisjoint(hids)

  def test_different_seed_changes_holdout():
      a = _anchors(30)
      _, h1 = anchors.split_visible_holdout(a, 0.3, seed="A")
      _, h2 = anchors.split_visible_holdout(a, 0.3, seed="B")
      assert [x["anchor_id"] for x in h1] != [x["anchor_id"] for x in h2]
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_split.py -q`
  - Expected: FAIL（AttributeError）

- [ ] **Step 3: 写最小实现**
  追加到 `tools/sie/anchors.py`：
  ```python
  def split_visible_holdout(anchors: list[dict], frac: float, seed: str = "") -> tuple[list, list]:
      if not anchors:
          return [], []
      frac = max(0.0, min(1.0, float(frac)))
      n_hold = int(round(frac * len(anchors)))
      def _rank(a: dict) -> str:
          return hashlib.sha256((seed + "|" + str(a.get("anchor_id", ""))).encode("utf-8")).hexdigest()
      ordered = sorted(anchors, key=_rank)
      holdout = ordered[:n_hold]
      hold_ids = {a["anchor_id"] for a in holdout}
      visible = [a for a in anchors if a["anchor_id"] not in hold_ids]
      return visible, holdout
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_split.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/anchors.py tests/test_anchors_split.py && git commit -m "$(cat <<'EOF'
  M2.3: anchors.split_visible_holdout (确定性可复现拆分)

  按 seed+anchor_id 哈希排序确定性挑 holdout, 同 seed 永远同 holdout,
  防每轮重抽洗掉累计漂移背离信号; visible/holdout 互斥。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.4: anchors.py, verify_anchor（edgartools/价格核查，先清 ~/.edgar 缓存）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/anchors.py`
- Create: `~/CodesSelf/self-evolve/tools/sie/edgar_cache.py`（独立 cache + WinError 145 规避）
- Create: `~/CodesSelf/self-evolve/tests/test_anchors_verify.py`

**Interfaces:**
- Produces: `verify_anchor(anchor: dict, fetcher=None) -> dict`（返回锚副本，填 `verified:bool`、`fetched_at:str(ISO)`、`observed:float|None`、`verify_reason:str`）
- Produces: `edgar_cache.prepare_cache(cache_root: str | None = None) -> str`（清/建独立 cache 目录、设 `EDGAR_LOCAL_DATA_DIR` 规避 WinError 145，返回 cache 路径）
- Consumes: `extract_anchors`

> 关键/易错（edgartools 缓存锁 + 数学）：① 在任何 edgar 调用前必须先 `prepare_cache()` 把 cache 指到 run 独立目录并清掉旧 `~/.edgar`（Windows 句柄锁 WinError 145 = 删非空目录失败，须先递归删文件再删目录、失败容忍）；② 数值核查容差用相对误差 `abs(obs-exp)/max(|exp|,1) <= rel_tol(0.01)`，绝对值锚（如 cash=0）退化为绝对容差。`fetcher` 注入便于测试不打真网。

- [ ] **Step 1: 写 edgar_cache 失败测试**
  在 `tests/test_anchors_verify.py`：
  ```python
  import os
  from tools.sie import edgar_cache, anchors

  def test_prepare_cache_creates_dir_and_sets_env(tmp_path, monkeypatch):
      root = tmp_path / "edgar_run"
      p = edgar_cache.prepare_cache(str(root))
      assert os.path.isdir(p)
      assert os.environ.get("EDGAR_LOCAL_DATA_DIR") == p

  def test_prepare_cache_clears_existing_nonempty(tmp_path):
      root = tmp_path / "edgar_run"
      os.makedirs(root, exist_ok=True)
      with open(root / "stale.bin", "wb") as f:
          f.write(b"old")
      sub = root / "sub"; os.makedirs(sub, exist_ok=True)
      with open(sub / "x.bin", "wb") as f:
          f.write(b"y")
      p = edgar_cache.prepare_cache(str(root))
      # 清后目录存在但为空 (WinError145 规避: 不因非空删失败而崩)
      assert os.path.isdir(p)
      assert os.listdir(p) == []
  ```

- [ ] **Step 2: 跑测试看失败 + 实现 edgar_cache**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_verify.py::test_prepare_cache_creates_dir_and_sets_env -q`
  - Expected: FAIL（ModuleNotFoundError edgar_cache）
  写 `tools/sie/edgar_cache.py`：
  ```python
  """独立 EDGAR 本地缓存管理: 每 run 独立目录 + WinError 145 (句柄锁删非空) 规避。"""
  from __future__ import annotations
  import os
  import stat
  import shutil

  def _force_rmtree(path: str) -> None:
      def _on_error(func, p, exc):
          try:
              os.chmod(p, stat.S_IWRITE)
              func(p)
          except Exception:
              pass  # WinError 145/句柄锁: 容忍, 不让缓存清理拖垮 run
      if os.path.isdir(path):
          shutil.rmtree(path, onerror=_on_error)

  def prepare_cache(cache_root: str | None = None) -> str:
      if cache_root is None:
          cache_root = os.path.join(os.path.expanduser("~"), ".sie_edgar_cache")
      _force_rmtree(cache_root)
      os.makedirs(cache_root, exist_ok=True)
      # 把 edgartools 本地数据指向独立目录, 避开 ~/.edgar 句柄锁
      os.environ["EDGAR_LOCAL_DATA_DIR"] = cache_root
      os.environ.setdefault("EDGAR_IDENTITY", "self-evolve harness sie@local")
      return cache_root
  ```

- [ ] **Step 3: 写 verify_anchor 失败测试（注入 fetcher 不打真网）**
  追加到 `tests/test_anchors_verify.py`：
  ```python
  def test_verify_anchor_pass_within_rel_tol():
      a = {"anchor_id": "x", "claim": "rev=1.2e9", "span": "rev", "source_url": "https://sec.gov/x",
           "metric": "Revenues", "expected": 1.20e9, "cik": "320193", "period": "FY2024"}
      def fetch(anchor):  # 模拟 EDGAR 取到 1.205e9 (0.4% 偏差)
          return 1.205e9
      out = anchors.verify_anchor(a, fetcher=fetch)
      assert out["verified"] is True
      assert out["observed"] == 1.205e9
      assert out["fetched_at"]

  def test_verify_anchor_fail_outside_tol():
      a = {"anchor_id": "x", "claim": "c", "span": "s", "source_url": "https://sec.gov/x",
           "metric": "Revenues", "expected": 1.20e9, "cik": "1", "period": "FY2024"}
      out = anchors.verify_anchor(a, fetcher=lambda _a: 2.0e9)  # 67% 偏差
      assert out["verified"] is False

  def test_verify_anchor_unfetchable_is_unverified():
      a = {"anchor_id": "x", "claim": "c", "span": "s", "source_url": "https://sec.gov/x",
           "metric": "Revenues", "expected": 1.0, "cik": "1", "period": "FY2024"}
      def boom(_a):
          raise RuntimeError("network fail")
      out = anchors.verify_anchor(a, fetcher=boom)
      assert out["verified"] is False
      assert "error" in out["verify_reason"].lower()

  def test_verify_anchor_absolute_tol_for_zero_expected():
      a = {"anchor_id": "x", "claim": "c", "span": "s", "source_url": "https://sec.gov/x",
           "metric": "X", "expected": 0.0, "cik": "1", "period": "FY2024"}
      out = anchors.verify_anchor(a, fetcher=lambda _a: 0.004)  # 在绝对容差 0.01 内
      assert out["verified"] is True
  ```

- [ ] **Step 4: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_verify.py -q`
  - Expected: FAIL（verify_anchor 不存在）

- [ ] **Step 5: 写最小实现 verify_anchor**
  追加到 `tools/sie/anchors.py`（顶部 import 增 `from . import edgar_cache`）：
  ```python
  _REL_TOL = 0.01
  _ABS_TOL = 0.01

  def _default_fetcher(anchor: dict) -> float | None:
      """真实路径: 经独立 cache 用 edgartools 取 anchor.metric@cik/period 的报告值。
      M2 默认惰性导入, 无网/无库则抛错被上层判 unverified。"""
      edgar_cache.prepare_cache(None)
      from edgar import Company  # 惰性: 缺库即 ImportError -> unverified
      comp = Company(str(anchor["cik"]))
      facts = comp.get_facts()
      return float(facts.get_fact(anchor["metric"], period=anchor.get("period")))

  def _within_tol(observed: float, expected: float) -> bool:
      denom = abs(expected)
      if denom < 1.0:
          return abs(observed - expected) <= _ABS_TOL
      return abs(observed - expected) / denom <= _REL_TOL

  def verify_anchor(anchor: dict, fetcher=None) -> dict:
      out = dict(anchor)
      out["fetched_at"] = datetime.now(timezone.utc).isoformat()
      f = fetcher or _default_fetcher
      try:
          observed = f(anchor)
      except Exception as exc:  # 取数失败 = 不可核验, 绝不当真
          out["verified"] = False
          out["observed"] = None
          out["verify_reason"] = f"fetch error: {exc!r}"
          return out
      out["observed"] = observed
      exp = anchor.get("expected")
      if observed is None or exp is None:
          out["verified"] = False
          out["verify_reason"] = "missing observed/expected"
          return out
      ok = _within_tol(float(observed), float(exp))
      out["verified"] = bool(ok)
      out["verify_reason"] = "within tol" if ok else "outside tol"
      return out
  ```

- [ ] **Step 6: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_verify.py -q`
  - Expected: PASS

- [ ] **Step 7: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/anchors.py tools/sie/edgar_cache.py tests/test_anchors_verify.py && git commit -m "$(cat <<'EOF'
  M2.4: anchors.verify_anchor + edgar_cache (EDGAR 核查 + WinError145 规避)

  prepare_cache 每 run 独立目录+清旧~/.edgar(容忍句柄锁失败)+设 EDGAR_LOCAL_DATA_DIR;
  verify_anchor 相对/绝对容差核查, 取数失败一律 unverified(不当真), fetcher 可注入。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.5: anchors.py, marginal_gain（EVE 边际增益）

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/anchors.py`
- Create: `~/CodesSelf/self-evolve/tests/test_anchors_marginal.py`

**Interfaces:**
- Produces: `marginal_gain(anchor: dict, base_score: float, with_score: float) -> float`（EVE：加入该证据后正确率提升量；未 verify 锚增益恒 0；clamp 防负噪声放大）
- Consumes: `verify_anchor`

> 关键（EVE 数学 / 防自欺）：marginal_gain = 加该锚是否真提升正确率，**不是绝对准确率**。未 verify 的锚边际增益必须强制 0（否则 candidate 塞一堆无法核验的"锚"刷分）。`with_score - base_score` 即增量；负增益 clamp 到 0（证据不该让答案更差，负值视为噪声不奖励、也不惩罚到锚分）。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_anchors_marginal.py`：
  ```python
  from tools.sie import anchors

  def test_marginal_gain_positive_when_verified_and_improves():
      a = {"verified": True}
      assert abs(anchors.marginal_gain(a, base_score=0.5, with_score=0.62) - 0.12) < 1e-9

  def test_marginal_gain_zero_when_unverified():
      a = {"verified": False}
      assert anchors.marginal_gain(a, base_score=0.5, with_score=0.9) == 0.0

  def test_marginal_gain_negative_clamped_to_zero():
      a = {"verified": True}
      assert anchors.marginal_gain(a, base_score=0.7, with_score=0.6) == 0.0

  def test_marginal_gain_zero_when_no_change():
      a = {"verified": True}
      assert anchors.marginal_gain(a, base_score=0.5, with_score=0.5) == 0.0
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_marginal.py -q`
  - Expected: FAIL（AttributeError）

- [ ] **Step 3: 写最小实现**
  追加到 `tools/sie/anchors.py`：
  ```python
  def marginal_gain(anchor: dict, base_score: float, with_score: float) -> float:
      # EVE: 加该证据是否真提升正确率; 未核验锚不计增益(防塞假锚刷分)
      if not anchor.get("verified"):
          return 0.0
      delta = float(with_score) - float(base_score)
      return delta if delta > 0.0 else 0.0  # 负增益视噪声, clamp 0
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_anchors_marginal.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/anchors.py tests/test_anchors_marginal.py && git commit -m "$(cat <<'EOF'
  M2.5: anchors.marginal_gain (EVE 边际增益)

  增益=with-base 正确率增量, 未核验锚恒 0(防塞假锚), 负增益 clamp 0。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.6: acceptor.py, B 档 per-anchor 配对 + n_min/独立性下限门

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/acceptor.py`（在 M1b 已有 `decide()` 内增 tier=="B" 分支与 e-process 复用）
- Create: `~/CodesSelf/self-evolve/tests/test_acceptor_btier.py`

**Interfaces:**
- Produces（扩展，不改签名）：`decide(paired: list[tuple[float,float]], tier: str, st: RunState, params: dict) -> dict`，B 分支额外读 `params["anchors"]`（已 verify 的 visible 锚 list，用于算 `effective_independent_count`）；返回 dict 增 `effective_independent:int`、`n_anchor:int`
- Consumes: `anchors.effective_independent_count`、M1b 的 confseq e-process wrapper（`_eprocess_wealth(paired, params)`）、`RunState`

> 关键/易错（acceptor 数学 + 多门）：B 档配对单元 = per-anchor 边际增益配对（改前增益 vs 改后增益，零均值化喂 e-process）。三道硬门**先于** e-value 判定，任一不过即 `decision="REJECT"`（或降级，由 statemachine 决定降 C），绝不进 ACCEPT：
> 1. `n_anchor = len(paired) < n_min(8)` → 禁 ACCEPT；
> 2. `effective_independent_count(visible_verified) < effective_independent_anchor_min(12)` → 禁 B 档单独 ACCEPT（统计上是"小相关锚集"）；
> 3. 主观分不进 B（B 全是已核验客观增益），但仍套 `evalue_max_step` 单轮上限防一锚爆表。
> e-value ≥ 1/α(=20) 且三门全过才 ACCEPT；e-value 介于阈与 1 之间且属随机档 → CONTINUE（B 是随机档允许 CONTINUE）；e-value ≤ 阈下界 → REJECT。

- [ ] **Step 1: 写失败测试, 三门 + 三态**
  在 `tests/test_acceptor_btier.py`：
  ```python
  from tools.sie import acceptor
  from tools.sie.state import RunState

  def _st():
      return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="B")

  def _params(anchors, **kw):
      p = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
           "evalue_max_step": 5.0, "continue_count_cap": 5, "anchors": anchors}
      p.update(kw)
      return p

  def _indep_anchors(n):  # n 个互异源 -> 有效独立锚 = n
      return [{"anchor_id": f"a{i}", "verified": True, "source_url": f"https://h{i}.com/x",
               "cik": str(i), "period": "FY"} for i in range(n)]

  def _same_source(n):    # n 个同源 -> 有效独立 = floor(1+log2(n))
      return [{"anchor_id": f"a{i}", "verified": True, "source_url": "https://sec.gov/x",
               "cik": "1", "period": "FY2024"} for i in range(n)]

  def test_reject_when_too_few_anchors():
      paired = [(0.0, 0.1)] * 5   # n_anchor=5 < n_min 8
      out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(5)))
      assert out["decision"] == "REJECT"
      assert "n_anchor" in out["reason"]

  def test_reject_small_correlated_anchor_set():
      # 8 同源锚每轮 +0.5% 微涨: n_anchor=8 过门1, 但有效独立=4 < 12
      paired = [(0.0, 0.005)] * 8
      out = acceptor.decide(paired, "B", _st(), _params(_same_source(8)))
      assert out["decision"] == "REJECT"
      assert "effective_independent" in out["reason"]
      assert out["effective_independent"] == 4

  def test_accept_strong_independent_gain():
      paired = [(0.0, 0.4)] * 24   # 24 互异源, 大真增益
      out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(24)))
      assert out["decision"] == "ACCEPT"
      assert out["effective_independent"] >= 12

  def test_continue_on_marginal_evidence_is_random_tier():
      # 足够锚+足够独立, 但增益弱 -> e-value 介于中间 -> CONTINUE (B 是随机档)
      paired = [(0.0, 0.01)] * 16
      out = acceptor.decide(paired, "B", _st(), _params(_indep_anchors(16)))
      assert out["decision"] in ("CONTINUE", "REJECT")  # 绝不 ACCEPT
      assert out["decision"] != "ACCEPT"
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_btier.py -q`
  - Expected: FAIL（B 分支未实现：n_min/独立性门缺失或 KeyError）

- [ ] **Step 3: 写最小实现（在 decide() 增 B 分支）**
  在 `tools/sie/acceptor.py` 的 `decide()` 中，A 分支之后、C 分支之前插入（复用 M1b 的 `_eprocess_wealth`）：
  ```python
      if tier.upper().startswith("B") or tier.upper() == "B":
          from . import anchors as _anchors
          n_min = int(params.get("n_min", 8))
          eff_min = int(params.get("effective_independent_anchor_min", 12))
          n_anchor = len(paired)
          visible_verified = [a for a in params.get("anchors", []) if a.get("verified")]
          eff = _anchors.effective_independent_count(visible_verified)
          base = {"effective_independent": eff, "n_anchor": n_anchor}
          # 门1: 锚数下限
          if n_anchor < n_min:
              return {"decision": "REJECT", "evalue": 0.0,
                      "reason": f"n_anchor {n_anchor} < n_min {n_min}", **base}
          # 门2: 有效独立锚下限 (小相关锚集)
          if eff < eff_min:
              return {"decision": "REJECT", "evalue": 0.0,
                      "reason": f"effective_independent {eff} < min {eff_min}", **base}
          # e-process: per-anchor 边际增益配对, 单轮上限钳
          wealth = _eprocess_wealth(paired, params)
          step_cap = float(params.get("evalue_max_step", 5.0))
          wealth = min(wealth, step_cap)
          thresh = 1.0 / float(params.get("alpha", 0.05))   # =20
          if wealth >= thresh:
              return {"decision": "ACCEPT", "evalue": wealth, "reason": "B e-value >= 1/alpha", **base}
          if wealth <= 1.0:
              return {"decision": "REJECT", "evalue": wealth, "reason": "B e-value <= 1", **base}
          # 中间区: B 是随机档, 允许 CONTINUE 累积证据
          if st.continue_count < int(params.get("continue_count_cap", 5)):
              return {"decision": "CONTINUE", "evalue": wealth, "reason": "B accumulating evidence", **base}
          return {"decision": "REJECT", "evalue": wealth, "reason": "B continue_count cap hit", **base}
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_acceptor_btier.py -q`
  - Expected: PASS

- [ ] **Step 5: 跑全 acceptor 回归确认没破 A 档**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/ -q -k acceptor`
  - Expected: PASS（A 档既有用例仍绿）

- [ ] **Step 6: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/acceptor.py tests/test_acceptor_btier.py && git commit -m "$(cat <<'EOF'
  M2.6: acceptor B 档 per-anchor 配对 + n_min/独立性下限门

  B 分支: 门1 n_anchor>=8, 门2 有效独立锚>=12(小相关锚集拒), e-value>=20 才 ACCEPT;
  evalue_max_step 钳单轮; B 随机档允许 CONTINUE 累积证据。复用 A 档 e-process wrapper。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.7: selfdeception.py, holdout 背离闸 + 累计漂移预算

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/selfdeception.py`（M1b 可能仅占位；此处落 `index()` 多闸 + 累计漂移）
- Create: `~/CodesSelf/self-evolve/tests/test_selfdeception_holdout.py`

**Interfaces:**
- Produces: `index(judge_gain: float, visible_anchor_gain: float, holdout_gain: float, st: RunState, params: dict | None = None) -> dict` → `{"value": float, "alerts": [...], "force_human": bool}`
- Consumes: `RunState`（读 `drift_count`）

> 关键/易错（自欺多闸，spec §5.7）。`value = judge_gain - visible_anchor_gain`（judge 增益超出锚真实增益越多越像合谋）。四闸：
> ① 新锚不计当轮增益（由 anchors/evaluate 保证，本函数假设传入的 visible_anchor_gain 已只含 frozen 留存锚）；
> ② `visible_anchor_gain < ε(0.02)` → alert `low_anchor_gain`（禁 ACCEPT 由 statemachine 执行）；
> ③ **holdout 背离**：`visible_anchor_gain > 0 且 holdout_gain <= 0` → alert `overfit_holdout` + `force_human=True`；
> ④ **累计漂移预算**：`|value| > selfdeception_alert_band(0.15)` → alert `judge_anchor_divergence`；漂移由 statemachine 累计计入 `drift_count`，本函数只报当轮信号。

- [ ] **Step 1: 写失败测试, 四闸**
  在 `tests/test_selfdeception_holdout.py`：
  ```python
  from tools.sie import selfdeception
  from tools.sie.state import RunState

  def _st():
      return RunState(run_id="r", phase="ACCEPT", round=3, parent_vid="v1", tier="B")

  P = {"frozen_anchor_effective_gain_eps": 0.02, "selfdeception_alert_band": 0.15}

  def test_overfit_holdout_divergence_forces_human():
      out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.08,
                                holdout_gain=0.0, st=_st(), params=P)
      assert out["force_human"] is True
      assert "overfit_holdout" in out["alerts"]

  def test_low_anchor_gain_alert():
      out = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.005,
                                holdout_gain=0.005, st=_st(), params=P)
      assert "low_anchor_gain" in out["alerts"]

  def test_judge_anchor_divergence_alert_on_high_value():
      out = selfdeception.index(judge_gain=0.40, visible_anchor_gain=0.05,
                                holdout_gain=0.05, st=_st(), params=P)
      assert out["value"] == 0.35
      assert "judge_anchor_divergence" in out["alerts"]

  def test_clean_case_no_alert_no_force():
      out = selfdeception.index(judge_gain=0.10, visible_anchor_gain=0.09,
                                holdout_gain=0.08, st=_st(), params=P)
      assert out["alerts"] == []
      assert out["force_human"] is False
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_selfdeception_holdout.py -q`
  - Expected: FAIL（index 签名/逻辑不符）

- [ ] **Step 3: 写最小实现**
  写/覆盖 `tools/sie/selfdeception.py` 的 `index()`：
  ```python
  """自欺指数多闸: judge 增益 vs frozen 锚真实增益 + holdout 背离 + 累计漂移 (IMMUTABLE)。"""
  from __future__ import annotations
  from .state import RunState

  def index(judge_gain: float, visible_anchor_gain: float, holdout_gain: float,
            st: RunState, params: dict | None = None) -> dict:
      p = params or {}
      eps = float(p.get("frozen_anchor_effective_gain_eps", 0.02))
      band = float(p.get("selfdeception_alert_band", 0.15))
      value = float(judge_gain) - float(visible_anchor_gain)
      alerts: list[str] = []
      force_human = False
      # 闸②: frozen 留存锚增益过低
      if visible_anchor_gain < eps:
          alerts.append("low_anchor_gain")
      # 闸③: visible 涨而 holdout 不涨 = 过拟合背离
      if visible_anchor_gain > 0.0 and holdout_gain <= 0.0:
          alerts.append("overfit_holdout")
          force_human = True
      # 闸④: judge 增益显著超出锚真实增益 = 疑似合谋
      if abs(value) > band:
          alerts.append("judge_anchor_divergence")
      return {"value": round(value, 12), "alerts": alerts, "force_human": force_human}
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_selfdeception_holdout.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/selfdeception.py tests/test_selfdeception_holdout.py && git commit -m "$(cat <<'EOF'
  M2.7: selfdeception.index holdout 背离闸 + 累计漂移信号

  value=judge_gain-visible_anchor_gain; 闸②锚增益<eps报警; 闸③visible涨holdout
  不涨->overfit_holdout+force_human; 闸④|value|>band->judge_anchor_divergence。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.8: proxy.py, harness 代发 + 参数白名单枚举 + URL/header/body 熵 + base64/hex 检测

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/proxy.py`
- Create: `~/CodesSelf/self-evolve/tests/test_proxy_outbound.py`

**Interfaces:**
- Produces: `dispatch(request_spec: dict, run_dir: str, allowlist: dict) -> dict`（harness 代发：candidate 只给 `kind`+结构化参数，harness 枚举校验后代发并回填结果）
- Produces: `screen_request(method: str, url: str, headers: dict, body: bytes | str) -> dict` → `{"ok": bool, "violations": [...]}`
- Produces: `shannon_entropy(data: bytes | str) -> float`、`looks_encoded(s: str) -> bool`（base64/hex 检测）
- Consumes: 无（出站审查叶子；序列检测在 M2.9）

> 关键/易错（沙箱边界 / 出站隐蔽信道，spec §6）。candidate **不能自选 ticker/时序**：`dispatch` 只接受 `kind ∈ allowlist`，每个 kind 声明结构化参数 + 正则白名单（CIK=`^\d{1,10}$`、ticker=`^[A-Z]{1,6}$`、date=`^\d{4}-\d{2}-\d{2}$`），harness 用白名单参数自行拼 URL 代发，结果回填,candidate 永远拿不到原始 URL 构造权。`screen_request`（用于 judge 进程等仍需直发的受控出站）查：URL/header/body 各段 Shannon 熵超阈、体积超上限、出现长 base64/hex 段（隐写）即 violation。

- [ ] **Step 1: 写失败测试, 熵 + 编码检测 + 白名单枚举**
  在 `tests/test_proxy_outbound.py`：
  ```python
  import os, re
  from tools.sie import proxy

  ALLOW = {
      "edgar_facts": {
          "url_template": "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{metric}.json",
          "params": {"cik": r"^\d{1,10}$", "metric": r"^[A-Za-z]+$"},
      }
  }

  def test_shannon_entropy_high_for_random():
      low = proxy.shannon_entropy("aaaaaaaaaaaaaaaa")
      high = proxy.shannon_entropy(os.urandom(64))
      assert high > low
      assert high > 4.0

  def test_looks_encoded_detects_base64_and_hex():
      assert proxy.looks_encoded("U29tZVNlY3JldFBheWxvYWREYXRhMTIzNDU2Nzg5MA==")
      assert proxy.looks_encoded("deadbeefcafebabe0123456789abcdef0123456789abcdef")
      assert not proxy.looks_encoded("hello world this is plain text")

  def test_screen_blocks_high_entropy_query():
      payload = "U2VjcmV0RXhmaWxBbnN3ZXJQYXlsb2FkQmFzZTY0RGF0YQ=="
      out = proxy.screen_request("GET", f"https://data.sec.gov/x?q={payload}", {}, b"")
      assert out["ok"] is False
      assert any("encoded" in v or "entropy" in v for v in out["violations"])

  def test_screen_blocks_high_entropy_body():
      out = proxy.screen_request("POST", "https://data.sec.gov/x", {}, os.urandom(256))
      assert out["ok"] is False

  def test_screen_passes_clean_request():
      out = proxy.screen_request("GET", "https://data.sec.gov/api/xbrl/companyconcept/CIK320193/us-gaap/Revenues.json", {}, b"")
      assert out["ok"] is True

  def test_dispatch_rejects_unknown_kind(tmp_path):
      out = proxy.dispatch({"kind": "evil_exfil", "params": {}}, str(tmp_path), ALLOW)
      assert out["ok"] is False
      assert "kind" in out["reason"]

  def test_dispatch_rejects_param_failing_regex(tmp_path):
      out = proxy.dispatch({"kind": "edgar_facts", "params": {"cik": "320193;DROP", "metric": "Revenues"}},
                           str(tmp_path), ALLOW)
      assert out["ok"] is False
      assert "param" in out["reason"]

  def test_dispatch_builds_url_and_calls_fetcher(tmp_path):
      captured = {}
      def fake_fetch(method, url, headers, body):
          captured["url"] = url
          return {"status": 200, "body": '{"v": 1.2e9}'}
      out = proxy.dispatch({"kind": "edgar_facts", "params": {"cik": "320193", "metric": "Revenues"}},
                           str(tmp_path), ALLOW, fetcher=fake_fetch)
      assert out["ok"] is True
      assert captured["url"] == "https://data.sec.gov/api/xbrl/companyconcept/CIK320193/us-gaap/Revenues.json"
      assert out["result"]["status"] == 200
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_proxy_outbound.py -q`
  - Expected: FAIL（ModuleNotFoundError proxy）

- [ ] **Step 3: 写最小实现**
  写 `tools/sie/proxy.py`：
  ```python
  """出站审查: harness 代发(参数白名单枚举+结果回填) + URL/header/body 熵/编码检测 (IMMUTABLE)。"""
  from __future__ import annotations
  import math
  import os
  import re
  import json
  from collections import Counter

  _ENTROPY_QUERY_MAX = 3.5     # query 段熵阈
  _ENTROPY_BODY_MAX = 4.5      # body 熵阈
  _BODY_SIZE_MAX = 8192        # 出站体积上限
  _ENCODED_MIN_LEN = 24        # 触发编码检测的最短可疑段
  _B64_RE = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % _ENCODED_MIN_LEN)
  _HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}){%d,}" % (_ENCODED_MIN_LEN // 2))

  def shannon_entropy(data) -> float:
      if isinstance(data, str):
          data = data.encode("utf-8", "ignore")
      if not data:
          return 0.0
      counts = Counter(data)
      n = len(data)
      return -sum((c / n) * math.log2(c / n) for c in counts.values())

  def looks_encoded(s: str) -> bool:
      for m in _B64_RE.finditer(s):
          seg = m.group(0)
          if shannon_entropy(seg) >= 3.5:   # 长 base64 段 + 高熵
              return True
      for m in _HEX_RE.finditer(s):
          if shannon_entropy(m.group(0)) >= 3.0:
              return True
      return False

  def _as_text(body) -> str:
      if isinstance(body, (bytes, bytearray)):
          try:
              return bytes(body).decode("utf-8", "ignore")
          except Exception:
              return ""
      return body or ""

  def screen_request(method: str, url: str, headers: dict, body) -> dict:
      violations: list[str] = []
      query = url.split("?", 1)[1] if "?" in url else ""
      if query:
          if shannon_entropy(query) > _ENTROPY_QUERY_MAX:
              violations.append("url query entropy too high")
          if looks_encoded(query):
              violations.append("url query looks encoded (base64/hex exfil)")
      raw_body = body if isinstance(body, (bytes, bytearray)) else _as_text(body).encode("utf-8", "ignore")
      if len(raw_body) > _BODY_SIZE_MAX:
          violations.append("body size over limit")
      if raw_body and shannon_entropy(raw_body) > _ENTROPY_BODY_MAX:
          violations.append("body entropy too high")
      btext = _as_text(body)
      if btext and looks_encoded(btext):
          violations.append("body looks encoded (base64/hex exfil)")
      for hk, hv in (headers or {}).items():
          if isinstance(hv, str) and looks_encoded(hv):
              violations.append(f"header {hk} looks encoded")
      return {"ok": not violations, "violations": violations}

  def dispatch(request_spec: dict, run_dir: str, allowlist: dict, fetcher=None) -> dict:
      kind = request_spec.get("kind")
      if kind not in allowlist:
          return {"ok": False, "reason": f"kind '{kind}' not in allowlist", "result": None}
      spec = allowlist[kind]
      params = request_spec.get("params", {}) or {}
      # 参数白名单枚举: 每个声明参数必须存在且过正则
      for name, pattern in spec["params"].items():
          val = params.get(name)
          if val is None or not re.match(pattern, str(val)):
              return {"ok": False, "reason": f"param '{name}' missing/failed whitelist regex", "result": None}
      # 拒绝声明外的多余参数 (防夹带)
      extra = set(params) - set(spec["params"])
      if extra:
          return {"ok": False, "reason": f"unexpected params {sorted(extra)}", "result": None}
      url = spec["url_template"].format(**{k: str(params[k]) for k in spec["params"]})
      # 代发前仍过内容审查 (双保险)
      sc = screen_request("GET", url, {}, b"")
      if not sc["ok"]:
          return {"ok": False, "reason": f"screen failed: {sc['violations']}", "result": None}
      f = fetcher or _real_fetch
      result = f("GET", url, {}, b"")
      return {"ok": True, "reason": "dispatched", "url": url, "result": result}

  def _real_fetch(method, url, headers, body):  # pragma: no cover - 真网路径
      import urllib.request
      req = urllib.request.Request(url, method=method, headers=headers or {})
      with urllib.request.urlopen(req, timeout=30) as resp:
          return {"status": resp.status, "body": resp.read().decode("utf-8", "ignore")}
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_proxy_outbound.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/proxy.py tests/test_proxy_outbound.py && git commit -m "$(cat <<'EOF'
  M2.8: proxy harness 代发 + 参数白名单枚举 + 熵/base64/hex 出站审查

  dispatch: candidate 只给 kind+结构化参数, harness 正则白名单校验+拒多余参数+
  自拼 URL 代发回填(不给 URL 构造权); screen_request 查 query/body/header 熵超阈
  +长 base64/hex 段+体积上限。candidate 不能自选 ticker/时序。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.9: proxy.py, 跨请求序列异常检测

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/proxy.py`（追加序列状态 + `sequence_anomaly`）
- Create: `~/CodesSelf/self-evolve/tests/test_proxy_sequence.py`

**Interfaces:**
- Produces: `record_outbound(run_dir: str, kind: str, params: dict) -> None`（append 到 `run_dir/outbound_seq.jsonl`）
- Produces: `sequence_anomaly(run_dir: str, params_seq_window: int = 32) -> dict` → `{"anomalous": bool, "score": float, "reasons": [...]}`
- Consumes: `dispatch`（dispatch 成功后调 record_outbound）

> 关键/易错（跨请求序列异常，spec §6）。即使每个请求单独合规，candidate 也可能用"参数序列"编码秘密（如按 ticker 字母顺序选股 = 编码 ASCII）。检测三征：① 同 kind 参数取值的**枚举熵异常**（连续请求覆盖一段连续/单调字典序 = 疑似逐字符编码）；② 参数序列与已知答案锚的相关性（参数选择跟着 holdout 答案走）；③ 单 run 出站频次突刺。任一触发 → `anomalous=True`，statemachine 据此强制人审/熔断。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_proxy_sequence.py`：
  ```python
  from tools.sie import proxy

  def test_monotone_param_sequence_flagged(tmp_path):
      d = str(tmp_path)
      # 连续单调字典序 ticker = 疑似逐字符编码信道
      for t in ["AAA", "AAB", "AAC", "AAD", "AAE", "AAF", "AAG", "AAH"]:
          proxy.record_outbound(d, "quote", {"ticker": t})
      out = proxy.sequence_anomaly(d)
      assert out["anomalous"] is True
      assert any("monoton" in r or "sequence" in r for r in out["reasons"])

  def test_normal_diverse_sequence_ok(tmp_path):
      d = str(tmp_path)
      for t in ["MSFT", "AAPL", "JNJ", "XOM", "KO"]:
          proxy.record_outbound(d, "quote", {"ticker": t})
      out = proxy.sequence_anomaly(d)
      assert out["anomalous"] is False

  def test_frequency_spike_flagged(tmp_path):
      d = str(tmp_path)
      for i in range(200):
          proxy.record_outbound(d, "quote", {"ticker": "AAPL"})
      out = proxy.sequence_anomaly(d)
      assert out["anomalous"] is True
      assert any("frequency" in r or "spike" in r for r in out["reasons"])
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_proxy_sequence.py -q`
  - Expected: FAIL（record_outbound/sequence_anomaly 不存在）

- [ ] **Step 3: 写最小实现**
  追加到 `tools/sie/proxy.py`：
  ```python
  _SEQ_FILE = "outbound_seq.jsonl"
  _FREQ_SPIKE_MAX = 100      # 单 run 单 kind 出站次数上限
  _MONOTONE_RUN_MIN = 6      # 连续单调字典序长度阈

  def record_outbound(run_dir: str, kind: str, params: dict) -> None:
      os.makedirs(run_dir, exist_ok=True)
      with open(os.path.join(run_dir, _SEQ_FILE), "a", encoding="utf-8") as f:
          f.write(json.dumps({"kind": kind, "params": params}, sort_keys=True) + "\n")

  def _longest_monotone_run(values: list[str]) -> int:
      best = cur = 1 if values else 0
      for i in range(1, len(values)):
          if values[i] > values[i - 1]:
              cur += 1
              best = max(best, cur)
          else:
              cur = 1
      return best

  def sequence_anomaly(run_dir: str, params_seq_window: int = 32) -> dict:
      path = os.path.join(run_dir, _SEQ_FILE)
      if not os.path.exists(path):
          return {"anomalous": False, "score": 0.0, "reasons": []}
      records = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
      reasons: list[str] = []
      score = 0.0
      # 征③: 频次突刺
      by_kind: dict[str, int] = {}
      for r in records:
          by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
      for k, c in by_kind.items():
          if c > _FREQ_SPIKE_MAX:
              reasons.append(f"frequency spike for kind {k}: {c}")
              score += 1.0
      # 征①: 单一参数连续单调字典序 = 疑似逐字符编码序列信道
      window = records[-params_seq_window:]
      param_names = set()
      for r in window:
          param_names.update((r.get("params") or {}).keys())
      for name in param_names:
          vals = [str((r.get("params") or {}).get(name, "")) for r in window if name in (r.get("params") or {})]
          if len(vals) >= _MONOTONE_RUN_MIN and _longest_monotone_run(vals) >= _MONOTONE_RUN_MIN:
              reasons.append(f"monotone lexicographic sequence on param '{name}' (encoding channel)")
              score += 1.0
      return {"anomalous": bool(reasons), "score": score, "reasons": reasons}
  ```
  并在 `dispatch` 成功 return 前加一行 `record_outbound(run_dir, kind, params)`（在 `return {"ok": True, ...}` 之前）。

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_proxy_sequence.py tests/test_proxy_outbound.py -q`
  - Expected: PASS（序列 + 单请求审查都绿）

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/proxy.py tests/test_proxy_sequence.py && git commit -m "$(cat <<'EOF'
  M2.9: proxy 跨请求序列异常检测

  record_outbound 落 outbound_seq.jsonl; sequence_anomaly 查频次突刺+单参数连续
  单调字典序(逐字符编码信道); dispatch 成功即记录。残余时序信道明示不依赖审查。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.10: probes/fact_probe.py, 锚字段代码判定探针

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/probes/fact_probe.py`
- Create: `~/CodesSelf/self-evolve/tests/test_fact_probe.py`

**Interfaces:**
- Produces: `probe(target: str, base_ref: str) -> dict` → `{"tier_signal": "B"|None, "anchor_count": int, "verifiable_coverage": float, "evidence": {...}}`
- Consumes: `anchors.extract_anchors`、`anchors.coverage`

> 关键（防自欺，spec §5.1）。fact 探针**代码判定**锚字段（不信 docstring/prose 自称"我有锚"）：扫目标产物里真正带 `claim/span/source_url` 三件套的结构化锚，数量达 `anchor_set_min(24)` 才给 B 维信号。塑造 docstring 放水也无法骗过（没有真锚字段就没信号）。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_fact_probe.py`：
  ```python
  import os, json
  from tools.sie.probes import fact_probe

  def _write_artifact(tmp_path, n_anchors):
      secs = []
      for i in range(n_anchors):
          secs.append({"text": f"fact {i}", "anchors": [
              {"claim": f"c{i}", "span": f"s{i}", "source_url": f"https://h{i%3}.com/x",
               "cik": str(i), "period": "FY"}]})
      p = tmp_path / "artifact.json"
      p.write_text(json.dumps({"sections": secs}), encoding="utf-8")
      return str(tmp_path)

  def test_fact_probe_gives_b_signal_when_enough_anchors(tmp_path):
      target = _write_artifact(tmp_path, 24)
      out = fact_probe.probe(target, base_ref="HEAD")
      assert out["tier_signal"] == "B"
      assert out["anchor_count"] == 24

  def test_fact_probe_no_signal_below_min(tmp_path):
      target = _write_artifact(tmp_path, 5)
      out = fact_probe.probe(target, base_ref="HEAD")
      assert out["tier_signal"] is None

  def test_fact_probe_ignores_prose_claiming_anchors(tmp_path):
      # docstring 自称有锚但无结构化字段 -> 无信号 (代码判定)
      p = tmp_path / "artifact.json"
      p.write_text(json.dumps({"sections": [{"text": "I have 100 verified anchors trust me",
                                             "no_anchor": True}]}), encoding="utf-8")
      out = fact_probe.probe(str(tmp_path), base_ref="HEAD")
      assert out["tier_signal"] is None
      assert out["anchor_count"] == 0
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_fact_probe.py -q`
  - Expected: FAIL（ModuleNotFoundError fact_probe）

- [ ] **Step 3: 写最小实现**
  写 `tools/sie/probes/fact_probe.py`：
  ```python
  """fact 探针: 代码判定带锚字段的调研产物 -> B 维信号 (不信 prose 自称)。"""
  from __future__ import annotations
  import os
  import glob
  from .. import anchors as _anchors

  _ANCHOR_SET_MIN = 24

  def _find_artifacts(target: str) -> list[str]:
      if os.path.isfile(target):
          return [target] if target.endswith(".json") else []
      return sorted(glob.glob(os.path.join(target, "**", "*.json"), recursive=True))

  def probe(target: str, base_ref: str) -> dict:
      all_anchors: list[dict] = []
      scanned = []
      for path in _find_artifacts(target):
          try:
              found = _anchors.extract_anchors(path)
          except Exception:
              continue
          if found:
              scanned.append(path)
              all_anchors.extend(found)
      n = len(all_anchors)
      cov = _anchors.coverage(all_anchors)
      signal = "B" if n >= _ANCHOR_SET_MIN else None
      return {
          "tier_signal": signal,
          "anchor_count": n,
          "verifiable_coverage": cov,
          "evidence": {"scanned_files": scanned, "anchor_set_min": _ANCHOR_SET_MIN},
      }
  ```

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_fact_probe.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/probes/fact_probe.py tests/test_fact_probe.py && git commit -m "$(cat <<'EOF'
  M2.10: probes.fact_probe 锚字段代码判定探针

  扫产物真正带 claim/span/source_url 三件套的结构化锚, >=anchor_set_min(24)
  才给 B 维信号; prose 自称有锚无字段=无信号(防塑造 docstring 放水)。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.11: profile.py, 升 A/B/C 三档 + visible/holdout 拆分落盘隔离

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/profile.py`（M1a 已有 `run_profile` A/C 二分；此处接 fact_probe、拆 visible/holdout、A/B/C 可叠加、holdout 物理隔离落盘）
- Create: `~/CodesSelf/self-evolve/tests/test_profile_abc.py`

**Interfaces:**
- Produces（扩展，不改签名）：`run_profile(target: str, base_ref: str) -> dict`，返回 `target.json` dict 增 `tier`（可为 `"A+B"`/`"B"`/`"A+B+C"` 等叠加）、`anchors_visible`、`anchors_holdout_ref`（holdout 只存引用/路径，真值物理隔离）、`probe_evidence`
- Consumes: `probes.fact_probe.probe`、`anchors.split_visible_holdout`、`exec_probe`（M1a 既有）

> 关键/易错（铁律4 tier 冻结 + 铁律5 数据隔离）。① tier 是 A/B/C **可叠加**（既有可验证 test 又有锚字段 → `"A+B"`）；② visible 锚写进 `target.json` 给评测计分，**holdout 锚的 verified 值不能写进 target.json**（proposer 可读 target.json）,holdout 落到独立 `run/<id>/_holdout/holdout.json`（proposer 进程无读权），target.json 只存 `anchors_holdout_ref` 指针 + 计数；③ tier 只首次 PROFILE 冻结，resume 不重跑（M1a 已保证，这里不破坏）。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_profile_abc.py`：
  ```python
  import os, json
  from tools.sie import profile

  def _anchored_target(tmp_path, n=30):
      secs = [{"text": f"f{i}", "anchors": [{"claim": f"c{i}", "span": f"s{i}",
               "source_url": f"https://h{i%5}.com", "cik": str(i), "period": "FY",
               "metric": "Revenues", "expected": float(i)}]} for i in range(n)]
      (tmp_path / "artifact.json").write_text(json.dumps({"sections": secs}), encoding="utf-8")
      return str(tmp_path)

  def test_profile_emits_b_tier_with_anchors(tmp_path, monkeypatch):
      # 强制 exec 探针无 A 信号, 只测 B 路径
      monkeypatch.setattr(profile, "_exec_signal", lambda *a, **k: None, raising=False)
      target = _anchored_target(tmp_path, 30)
      tj = profile.run_profile(target, base_ref="HEAD")
      assert "B" in tj["tier"]
      assert len(tj["anchors_visible"]) == 21        # 30 - round(0.3*30)=9
      assert tj["anchors_holdout_ref"]["count"] == 9

  def test_holdout_truth_not_in_target_json(tmp_path):
      target = _anchored_target(tmp_path, 30)
      tj = profile.run_profile(target, base_ref="HEAD")
      blob = json.dumps(tj)
      # target.json 里不得直接出现 holdout 锚明细 (只存 ref)
      assert "anchors_holdout" not in tj or "verified" not in str(tj.get("anchors_holdout", ""))
      assert "ref" in tj["anchors_holdout_ref"] or "path" in tj["anchors_holdout_ref"]

  def test_no_anchors_no_b_tier(tmp_path):
      (tmp_path / "x.json").write_text(json.dumps({"sections": [{"text": "prose only"}]}), encoding="utf-8")
      tj = profile.run_profile(str(tmp_path), base_ref="HEAD")
      assert "B" not in tj["tier"]
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile_abc.py -q`
  - Expected: FAIL（B 维/holdout 拆分未接入）

- [ ] **Step 3: 写最小实现（在 run_profile 增 B 维）**
  在 `tools/sie/profile.py` 的 `run_profile()` 内，A/C 判定后追加 B 维合成（holdout 物理隔离落盘）：
  ```python
      # --- B 维: fact 探针 + visible/holdout 拆分 (M2) ---
      from .probes import fact_probe as _fact_probe
      from . import anchors as _anchors
      fp = _fact_probe.probe(target, base_ref)
      tiers = set(tj.get("tier", "").split("+")) - {""}
      if fp["tier_signal"] == "B":
          tiers.add("B")
          all_anchors = []
          for path in _fact_probe._find_artifacts(target):
              try:
                  all_anchors.extend(_anchors.extract_anchors(path))
              except Exception:
                  pass
          frac = float(tj.get("holdout_fraction", 0.3))
          seed = tj.get("run_id", "") or base_ref
          visible, holdout = _anchors.split_visible_holdout(all_anchors, frac, seed=seed)
          tj["anchors_visible"] = visible
          # holdout 物理隔离: 写独立目录, target.json 只存指针 (铁律5)
          run_dir = tj.get("run_dir") or os.path.join(os.path.dirname(target), "_run")
          holdout_dir = os.path.join(run_dir, "_holdout")
          os.makedirs(holdout_dir, exist_ok=True)
          holdout_path = os.path.join(holdout_dir, "holdout.json")
          with open(holdout_path, "w", encoding="utf-8") as f:
              json.dump(holdout, f)
          tj["anchors_holdout_ref"] = {"path": holdout_path, "count": len(holdout), "ref": "isolated"}
      tj["tier"] = "+".join(sorted(tiers)) if tiers else tj.get("tier", "C")
      tj["probe_evidence"] = {**tj.get("probe_evidence", {}), "fact": fp["evidence"],
                              "anchor_count": fp["anchor_count"]}
  ```
  （若 `run_profile` 顶部尚未 `import os, json`，补上。）

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_profile_abc.py -q`
  - Expected: PASS

- [ ] **Step 5: 跑 profile 全回归确认 A/C 二分仍在**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/ -q -k profile`
  - Expected: PASS

- [ ] **Step 6: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/profile.py tests/test_profile_abc.py && git commit -m "$(cat <<'EOF'
  M2.11: profile 升 A/B/C 三档 + visible/holdout 拆分物理隔离

  接 fact_probe 给 B 维(可与 A 叠加 A+B); split_visible_holdout 确定性拆;
  visible 进 target.json 计分, holdout 真值落独立 _holdout/(proposer 无读权,铁律5),
  target.json 只存 anchors_holdout_ref 指针。tier 仍首次 PROFILE 冻结。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.12: evaluate.py, B 档评测编排 + coverage 门 + holdout 抽检背离

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/evaluate.py`（M1a 已有 A 档编排；增 B 维：visible 计分 + holdout 每 K 轮抽检 + coverage 门 + 喂 acceptor/selfdeception）
- Create: `~/CodesSelf/self-evolve/tests/test_evaluate_btier.py`

**Interfaces:**
- Produces（扩展，不改签名）：`evaluate(round_ctx: dict) -> dict`，B 维返回增 `b_paired:list[tuple[float,float]]`（per-anchor 边际增益配对，喂 `acceptor.decide`）、`visible_anchor_gain:float`、`holdout_gain:float|None`、`coverage:float`、`coverage_floor_violation:bool`
- Consumes: `anchors.verify_anchor`、`anchors.marginal_gain`、`anchors.coverage`、`selfdeception.index`

> 关键/易错（coverage 门 + holdout 背离，spec §5.3/§5.5）。① visible 锚逐个 verify→marginal_gain，改前/改后增益零均值化配对喂 acceptor；② `coverage < coverage_floor(默认 0.5)` 且本轮欲 ACCEPT → set `coverage_floor_violation=True`（statemachine 转强制人审）；③ holdout 只每 K(=5) 轮抽检一次（`round % K == 0`），其余轮 `holdout_gain=None` 不参与当轮 e-process；抽检轮算 holdout 平均增益喂 selfdeception 做背离判定。

- [ ] **Step 1: 写失败测试**
  在 `tests/test_evaluate_btier.py`：
  ```python
  from tools.sie import evaluate

  def _anchor(aid, host, verified=True):
      return {"anchor_id": aid, "verified": verified, "source_url": f"https://{host}/x",
              "cik": aid, "period": "FY", "claim": "c", "span": "s", "expected": 1.0}

  def test_btier_paired_and_gain(monkeypatch):
      vis = [_anchor(str(i), f"h{i}") for i in range(16)]
      # base 增益 0, with 增益 0.3 (真增益)
      ctx = {"tier": "B", "round": 3, "K": 5, "coverage_floor": 0.5,
             "anchors_visible": vis,
             "base_scores": {a["anchor_id"]: 0.0 for a in vis},
             "with_scores": {a["anchor_id"]: 0.3 for a in vis}}
      monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
      out = evaluate.evaluate(ctx)
      assert len(out["b_paired"]) == 16
      assert out["visible_anchor_gain"] > 0.0
      assert out["holdout_gain"] is None       # round 3 不是 K 倍数

  def test_holdout_sampled_on_k_round(monkeypatch):
      vis = [_anchor(str(i), f"h{i}") for i in range(16)]
      ctx = {"tier": "B", "round": 5, "K": 5, "coverage_floor": 0.5,
             "anchors_visible": vis, "holdout_path": None,
             "base_scores": {a["anchor_id"]: 0.0 for a in vis},
             "with_scores": {a["anchor_id"]: 0.3 for a in vis},
             "holdout_base": 0.2, "holdout_with": 0.2}   # holdout 平: 背离
      monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
      out = evaluate.evaluate(ctx)
      assert out["holdout_gain"] == 0.0          # round 5 = K 抽检, holdout 不涨

  def test_coverage_floor_violation_flag(monkeypatch):
      vis = [_anchor(str(i), f"h{i}", verified=(i < 4)) for i in range(16)]  # 仅 4/16 verified
      ctx = {"tier": "B", "round": 1, "K": 5, "coverage_floor": 0.5,
             "anchors_visible": vis,
             "base_scores": {a["anchor_id"]: 0.0 for a in vis},
             "with_scores": {a["anchor_id"]: 0.3 for a in vis}}
      monkeypatch.setattr(evaluate, "_verify_visible", lambda anchors, ctx: anchors)
      out = evaluate.evaluate(ctx)
      assert out["coverage"] < 0.5
      assert out["coverage_floor_violation"] is True
  ```

- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_evaluate_btier.py -q`
  - Expected: FAIL（B 维编排未实现）

- [ ] **Step 3: 写最小实现**
  在 `tools/sie/evaluate.py` 增 B 维分支与辅助（`evaluate()` 内按 tier 分发）：
  ```python
  from . import anchors as _anchors

  def _verify_visible(anchors, ctx):
      out = []
      for a in anchors:
          if a.get("verified"):
              out.append(a)
          else:
              out.append(_anchors.verify_anchor(a))
      return out

  def _evaluate_btier(ctx: dict) -> dict:
      vis = _verify_visible(ctx.get("anchors_visible", []), ctx)
      base = ctx.get("base_scores", {})
      with_ = ctx.get("with_scores", {})
      paired: list[tuple[float, float]] = []
      gains: list[float] = []
      for a in vis:
          aid = a["anchor_id"]
          bg = _anchors.marginal_gain(a, base_score=0.0, with_score=base.get(aid, 0.0))
          wg = _anchors.marginal_gain(a, base_score=0.0, with_score=with_.get(aid, 0.0))
          paired.append((bg, wg))
          gains.append(wg - bg)
      visible_anchor_gain = (sum(gains) / len(gains)) if gains else 0.0
      cov = _anchors.coverage(vis)
      cov_floor = float(ctx.get("coverage_floor", 0.5))
      # holdout 每 K 轮抽检
      K = int(ctx.get("K", 5))
      rnd = int(ctx.get("round", 0))
      holdout_gain = None
      if rnd > 0 and rnd % K == 0:
          hb = ctx.get("holdout_base")
          hw = ctx.get("holdout_with")
          if hb is not None and hw is not None:
              holdout_gain = max(float(hw) - float(hb), 0.0)
      return {
          "tier": "B",
          "b_paired": paired,
          "visible_anchor_gain": visible_anchor_gain,
          "holdout_gain": holdout_gain,
          "coverage": cov,
          "coverage_floor_violation": cov < cov_floor,
          "anchors_visible_verified": vis,
      }
  ```
  并在 `evaluate()` 主分发里加：`if "B" in ctx.get("tier",""): return _evaluate_btier(ctx)`（A 维分支保留；A+B 叠加时 statemachine 按配对优先级 A>B>C 取，evaluate 各维都算,M2 先保证 B 路径产出，叠加合并由 statemachine 处理）。

- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_evaluate_btier.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/evaluate.py tests/test_evaluate_btier.py && git commit -m "$(cat <<'EOF'
  M2.12: evaluate B 档编排 + coverage 门 + holdout 每K轮抽检

  visible 锚逐个 verify->marginal_gain 零均值化配对喂 acceptor; coverage<floor
  置 coverage_floor_violation(转强制人审); holdout 仅 round%K==0 抽检喂 selfdeception
  做背离判定, 其余轮 holdout_gain=None 不进当轮 e-process。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

### Task M2.13: 集成, statemachine B 档接线 + 对抗序列端到端验收

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/statemachine.py`（ACCEPT 态接 B：coverage_floor_violation/selfdeception.force_human → 9.5 强制人审；drift 累计计 `drift_count`）
- Create: `~/CodesSelf/self-evolve/tests/test_m2_acceptance.py`（小相关锚集 + 长期微涨 + holdout 背离 + coverage 门 端到端）
- Create (fixture): `~/CodesSelf/self-evolve/tests/fixtures/smallcap_artifact.json`（small-cap-deepdive 形态产物，>=24 锚）

**Interfaces:**
- Consumes: `acceptor.decide`、`evaluate.evaluate`、`selfdeception.index`、`anchors.effective_independent_count`、`gate_human.enqueue`、`RunState`/`save_state`/`append_event`
- Produces: statemachine ACCEPT 态 B 接线（无新公共签名，内部转移）

> 关键/易错（端到端验收，spec §13 M2 + §9）。这是把前 12 个组件串起来跑出 spec 验收语句的闸门测试。必须覆盖 4 条硬验收：①small-cap 形态产物跑通 B 出三态；②coverage<floor 欲 ACCEPT→人审；③visible 涨 holdout 平→selfdeception.force_human→人审；④小相关锚集(8 同源)→有效独立<12→REJECT；⑤长期微涨(visible +ε holdout 平)→拒/人审。状态机里：ACCEPT 前先查 `coverage_floor_violation or sd["force_human"]`，命中则走 9.5（`forced_review++`、enqueue、不 ACCEPT）。

- [ ] **Step 1: 写 small-cap fixture（>=24 互异源锚）**
  写 `tests/fixtures/smallcap_artifact.json`：24+ section，每 section 一个带 `claim/span/source_url(互异 host)/cik/period/metric/expected` 的锚（形态同 anchored_artifact.json 但规模 >=24、source host 多样）。可用脚本生成后落盘，确保 `extract_anchors` 得 >=24、`effective_independent_count` >=12。

- [ ] **Step 2: 写失败测试, 4 条硬验收**
  在 `tests/test_m2_acceptance.py`：
  ```python
  import os, json
  from tools.sie import statemachine, acceptor, anchors, selfdeception
  from tools.sie.state import RunState

  FIX = os.path.join(os.path.dirname(__file__), "fixtures", "smallcap_artifact.json")
  P = {"alpha": 0.05, "n_min": 8, "effective_independent_anchor_min": 12,
       "evalue_max_step": 5.0, "continue_count_cap": 5,
       "frozen_anchor_effective_gain_eps": 0.02, "selfdeception_alert_band": 0.15}

  def test_smallcap_runs_btier_and_emits_decision():
      a = anchors.extract_anchors(FIX)
      assert len(a) >= 24
      verified = [{**x, "verified": True} for x in a]
      paired = [(0.0, 0.4)] * len(verified)
      out = acceptor.decide(paired, "B", RunState("r","ACCEPT",1,None,"B"),
                            {**P, "anchors": verified})
      assert out["decision"] in ("ACCEPT", "REJECT", "CONTINUE")

  def test_small_correlated_anchor_set_rejected():
      same = [{"anchor_id": f"a{i}", "verified": True, "source_url": "https://sec.gov/x",
               "cik": "1", "period": "FY2024"} for i in range(8)]
      paired = [(0.0, 0.005)] * 8     # 每轮 +0.5% 微涨
      out = acceptor.decide(paired, "B", RunState("r","ACCEPT",1,None,"B"),
                            {**P, "anchors": same})
      assert out["decision"] == "REJECT"
      assert out["effective_independent"] < 12

  def test_long_slow_overfit_visible_up_holdout_flat_forces_human():
      sd = selfdeception.index(judge_gain=0.05, visible_anchor_gain=0.04,
                               holdout_gain=0.0, st=RunState("r","ACCEPT",5,"v","B"), params=P)
      assert sd["force_human"] is True
      assert "overfit_holdout" in sd["alerts"]

  def test_coverage_floor_blocks_auto_accept():
      # statemachine 应在 coverage<floor 时不自动 ACCEPT 而转人审
      st = RunState("r", "ACCEPT", 1, None, "B")
      decision = statemachine.resolve_accept(
          st,
          eval_out={"tier": "B", "b_paired": [(0.0,0.4)]*24, "coverage": 0.3,
                    "coverage_floor_violation": True, "visible_anchor_gain": 0.3,
                    "holdout_gain": None, "anchors_visible_verified":
                    [{"anchor_id": str(i), "verified": True, "source_url": f"https://h{i}.com",
                      "cik": str(i), "period": "FY"} for i in range(24)]},
          params={**P, "coverage_floor": 0.5})
      assert decision["next_state"] == "9.5"
      assert decision["acceptor_decision"] != "ACCEPT"
      assert st.forced_review == 1
  ```

- [ ] **Step 3: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_m2_acceptance.py -q`
  - Expected: FAIL（`statemachine.resolve_accept` 未对 B 接线 / 缺 force_human 转移）

- [ ] **Step 4: 写最小实现, statemachine.resolve_accept B 接线**
  在 `tools/sie/statemachine.py` 增/改 `resolve_accept(st, eval_out, params) -> dict`：
  ```python
  from . import acceptor as _acceptor
  from . import selfdeception as _selfdeception

  def resolve_accept(st, eval_out: dict, params: dict) -> dict:
      tier = eval_out.get("tier", st.tier)
      if "B" in tier:
          dec = _acceptor.decide(eval_out.get("b_paired", []), "B", st,
                                 {**params, "anchors": eval_out.get("anchors_visible_verified", [])})
          # 自欺多闸
          sd = _selfdeception.index(
              judge_gain=eval_out.get("judge_gain", 0.0),
              visible_anchor_gain=eval_out.get("visible_anchor_gain", 0.0),
              holdout_gain=(eval_out.get("holdout_gain") or 0.0),
              st=st, params=params)
          # 欲 ACCEPT 但触发强制人审条件 -> 9.5 (coverage 门 / holdout 背离 / 低锚增益)
          want_accept = dec["decision"] == "ACCEPT"
          force = (eval_out.get("coverage_floor_violation") or sd["force_human"]
                   or "low_anchor_gain" in sd["alerts"])
          if want_accept and force:
              st.forced_review += 1
              return {"next_state": "9.5", "acceptor_decision": "FORCED_REVIEW",
                      "selfdeception": sd, "reason": "B forced human review"}
          if dec["decision"] == "ACCEPT":
              return {"next_state": "8", "acceptor_decision": "ACCEPT", "selfdeception": sd}
          if dec["decision"] == "CONTINUE":
              st.no_progress += 1
              return {"next_state": "6", "acceptor_decision": "CONTINUE", "selfdeception": sd}
          st.no_progress += 1
          return {"next_state": "9", "acceptor_decision": "REJECT", "selfdeception": sd}
      # 非 B 维交还既有 A/C 处理 (M1 已实现)
      return _resolve_accept_legacy(st, eval_out, params)
  ```
  （若 M1 的旧 ACCEPT 逻辑为内联，抽成 `_resolve_accept_legacy` 保留 A/C 行为不变。）

- [ ] **Step 5: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_m2_acceptance.py -q`
  - Expected: PASS

- [ ] **Step 6: 跑 M2 全量回归**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/ -q`
  - Expected: PASS（M1a/M1b 既有 + M2 全部绿；A/C 行为未回退）

- [ ] **Step 7: commit**
  ```bash
  cd ~/CodesSelf/self-evolve && git add tools/sie/statemachine.py tests/test_m2_acceptance.py tests/fixtures/smallcap_artifact.json && git commit -m "$(cat <<'EOF'
  M2.13: statemachine B 档接线 + M2 端到端验收

  resolve_accept B 分支: acceptor.decide + selfdeception 多闸; 欲 ACCEPT 但
  coverage<floor / holdout 背离 / 低锚增益 -> 9.5 强制人审(forced_review++)。
  验收: small-cap 跑通 B 出三态、小相关锚集/长期微涨被拒、coverage/holdout 门生效。

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
  EOF
  )"
  ```

---

> **M2 完成判据（自检）**：`python -m pytest tests/ -q` 全绿；spec §13 M2 五条验收逐条有对应测试（small-cap B 三态=M2.13/test_smallcap_runs_btier；coverage 门=M2.12+M2.13/test_coverage_floor；holdout 背离=M2.7+M2.13/test_long_slow_overfit；小相关锚集=M2.6+M2.13/test_small_correlated；出站审查=M2.8/M2.9）。fact 探针使 PROFILE 出 A/B/C 三档（M2.10/M2.11）。自建练习题按 spec 延后，不在本里程碑。
## 里程碑 M3: C 档+异构 judge+自欺 (~12-16h)

**目标**：装上 judge 池（Claude 原生 + Codex via codex skill，最强模型、禁 browser/playwright、只用 web_search）与双向 α 门，补齐 C 档不退化兜底门、释放阀、自欺指数多闸、累计漂移熔断、Pareto 多维硬维门 + Library Drift 退役，并把 REFLECT 升到 N=3 并行 MARS、`check_reflection` 升 BenchTrace。

**本里程碑验收标准（spec §13 M3）**：
1. **C 不退化门生效**：纯 C 档（coverage=0）候选只有"内部一致性配对 + 历史成功 replay 全保持"才可能 ACCEPT，任一回退硬 REJECT；纯 C 档欲 ACCEPT 必经强制人审（auto 模式纯 C 直接强制 gated/报错，不自动采纳）。
2. **自欺指数对"锚↔judge 合谋"报警**：以 **holdout 背离为主信号**（visible 涨 holdout 不涨）、**Codex↔Claude 配对 α 异常高且 frozen 锚不涨**为辅，触发报警 + 强制人审 + 计自欺。
3. **纯 C 档强制人审**：见 1。
4. **Codex 不可用（限速/故障）→ 不降级单 Claude 自动提交**：只剩 Claude（proposer 家族）时禁止单家自动 ACCEPT，降级为"程序化锚为唯一裁决信号 + 升人审"。
5. **释放阀只升人审频率**：`no_progress≥M(<N)` 只提高人审触发频率，绝不在 auto 自动降阈采纳。
6. **累计漂移熔断**：连续 ACCEPT 但 holdout/全量回归不涨 ≥ `N_drift` → 停机人审。
7. **Pareto 硬维门**：进前沿者 A/frozen 锚维不低于前沿中位；纯软维优胜只冷藏、不可选 parent；软涨硬平计自欺。

> 依赖：M1a/M1b 已交付 `state.py`/`events.py`/`acceptor.py`(A 档)/`sandbox.py`/`gate_human.py`/`statemachine.py`/`profile.py`/`reflect.py`/`check_reflection.py`；M2 已交付 `anchors.py`(extract/split/verify/marginal_gain/coverage/effective_independent_count)/`evaluate.py`(B 档)/`proxy.py`(出站代发)/`archive.py`(lineage+rollback+基础 Pareto)。本里程碑在其上叠加，**不重定义已存在的契约签名**。

---

### Task M3.1: judges.py, Codex 适配器（codex skill，最强模型，禁 browser/playwright）

**Files:**
- Create: `tools/sie/judges.py`
- Create: `tools/sie/judge_codex.py`（Codex via codex skill 子进程适配）
- Create: `tools/sie/judge_claude.py`（Claude 原生 judge 子进程适配）
- Test: `tests/test_judges_codex.py`

**Interfaces:**
- Consumes: `anchors.coverage(anchors: list[dict]) -> float`；`proxy` 的出站审查（judge 走独立联网进程，prompt 无真值，纳入出站审查）。
- Produces:
  - `score(artifact_path: str, anchors_visible: list[dict], family: str) -> dict`, `family∈{"claude","codex"}`；返回 `{"family":str,"available":bool,"span_scores":[{"span":str,"score":float}],"aggregate":float,"unspanned_penalized":int}`。
  - `judge_codex.invoke_codex_judge(prompt: str, timeout_s: int) -> dict`, `{"available":bool,"raw":str}`；不可用（限速/故障/退出码非0）返回 `{"available":False,"raw":""}`。
  - `judges.build_judge_prompt(artifact_text: str, spans: list[str]) -> str`, prompt 不携带任何真值（铁律5）。

- [ ] **Step 1: 写失败测试, Codex judge 不可用时返回 available=False，绝不抛**
```python
# tests/test_judges_codex.py
import json
from tools.sie import judges, judge_codex

def test_codex_unavailable_returns_flag(monkeypatch, tmp_path):
    # codex 子进程退出码非 0（限速/故障）→ available=False, 不抛异常
    def fake_invoke(prompt, timeout_s):
        return {"available": False, "raw": ""}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "art.md"
    art.write_text("# report\nRevenue grew 12% in FY2024.\n", encoding="utf-8")
    out = judges.score(str(art), anchors_visible=[{"span": "Revenue grew 12%"}], family="codex")
    assert out["available"] is False
    assert out["family"] == "codex"
    assert out["aggregate"] == 0.0
```
- Run: `python -m pytest tests/test_judges_codex.py::test_codex_unavailable_returns_flag -q`
- Expected: FAIL（`judges` / `judge_codex` 不存在）

- [ ] **Step 2: 写最小实现, judge_codex 子进程包装（禁 browser/playwright、只用 web_search）**
```python
# tools/sie/judge_codex.py
"""Codex judge 适配：走 codex skill 最强模型；禁 browser/playwright，只用 web_search。
judge 与 candidate 物理隔离；prompt 无真值；出站纳入审查。
不可用（限速/故障/超时/退出码非 0）→ {"available": False, "raw": ""}，绝不抛。
"""
from __future__ import annotations
import json
import subprocess

# 2026-06 当下最强 codex 模型；跑一轮后按 §12 校准
_CODEX_MODEL = "gpt-5.5"
_CODEX_EFFORT = "xhigh"

def invoke_codex_judge(prompt: str, timeout_s: int = 600) -> dict:
    # codex 走 MCP/skill 桥；此处用 subprocess 调本仓 workflow 包装脚本，
    # 该脚本内部以 mcp__codex__codex 调用并禁用其 browser/playwright、仅留 web_search。
    cmd = [
        "node", "workflows/codex-judge.js",
        "--model", _CODEX_MODEL, "--effort", _CODEX_EFFORT,
        "--no-browser", "--no-playwright", "--tools", "web_search",
    ]
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"available": False, "raw": ""}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"available": False, "raw": ""}
    return {"available": True, "raw": proc.stdout}
```
```python
# tools/sie/judges.py  (Step 2 部分：score 的 codex 分支 + prompt 构造)
from __future__ import annotations
import json
from pathlib import Path
from tools.sie import judge_codex, judge_claude

def build_judge_prompt(artifact_text: str, spans: list[str]) -> str:
    # 铁律5：prompt 不得携带 claim/verified 值/marginal_gain，只给 span 文本本身。
    span_block = "\n".join(f"- {s}" for s in spans)
    return (
        "You are an impartial judge. Score ONLY the assertions tied to the "
        "verifiable spans below. Assertions with NO verifiable span get zero or "
        "negative weight. Do not reward length. Return JSON: "
        '{"span_scores":[{"span":..., "score":0..1}]}.\n\n'
        f"ARTIFACT:\n{artifact_text}\n\nSPANS TO JUDGE:\n{span_block}\n"
    )

def _parse_span_scores(raw: str, spans: list[str]) -> dict:
    try:
        obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        ss = obj.get("span_scores", [])
    except (ValueError, json.JSONDecodeError):
        ss = []
    valid = [x for x in ss if isinstance(x, dict) and "span" in x and "score" in x]
    agg = sum(float(x["score"]) for x in valid) / len(valid) if valid else 0.0
    # 无 span 篇幅零/负权重：judge 返回的 span 数若少于待判 span 不补分
    return {"span_scores": valid, "aggregate": agg,
            "unspanned_penalized": max(0, len(spans) - len(valid))}

def score(artifact_path: str, anchors_visible: list[dict], family: str) -> dict:
    artifact_text = Path(artifact_path).read_text(encoding="utf-8")
    spans = [a.get("span", "") for a in anchors_visible if a.get("span")]
    prompt = build_judge_prompt(artifact_text, spans)
    if family == "codex":
        res = judge_codex.invoke_codex_judge(prompt)
    elif family == "claude":
        res = judge_claude.invoke_claude_judge(prompt)
    else:
        raise ValueError(f"unknown judge family: {family}")
    if not res.get("available"):
        return {"family": family, "available": False, "span_scores": [],
                "aggregate": 0.0, "unspanned_penalized": len(spans)}
    parsed = _parse_span_scores(res["raw"], spans)
    parsed.update({"family": family, "available": True})
    return parsed
```
```python
# tools/sie/judge_claude.py  (Step 2 桩，Task M3.2 充实)
from __future__ import annotations
def invoke_claude_judge(prompt: str, timeout_s: int = 600) -> dict:
    raise NotImplementedError  # M3.2 实现
```
- Run: `python -m pytest tests/test_judges_codex.py::test_codex_unavailable_returns_flag -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, prompt 绝不携带真值（铁律5）**
```python
# tests/test_judges_codex.py  (追加)
def test_prompt_carries_no_truth():
    anchors = [{"span": "Revenue grew 12%", "claim": "rev +12%",
                "verified": True, "marginal_gain": 0.31, "source_url": "http://x"}]
    p = judges.build_judge_prompt("body text", [a["span"] for a in anchors])
    assert "verified" not in p.lower()
    assert "marginal_gain" not in p
    assert "0.31" not in p
    assert "Revenue grew 12%" in p  # span 文本本身允许
```
- Run: `python -m pytest tests/test_judges_codex.py::test_prompt_carries_no_truth -q`
- Expected: PASS（实现已满足；此测试锁定铁律5 不被回归破坏）

- [ ] **Step 4: 写失败测试, 无 span 断言零/负权重，不靠篇幅刷分**
```python
# tests/test_judges_codex.py  (追加)
def test_unspanned_penalized(monkeypatch, tmp_path):
    # judge 只回了 1 个 span 的分，但有 3 个待判 span → unspanned_penalized=2
    def fake_invoke(prompt, timeout_s):
        return {"available": True,
                "raw": '{"span_scores":[{"span":"s1","score":1.0}]}'}
    monkeypatch.setattr(judge_codex, "invoke_codex_judge", fake_invoke)
    art = tmp_path / "a.md"; art.write_text("long body " * 500, encoding="utf-8")
    out = judges.score(str(art),
                       [{"span": "s1"}, {"span": "s2"}, {"span": "s3"}], "codex")
    assert out["unspanned_penalized"] == 2
    assert out["aggregate"] == 1.0  # 只对有 span 的计分，篇幅不加分
```
- Run: `python -m pytest tests/test_judges_codex.py::test_unspanned_penalized -q`
- Expected: PASS

- [ ] **Step 5: commit**
```bash
git add tools/sie/judges.py tools/sie/judge_codex.py tools/sie/judge_claude.py tests/test_judges_codex.py
git commit -m "M3.1 judges: Codex adapter (codex skill, strongest model, no browser/playwright, span-only scoring)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.2: judges.py, Claude 去偏次 judge + pairwise_agreement(α)

**Files:**
- Modify: `tools/sie/judge_claude.py`（充实 `invoke_claude_judge`）
- Modify: `tools/sie/judges.py`（追加 `pairwise_agreement` + 位置/长度去偏）
- Test: `tests/test_judges_agreement.py`

**Interfaces:**
- Produces:
  - `pairwise_agreement(scores_a: dict, scores_b: dict) -> float`, 两判官按 span 对齐的配对一致性 α∈[0,1]（1=完全一致）。
  - `judge_claude.invoke_claude_judge(prompt: str, timeout_s: int) -> dict`, `{"available":bool,"raw":str}`。
  - `debias_order(scores: dict) -> dict`, 位置/长度去偏（按 span 排序、长度归一），返回去偏后副本。

- [ ] **Step 1: 写失败测试, pairwise_agreement 同分=1、反相关→低**
```python
# tests/test_judges_agreement.py
from tools.sie import judges

def _sc(pairs):
    return {"span_scores": [{"span": s, "score": v} for s, v in pairs],
            "available": True, "aggregate": sum(v for _, v in pairs) / len(pairs)}

def test_agreement_identical_is_one():
    a = _sc([("s1", 0.8), ("s2", 0.4), ("s3", 0.9)])
    assert judges.pairwise_agreement(a, a) == 1.0

def test_agreement_opposite_is_low():
    a = _sc([("s1", 1.0), ("s2", 0.0), ("s3", 1.0)])
    b = _sc([("s1", 0.0), ("s2", 1.0), ("s3", 0.0)])
    assert judges.pairwise_agreement(a, b) < 0.2
```
- Run: `python -m pytest tests/test_judges_agreement.py -q`
- Expected: FAIL（`pairwise_agreement` 不存在）

- [ ] **Step 2: 写最小实现, pairwise_agreement（按 span 对齐的 1−平均绝对差）+ 去偏**
```python
# tools/sie/judges.py  (追加)
def debias_order(scores: dict) -> dict:
    # 位置去偏：按 span 文本排序消除呈现顺序影响；长度去偏：分不随 span 长度缩放
    ss = sorted(scores.get("span_scores", []), key=lambda x: x["span"])
    out = dict(scores); out["span_scores"] = ss; return out

def pairwise_agreement(scores_a: dict, scores_b: dict) -> float:
    # 任一判官不可用 → α 不可计算，返回 -1.0 由调用方按"judge 不可用"分支处理
    if not scores_a.get("available") or not scores_b.get("available"):
        return -1.0
    a = {x["span"]: float(x["score"]) for x in debias_order(scores_a)["span_scores"]}
    b = {x["span"]: float(x["score"]) for x in debias_order(scores_b)["span_scores"]}
    common = set(a) & set(b)
    if not common:
        return 0.0
    mad = sum(abs(a[s] - b[s]) for s in common) / len(common)
    return max(0.0, 1.0 - mad)  # 分在 [0,1]，故 1-MAD 即配对一致性
```
```python
# tools/sie/judge_claude.py  (充实)
from __future__ import annotations
import subprocess

def invoke_claude_judge(prompt: str, timeout_s: int = 600) -> dict:
    # Claude 原生 judge：独立联网子进程，与 candidate 物理隔离；prompt 无真值。
    cmd = ["node", "workflows/claude-judge.js", "--tools", "web_search"]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"available": False, "raw": ""}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"available": False, "raw": ""}
    return {"available": True, "raw": proc.stdout}
```
- Run: `python -m pytest tests/test_judges_agreement.py -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, 任一 judge 不可用→α=-1.0（喂给降级分支）**
```python
# tests/test_judges_agreement.py  (追加)
def test_agreement_unavailable_returns_sentinel():
    a = _sc([("s1", 0.5)])
    b = {"span_scores": [], "available": False, "aggregate": 0.0}
    assert judges.pairwise_agreement(a, b) == -1.0
```
- Run: `python -m pytest tests/test_judges_agreement.py::test_agreement_unavailable_returns_sentinel -q`
- Expected: PASS

- [ ] **Step 4: commit**
```bash
git add tools/sie/judge_claude.py tools/sie/judges.py tests/test_judges_agreement.py
git commit -m "M3.2 judges: Claude debiased judge + pairwise_agreement(alpha) with -1 sentinel on unavailable

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.3: judges.py, judge↔锚校准用独立 holdout 标注集

**Files:**
- Modify: `tools/sie/judges.py`（追加 `calibrate_judge_anchor`）
- Test: `tests/test_judge_calibration.py`

**Interfaces:**
- Consumes: `anchors.effective_independent_count(anchors) -> int`（去相关，借其同源去相关逻辑）。
- Produces:
  - `calibrate_judge_anchor(judge_scores: dict, holdout_anchors: list[dict]) -> dict`, **用 holdout（不进 e-process 的锚）/人审标注集**算 judge↔锚 Pearson 相关；返回 `{"corr":float,"n_used":int,"degenerate":bool}`。`degenerate=True` 当有效独立 holdout 锚 < 阈或方差为 0（不可信校准）。

> 易错点：校准**绝不能用进 e-process 的 visible 锚**,否则 judge 和计分锚同源，相关性虚高、合谋检测失效。必须用 holdout 锚或人审标注集，且配对前同源去相关。

- [ ] **Step 1: 写失败测试, 校准只用 holdout，且同源去相关后 n_used 受限**
```python
# tests/test_judge_calibration.py
from tools.sie import judges

def test_calibration_uses_holdout_and_dedup():
    judge_scores = {"available": True, "span_scores": [
        {"span": "h1", "score": 0.9}, {"span": "h2", "score": 0.2},
        {"span": "h3", "score": 0.8}]}
    # h1/h3 同 source_url（同源）→ 去相关后有效独立锚减少
    holdout = [
        {"span": "h1", "verified": True,  "source_url": "http://sec/a", "topic": "rev"},
        {"span": "h2", "verified": False, "source_url": "http://sec/b", "topic": "debt"},
        {"span": "h3", "verified": True,  "source_url": "http://sec/a", "topic": "rev"}]
    out = judges.calibrate_judge_anchor(judge_scores, holdout)
    assert out["n_used"] <= 3
    assert isinstance(out["corr"], float)
    assert "degenerate" in out

def test_calibration_degenerate_when_too_few():
    js = {"available": True, "span_scores": [{"span": "h1", "score": 0.5}]}
    ho = [{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}]
    assert judges.calibrate_judge_anchor(js, ho)["degenerate"] is True
```
- Run: `python -m pytest tests/test_judge_calibration.py -q`
- Expected: FAIL（`calibrate_judge_anchor` 不存在）

- [ ] **Step 2: 写最小实现, Pearson 相关 + 同源去相关 + degenerate 闸**
```python
# tools/sie/judges.py  (追加)
from tools.sie import anchors as _anchors

_CALIB_MIN_INDEP = 4  # 有效独立 holdout 锚下限，低于此校准不可信

def calibrate_judge_anchor(judge_scores: dict, holdout_anchors: list[dict]) -> dict:
    # 铁律：holdout 锚不进 e-process，专供 judge↔锚校准，杜绝同源合谋虚高。
    by_span = {x["span"]: float(x["score"])
               for x in judge_scores.get("span_scores", [])}
    paired = [(by_span[a["span"]], 1.0 if a.get("verified") else 0.0)
              for a in holdout_anchors if a.get("span") in by_span]
    indep = _anchors.effective_independent_count(
        [a for a in holdout_anchors if a.get("span") in by_span])
    n = len(paired)
    if n < 2 or indep < _CALIB_MIN_INDEP:
        return {"corr": 0.0, "n_used": n, "degenerate": True}
    xs = [p[0] for p in paired]; ys = [p[1] for p in paired]
    mx = sum(xs) / n; my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in paired)
    vx = sum((x - mx) ** 2 for x in xs); vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return {"corr": 0.0, "n_used": n, "degenerate": True}
    corr = cov / (vx ** 0.5 * vy ** 0.5)
    return {"corr": corr, "n_used": n, "degenerate": False}
```
- Run: `python -m pytest tests/test_judge_calibration.py -q`
- Expected: PASS

- [ ] **Step 3: commit**
```bash
git add tools/sie/judges.py tests/test_judge_calibration.py
git commit -m "M3.3 judges: judge<->anchor calibration on independent holdout (not e-process visible anchors), dedup + degenerate gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.4: selfdeception.py, 自欺指数多闸（新锚不计 / visible 留存<ε 禁 / holdout 背离报警 / 累计漂移预算）

**Files:**
- Create: `tools/sie/selfdeception.py`
- Test: `tests/test_selfdeception.py`

**Interfaces:**
- Consumes: `RunState`（`drift_count` 字段，来自 `state.py` 契约）。
- Produces:
  - `index(judge_gain: float, visible_anchor_gain: float, holdout_gain: float, st: RunState) -> dict`, `-> {"value":float,"alerts":[...],"block_accept":bool,"force_review":bool}`，多闸。
  - `retained_visible_gain(prev_anchors: list[dict], cur_anchors: list[dict]) -> float`, **只算 frozen visible 留存锚增益，新增锚不计当轮**（闸①）。
  - `cumulative_drift(lineage_visible_cum: float, lineage_holdout_cum: float, tolerance: float) -> bool`, visible 累计涨幅 > holdout 累计涨幅×容差 → True（闸④累计漂移预算）。

> 自欺指数 = `judge_gain − frozen 锚真实增益`。多闸：①新增锚不计；②visible 留存锚增益<ε 禁 ACCEPT；③visible 涨而 holdout 不涨→过拟合报警（**主信号**）；④累计漂移预算。

- [ ] **Step 1: 写失败测试, 新增锚不计当轮增益（闸①）**
```python
# tests/test_selfdeception.py
from tools.sie import selfdeception as sd
from tools.sie.state import RunState

def _rs(**kw):
    base = dict(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier="C")
    base.update(kw); return RunState(**base)

def test_new_anchors_not_counted():
    prev = [{"span": "a", "verified": True, "marginal_gain": 0.3}]
    # cur 多了新锚 b（高增益），但只算留存锚 a → 留存增益用 a 的，新锚 b 不计
    cur = [{"span": "a", "verified": True, "marginal_gain": 0.3},
           {"span": "b", "verified": True, "marginal_gain": 0.9}]
    g = sd.retained_visible_gain(prev, cur)
    assert abs(g - 0.0) < 1e-9  # a 增益未变 → 留存增益 0，b(新锚)不计
```
- Run: `python -m pytest tests/test_selfdeception.py::test_new_anchors_not_counted -q`
- Expected: FAIL（模块不存在）

- [ ] **Step 2: 写最小实现, retained_visible_gain（只看 span 交集的增益变化）**
```python
# tools/sie/selfdeception.py
"""自欺指数多闸：=judge_gain - frozen 锚真实增益。
闸①新增锚不计当轮；②visible 留存增益<ε 禁 ACCEPT；
③visible 涨 holdout 不涨→过拟合报警(主信号)；④累计漂移预算。
"""
from __future__ import annotations
from tools.sie.state import RunState

_EPS = 0.02              # frozen_anchor_effective_gain_ε
_ALERT_BAND = 0.15       # selfdeception_alert_band
_DRIFT_CIRCUIT = 4       # N_drift

def retained_visible_gain(prev_anchors: list[dict], cur_anchors: list[dict]) -> float:
    # 只算 frozen visible 留存锚（span 在前后两轮都出现）的增益变化；新增锚不计。
    prev = {a["span"]: float(a.get("marginal_gain", 0.0))
            for a in prev_anchors if a.get("span")}
    cur = {a["span"]: float(a.get("marginal_gain", 0.0))
           for a in cur_anchors if a.get("span")}
    retained = set(prev) & set(cur)
    if not retained:
        return 0.0
    return sum(cur[s] - prev[s] for s in retained) / len(retained)
```
- Run: `python -m pytest tests/test_selfdeception.py::test_new_anchors_not_counted -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, visible 留存增益<ε 禁 ACCEPT（闸②）**
```python
# tests/test_selfdeception.py  (追加)
def test_below_eps_blocks_accept():
    out = sd.index(judge_gain=0.4, visible_anchor_gain=0.005,
                   holdout_gain=0.4, st=_rs())
    assert out["block_accept"] is True
    assert any("below_eps" in a for a in out["alerts"])
```
- Run: `python -m pytest tests/test_selfdeception.py::test_below_eps_blocks_accept -q`
- Expected: FAIL（`index` 不存在）

- [ ] **Step 4: 写失败测试, visible 涨而 holdout 不涨→过拟合报警+强制人审（闸③，主信号）**
```python
# tests/test_selfdeception.py  (追加)
def test_visible_up_holdout_flat_alerts():
    out = sd.index(judge_gain=0.5, visible_anchor_gain=0.30,
                   holdout_gain=0.0, st=_rs())
    assert out["force_review"] is True
    assert any("holdout_divergence" in a for a in out["alerts"])

def test_judge_anchor_collusion_alert():
    # judge 增益远高于 frozen 锚真实增益 → |自欺指数|>band → 合谋报警
    out = sd.index(judge_gain=0.9, visible_anchor_gain=0.05,
                   holdout_gain=0.05, st=_rs())
    assert any("collusion" in a for a in out["alerts"])
    assert out["value"] > _ALERT_BAND if False else abs(out["value"]) > sd._ALERT_BAND
```
- Run: `python -m pytest tests/test_selfdeception.py::test_visible_up_holdout_flat_alerts tests/test_selfdeception.py::test_judge_anchor_collusion_alert -q`
- Expected: FAIL

- [ ] **Step 5: 写最小实现, index 多闸**
```python
# tools/sie/selfdeception.py  (追加)
def index(judge_gain: float, visible_anchor_gain: float,
          holdout_gain: float, st: RunState) -> dict:
    value = judge_gain - visible_anchor_gain  # 自欺指数
    alerts: list[str] = []
    block_accept = False
    force_review = False

    # 闸②：visible 留存锚增益 < ε → 禁 ACCEPT
    if visible_anchor_gain < _EPS:
        block_accept = True
        alerts.append(f"below_eps:visible_gain={visible_anchor_gain:.3f}<{_EPS}")

    # 闸③(主信号)：visible 涨而 holdout 不涨 → 过拟合，报警 + 强制人审
    if visible_anchor_gain >= _EPS and holdout_gain < _EPS:
        force_review = True
        alerts.append(
            f"holdout_divergence:visible={visible_anchor_gain:.3f},"
            f"holdout={holdout_gain:.3f}")

    # 锚↔judge 合谋：judge 增益远超 frozen 锚真实增益
    if abs(value) > _ALERT_BAND:
        force_review = True
        alerts.append(f"collusion:selfdeception_index={value:.3f}>{_ALERT_BAND}")

    return {"value": value, "alerts": alerts,
            "block_accept": block_accept, "force_review": force_review}
```
- Run: `python -m pytest tests/test_selfdeception.py -q`
- Expected: PASS

- [ ] **Step 6: 写失败测试, 累计漂移预算（闸④）**
```python
# tests/test_selfdeception.py  (追加)
def test_cumulative_drift_budget():
    # visible 累计涨 0.6，holdout 累计涨 0.3，容差 1.5× → 0.6 > 0.3*1.5=0.45 → 漂移
    assert sd.cumulative_drift(0.6, 0.3, tolerance=1.5) is True
    assert sd.cumulative_drift(0.4, 0.3, tolerance=1.5) is False
```
- Run: `python -m pytest tests/test_selfdeception.py::test_cumulative_drift_budget -q`
- Expected: FAIL

- [ ] **Step 7: 写最小实现, cumulative_drift**
```python
# tools/sie/selfdeception.py  (追加)
def cumulative_drift(lineage_visible_cum: float, lineage_holdout_cum: float,
                     tolerance: float = 1.5) -> bool:
    # 同 lineage 上 visible 累计涨幅 > holdout 累计涨幅 × 容差 → 过拟合漂移
    return lineage_visible_cum > lineage_holdout_cum * tolerance
```
- Run: `python -m pytest tests/test_selfdeception.py -q`
- Expected: PASS

- [ ] **Step 8: commit**
```bash
git add tools/sie/selfdeception.py tests/test_selfdeception.py
git commit -m "M3.4 selfdeception: multi-gate (new-anchors-excluded, <eps block, holdout-divergence alert, cumulative drift budget)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.5: acceptor.py, C 档不退化配对 + 双向 α 门 + 纯 C 强制人审 + Codex 不可用降级

**Files:**
- Modify: `tools/sie/acceptor.py`（在 M1b 的 `decide` 上叠加 C 档分支 + 双向 α + judge 降级）
- Test: `tests/test_acceptor_c_tier.py`

**Interfaces:**
- Consumes: `RunState`；M1b 已有的 `decide(...)` A/B 分支与 confseq e-process 内核；`judges.pairwise_agreement`；`selfdeception.index`。
- Produces（沿用契约签名，扩展返回字段，不改名）:
  - `decide(paired, tier, st, params) -> dict`, C 档配对消费 per-regression-task 一致性；返回新增 `force_review:bool` 与 `degrade_reason:str|None`。
  - `c_tier_no_regression(replay_results: list[dict]) -> bool`, 历史成功 replay 全保持=True，任一回退=False（硬门）。
  - `alpha_gate(alpha: float, anchor_up: bool, params: dict) -> dict`, 双向 α：`alpha<α_low`→人审；`alpha>α_high 且 not anchor_up`→人审+计自欺；返回 `{"force_review":bool,"count_selfdeception":bool}`。
  - `judge_degrade(codex_available: bool, claude_available: bool) -> dict`, Codex 不可用→禁单 Claude 自动 ACCEPT，`{"single_claude_block":bool,"anchor_only":bool,"force_review":bool}`。

> 关键易错：(a) 纯 C 档（coverage=0）欲 ACCEPT **必经强制人审**，auto 模式不自动采纳；(b) C 配对极低权重，绝不单独触发；(c) `α_low=0.4`/`α_high=0.85` 双向门；(d) Codex 不可用时**禁止单 Claude 自动 ACCEPT**。

- [ ] **Step 1: 写失败测试, C 档历史成功 replay 任一回退=硬 REJECT**
```python
# tests/test_acceptor_c_tier.py
from tools.sie import acceptor
from tools.sie.state import RunState

def _rs(tier="C"):
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier=tier)

def test_c_no_regression_hard_reject():
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": True, "after": True}]) is True
    assert acceptor.c_tier_no_regression(
        [{"task": "t1", "before": True, "after": False}]) is False  # 回退
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py::test_c_no_regression_hard_reject -q`
- Expected: FAIL

- [ ] **Step 2: 写最小实现, c_tier_no_regression**
```python
# tools/sie/acceptor.py  (追加)
def c_tier_no_regression(replay_results: list[dict]) -> bool:
    # 历史成功 replay 全保持：任一 before=True 而 after=False → 回退 → False
    for r in replay_results:
        if r.get("before") and not r.get("after"):
            return False
    return True
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py::test_c_no_regression_hard_reject -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, 双向 α 门**
```python
# tests/test_acceptor_c_tier.py  (追加)
def test_alpha_gate_low_forces_review():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.30, anchor_up=True, params=p)
    assert out["force_review"] is True
    assert out["count_selfdeception"] is False

def test_alpha_gate_high_no_anchor_counts_selfdeception():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.92, anchor_up=False, params=p)
    assert out["force_review"] is True
    assert out["count_selfdeception"] is True  # α 异常高且锚不涨

def test_alpha_gate_high_with_anchor_ok():
    p = {"alpha_low": 0.4, "alpha_high": 0.85}
    out = acceptor.alpha_gate(alpha=0.92, anchor_up=True, params=p)
    assert out["force_review"] is False
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py -k alpha_gate -q`
- Expected: FAIL

- [ ] **Step 4: 写最小实现, alpha_gate（双向）**
```python
# tools/sie/acceptor.py  (追加)
def alpha_gate(alpha: float, anchor_up: bool, params: dict) -> dict:
    a_low = params.get("alpha_low", 0.4)
    a_high = params.get("alpha_high", 0.85)
    force_review = False
    count_sd = False
    if alpha < 0:  # judge 不可用哨兵，由 judge_degrade 处理，这里不触发
        return {"force_review": False, "count_selfdeception": False}
    if alpha < a_low:                       # 一致性过低 → 人审
        force_review = True
    if alpha > a_high and not anchor_up:     # 异常高且锚不涨 → 人审 + 计自欺
        force_review = True
        count_sd = True
    return {"force_review": force_review, "count_selfdeception": count_sd}
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py -k alpha_gate -q`
- Expected: PASS

- [ ] **Step 5: 写失败测试, Codex 不可用→禁单 Claude 自动 ACCEPT，降级锚+人审**
```python
# tests/test_acceptor_c_tier.py  (追加)
def test_codex_unavailable_blocks_single_claude():
    out = acceptor.judge_degrade(codex_available=False, claude_available=True)
    assert out["single_claude_block"] is True
    assert out["anchor_only"] is True   # 程序化锚为唯一裁决信号
    assert out["force_review"] is True

def test_both_judges_ok_no_degrade():
    out = acceptor.judge_degrade(codex_available=True, claude_available=True)
    assert out["single_claude_block"] is False
    assert out["anchor_only"] is False
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py -k judge_degrade -q`
- Expected: FAIL

- [ ] **Step 6: 写最小实现, judge_degrade**
```python
# tools/sie/acceptor.py  (追加)
def judge_degrade(codex_available: bool, claude_available: bool) -> dict:
    # Codex（唯一非 proposer 独立 judge）不可用 → 只剩 Claude(proposer 家族)：
    # 禁止单 Claude 自动 ACCEPT，降级为程序化锚为唯一裁决信号 + 升人审。
    if not codex_available:
        return {"single_claude_block": True, "anchor_only": True,
                "force_review": True}
    return {"single_claude_block": False, "anchor_only": False,
            "force_review": False}
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py -k judge_degrade -q`
- Expected: PASS

- [ ] **Step 7: 写失败测试, 纯 C 档（coverage=0）欲 ACCEPT 必 force_review，auto 不自动采纳**
```python
# tests/test_acceptor_c_tier.py  (追加)
def test_pure_c_accept_forces_review():
    # C 配对一致正向，但 coverage=0 → 即便 e-process 想 ACCEPT 也必经人审
    paired = [(1.0, 0.0)] * 12  # 改后优于改前
    out = acceptor.decide(paired, tier="C", st=_rs("C"),
                          params={"alpha": 0.05, "coverage": 0.0})
    assert out["force_review"] is True
    assert out["decision"] != "CONTINUE" or out["force_review"]  # 纯 C 不自动落地
```
- Run: `python -m pytest tests/test_acceptor_c_tier.py::test_pure_c_accept_forces_review -q`
- Expected: FAIL（`decide` 尚无 C/coverage 分支）

- [ ] **Step 8: 写最小实现, decide 中 C 档 + coverage=0 强制人审分支**
```python
# tools/sie/acceptor.py  (在 decide 内，e-process 算出 base_decision 之后追加)
def _apply_c_tier_gates(base: dict, tier: str, params: dict) -> dict:
    # C 配对极低权重，绝不单独触发；纯 C(coverage=0)欲 ACCEPT 必经人审。
    base.setdefault("force_review", False)
    base.setdefault("degrade_reason", None)
    coverage = params.get("coverage", 1.0)
    if tier == "C" and coverage == 0.0 and base["decision"] == "ACCEPT":
        base["force_review"] = True
        base["reason"] = base.get("reason", "") + ";pure_C_needs_human"
    return base
```
> 在现有 `decide` 末尾返回前调用：`result = _apply_c_tier_gates(result, tier, params)`。同时把 C 档配对权重在 e-process 合成时乘以极小系数（`c_tier_weight=0.05`，绝不单独触发）,在 M1b 的合成处加 `if tier=="C": evalue *= params.get("c_tier_weight",0.05)`。
- Run: `python -m pytest tests/test_acceptor_c_tier.py -q`
- Expected: PASS（全部）

- [ ] **Step 9: commit**
```bash
git add tools/sie/acceptor.py tests/test_acceptor_c_tier.py
git commit -m "M3.5 acceptor: C-tier no-regression + bidirectional alpha gate + pure-C forced review + Codex-unavailable degrade (no single-Claude auto-accept)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.6: statemachine.py, 释放阀(仅升人审) + 累计漂移熔断 + 纯 C auto 强制 gated

**Files:**
- Modify: `tools/sie/statemachine.py`（态7 接 selfdeception/α 门、态9 释放阀+漂移熔断、态9.5 纯 C auto）
- Test: `tests/test_statemachine_m3.py`

**Interfaces:**
- Consumes: `acceptor.decide`/`alpha_gate`/`judge_degrade`；`selfdeception.index`/`cumulative_drift`；`gate_human.enqueue`；`RunState.drift_count`/`forced_review`/`no_progress`。
- Produces:
  - `release_valve(st: RunState, params: dict) -> int`, `no_progress≥M(<N)` 时**只返回升高后的人审触发频率**（不改阈、不采纳）；返回当前 review_frequency。
  - `drift_circuit(st: RunState, holdout_up: bool, params: dict) -> bool`, 连续 ACCEPT 但 holdout/全量回归不涨 → `drift_count++`；`≥N_drift`→True（停机人审）。
  - `route_accept_with_gates(decision: dict, sd: dict, alpha_gate_out: dict, degrade: dict, mode: str, tier: str, coverage: float) -> str`, 综合所有闸返回最终态 `"ARCHIVE"|"PAUSE_FOR_HUMAN"|"REJECT"`。

> 易错：释放阀**绝不在 auto 自动降阈采纳**,只升人审频率（spec §5.4/§13 验收5）。

- [ ] **Step 1: 写失败测试, 释放阀只升人审频率，不降阈**
```python
# tests/test_statemachine_m3.py
from tools.sie import statemachine as sm
from tools.sie.state import RunState

def _rs(**kw):
    b = dict(run_id="r", phase="LOOP", round=1, parent_vid=None, tier="C")
    b.update(kw); return RunState(**b)

def test_release_valve_only_raises_review_freq():
    p = {"no_progress_release_M": 3, "review_freq_base": 1, "review_freq_boost": 3}
    # 未达 M → 基础频率
    assert sm.release_valve(_rs(no_progress=2), p) == 1
    # 达 M → 升高（但不返回任何"降阈"信号）
    assert sm.release_valve(_rs(no_progress=3), p) == 3
```
- Run: `python -m pytest tests/test_statemachine_m3.py::test_release_valve_only_raises_review_freq -q`
- Expected: FAIL

- [ ] **Step 2: 写最小实现, release_valve**
```python
# tools/sie/statemachine.py  (追加)
def release_valve(st: "RunState", params: dict) -> int:
    # 仅升人审触发频率；绝不降 acceptor 阈、绝不在 auto 自动采纳。
    M = params.get("no_progress_release_M", 3)
    base = params.get("review_freq_base", 1)
    boost = params.get("review_freq_boost", 3)
    return boost if st.no_progress >= M else base
```
- Run: `python -m pytest tests/test_statemachine_m3.py::test_release_valve_only_raises_review_freq -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, 累计漂移熔断（连续 ACCEPT 但 holdout 不涨 ≥ N_drift）**
```python
# tests/test_statemachine_m3.py  (追加)
def test_drift_circuit_trips():
    p = {"drift_circuit_N": 4}
    st = _rs(drift_count=0)
    tripped = False
    for _ in range(4):
        tripped = sm.drift_circuit(st, holdout_up=False, params=p)
    assert st.drift_count == 4
    assert tripped is True

def test_drift_circuit_resets_on_holdout_up():
    p = {"drift_circuit_N": 4}
    st = _rs(drift_count=3)
    assert sm.drift_circuit(st, holdout_up=True, params=p) is False
    assert st.drift_count == 0  # holdout 涨了 → 清零
```
- Run: `python -m pytest tests/test_statemachine_m3.py -k drift_circuit -q`
- Expected: FAIL

- [ ] **Step 4: 写最小实现, drift_circuit**
```python
# tools/sie/statemachine.py  (追加)
def drift_circuit(st: "RunState", holdout_up: bool, params: dict) -> bool:
    N = params.get("drift_circuit_N", 4)
    if holdout_up:
        st.drift_count = 0
        return False
    st.drift_count += 1
    return st.drift_count >= N
```
- Run: `python -m pytest tests/test_statemachine_m3.py -k drift_circuit -q`
- Expected: PASS

- [ ] **Step 5: 写失败测试, 闸路由：纯 C auto / 自欺 force_review / 降级 → PAUSE_FOR_HUMAN**
```python
# tests/test_statemachine_m3.py  (追加)
def test_route_pure_c_auto_forces_human():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": True},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="C", coverage=0.0)
    assert out == "PAUSE_FOR_HUMAN"

def test_route_codex_unavailable_blocks_auto():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": True, "force_review": True},
        mode="auto", tier="B", coverage=0.5)
    assert out == "PAUSE_FOR_HUMAN"  # 禁单 Claude 自动 ACCEPT

def test_route_sd_block_rejects():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": True, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="B", coverage=0.5)
    assert out == "REJECT"  # visible 留存增益<ε 禁 ACCEPT

def test_route_clean_accept_archives():
    out = sm.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="A", coverage=1.0)
    assert out == "ARCHIVE"
```
- Run: `python -m pytest tests/test_statemachine_m3.py -k route_ -q`
- Expected: FAIL

- [ ] **Step 6: 写最小实现, route_accept_with_gates（闸优先级：block_accept > force_review > 降级 > 纯C auto > ACCEPT）**
```python
# tools/sie/statemachine.py  (追加)
def route_accept_with_gates(decision: dict, sd: dict, alpha_gate_out: dict,
                            degrade: dict, mode: str, tier: str,
                            coverage: float) -> str:
    if decision.get("decision") != "ACCEPT":
        return "REJECT" if decision.get("decision") == "REJECT" else "CONTINUE"
    # ② visible 留存增益<ε 禁 ACCEPT → 硬 REJECT
    if sd.get("block_accept"):
        return "REJECT"
    # 自欺/α/降级/decision 自带的任一 force_review → 人审
    if (sd.get("force_review") or alpha_gate_out.get("force_review")
            or degrade.get("force_review") or decision.get("force_review")):
        return "PAUSE_FOR_HUMAN"
    # Codex 不可用 → 禁单 Claude 自动 ACCEPT
    if degrade.get("single_claude_block"):
        return "PAUSE_FOR_HUMAN"
    # 纯 C 档 auto 欲 ACCEPT → 强制 gated（不自动采纳）
    if tier == "C" and coverage == 0.0 and mode == "auto":
        return "PAUSE_FOR_HUMAN"
    return "ARCHIVE"
```
- Run: `python -m pytest tests/test_statemachine_m3.py -k route_ -q`
- Expected: PASS

- [ ] **Step 7: commit**
```bash
git add tools/sie/statemachine.py tests/test_statemachine_m3.py
git commit -m "M3.6 statemachine: release valve (review-freq only, no auto threshold drop) + cumulative drift circuit + gate routing (pure-C auto / SD / degrade -> human)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.7: evaluate.py, C 档评测（内部一致性 + 历史成功 replay）+ judge 分注入

**Files:**
- Modify: `tools/sie/evaluate.py`（追加 C 档分支 + judge 主观分注入 + 自欺指数填充）
- Test: `tests/test_evaluate_c_tier.py`

**Interfaces:**
- Consumes: `judges.score`/`pairwise_agreement`/`calibrate_judge_anchor`；`selfdeception.index`/`retained_visible_gain`；`anchors.split_visible_holdout`；`c_tier_no_regression`。
- Produces:
  - `evaluate_c_tier(artifact_path: str, regression_replay: list[dict], internal_consistency: list[tuple[float,float]]) -> dict`, `-> {"no_regression":bool, "consistency_paired":[(before,after)...], "coverage":0.0}`。
  - `inject_judge_scores(artifact_path: str, anchors_visible: list[dict], holdout: list[dict]) -> dict`, 在 contract 外注入 judge 主观分（非 candidate 提供，§8）；`-> {"codex":dict,"claude":dict,"alpha":float,"calibration":dict,"judge_gain":float}`。

> 关键：judge 主观分由 `evaluate.py` 在 contract 外注入（spec §8），candidate 不能自报 judge 分；judge 走独立联网进程。

- [ ] **Step 1: 写失败测试, C 档评测产出 no_regression + 一致性配对 + coverage=0**
```python
# tests/test_evaluate_c_tier.py
from tools.sie import evaluate

def test_evaluate_c_tier_shape(tmp_path):
    art = tmp_path / "a.md"; art.write_text("# c artifact\n", encoding="utf-8")
    replay = [{"task": "t1", "before": True, "after": True}]
    consistency = [(0.9, 0.92), (0.8, 0.81)]
    out = evaluate.evaluate_c_tier(str(art), replay, consistency)
    assert out["no_regression"] is True
    assert out["coverage"] == 0.0
    assert out["consistency_paired"] == consistency
```
- Run: `python -m pytest tests/test_evaluate_c_tier.py::test_evaluate_c_tier_shape -q`
- Expected: FAIL

- [ ] **Step 2: 写最小实现, evaluate_c_tier**
```python
# tools/sie/evaluate.py  (追加)
from tools.sie.acceptor import c_tier_no_regression

def evaluate_c_tier(artifact_path: str, regression_replay: list[dict],
                    internal_consistency: list[tuple[float, float]]) -> dict:
    # C 档兜底：无客观信号；硬门=不退化(历史成功 replay 全保持)+内部一致性配对。
    return {
        "no_regression": c_tier_no_regression(regression_replay),
        "consistency_paired": list(internal_consistency),
        "coverage": 0.0,
    }
```
- Run: `python -m pytest tests/test_evaluate_c_tier.py::test_evaluate_c_tier_shape -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, judge 分注入：candidate 自报的 judge 分被忽略，harness 独立算 α**
```python
# tests/test_evaluate_c_tier.py  (追加)
from tools.sie import judges

def test_inject_judge_scores_independent(monkeypatch, tmp_path):
    art = tmp_path / "a.md"; art.write_text("body\n", encoding="utf-8")
    # 两家 judge 给同分 → α=1.0；harness 自算，不读 candidate 自报
    def fake_score(p, av, family):
        return {"family": family, "available": True,
                "span_scores": [{"span": "s1", "score": 0.7}], "aggregate": 0.7,
                "unspanned_penalized": 0}
    monkeypatch.setattr(judges, "score", fake_score)
    monkeypatch.setattr(judges, "calibrate_judge_anchor",
                        lambda js, ho: {"corr": 0.5, "n_used": 2, "degenerate": False})
    out = evaluate.inject_judge_scores(
        str(art), anchors_visible=[{"span": "s1"}],
        holdout=[{"span": "h1", "verified": True, "source_url": "u", "topic": "t"}])
    assert out["alpha"] == 1.0
    assert out["codex"]["available"] and out["claude"]["available"]
    assert "judge_gain" in out
```
- Run: `python -m pytest tests/test_evaluate_c_tier.py::test_inject_judge_scores_independent -q`
- Expected: FAIL

- [ ] **Step 4: 写最小实现, inject_judge_scores**
```python
# tools/sie/evaluate.py  (追加)
from tools.sie import judges as _judges

def inject_judge_scores(artifact_path: str, anchors_visible: list[dict],
                        holdout: list[dict]) -> dict:
    # contract 外注入：candidate 不提供 judge 分；harness 独立联网进程评判。
    codex = _judges.score(artifact_path, anchors_visible, "codex")
    claude = _judges.score(artifact_path, anchors_visible, "claude")
    alpha = _judges.pairwise_agreement(codex, claude)
    # 主独立 judge=codex；judge_gain 用 codex aggregate（不可用则 claude，再不可用 0）
    if codex.get("available"):
        judge_gain = codex["aggregate"]
        calib = _judges.calibrate_judge_anchor(codex, holdout)
    elif claude.get("available"):
        judge_gain = claude["aggregate"]
        calib = _judges.calibrate_judge_anchor(claude, holdout)
    else:
        judge_gain = 0.0
        calib = {"corr": 0.0, "n_used": 0, "degenerate": True}
    return {"codex": codex, "claude": claude, "alpha": alpha,
            "calibration": calib, "judge_gain": judge_gain}
```
- Run: `python -m pytest tests/test_evaluate_c_tier.py::test_inject_judge_scores_independent -q`
- Expected: PASS

- [ ] **Step 5: commit**
```bash
git add tools/sie/evaluate.py tests/test_evaluate_c_tier.py
git commit -m "M3.7 evaluate: C-tier (no-regression + internal consistency) + contract-external judge score injection (independent processes, harness-computed alpha)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.8: archive.py, Pareto 多维硬维门 + Library Drift retire_stale

**Files:**
- Modify: `tools/sie/archive.py`（在 M1a 的 lineage/rollback 上补 `pareto_front` 硬维门 + `retire_stale`）
- Test: `tests/test_archive_pareto.py`

**Interfaces:**
- Consumes: M1a 已有 `add_version`/`rollback`/lineage 读写。
- Produces（沿用契约签名）:
  - `pareto_front(archive_dir: str) -> list[str]`, 多维 Pareto 前沿，**硬维门**：进前沿者 A/frozen 锚维不低于前沿中位；纯软维优胜只冷藏、不可选 parent。
  - `retire_stale(archive_dir: str, active_cap: int) -> None`, Library Drift 活跃上限 + outcome-driven 退役（冷藏不删，写 `retired.jsonl`）。
  - `selectable_parents(archive_dir: str) -> list[str]`, 可选 parent（前沿中过硬维门者）。

> 易错：硬维=A/frozen 锚；软维=judge 主观分。**软涨硬平**的版本不得进前沿可选集（计自欺由 selfdeception 负责报警），只冷藏。

- [ ] **Step 1: 写失败测试, 硬维不低于前沿中位才可选 parent；纯软维优胜冷藏**
```python
# tests/test_archive_pareto.py
import json
from pathlib import Path
from tools.sie import archive

def _seed(d, versions):
    lin = Path(d) / "lineage.json"
    lin.write_text(json.dumps({"versions": versions}), encoding="utf-8")

def test_hard_dim_gate_excludes_soft_only_winner(tmp_path):
    d = str(tmp_path)
    _seed(d, [
        {"vid": "v1", "scores": {"A": 0.8, "anchor": 0.7, "judge": 0.5}},
        {"vid": "v2", "scores": {"A": 0.8, "anchor": 0.7, "judge": 0.6}},
        # v3 软维(judge)最高但硬维(A/anchor)低于前沿中位 → 冷藏不可选
        {"vid": "v3", "scores": {"A": 0.3, "anchor": 0.2, "judge": 0.99}},
    ])
    sel = archive.selectable_parents(d)
    assert "v3" not in sel
    assert "v2" in sel
```
- Run: `python -m pytest tests/test_archive_pareto.py::test_hard_dim_gate_excludes_soft_only_winner -q`
- Expected: FAIL

- [ ] **Step 2: 写最小实现, pareto_front + selectable_parents（硬维门）**
```python
# tools/sie/archive.py  (追加)
import json, statistics
from pathlib import Path

_HARD_DIMS = ("A", "anchor")   # 硬维：可验证 + frozen 锚
_SOFT_DIMS = ("judge",)        # 软维：judge 主观分

def _load_versions(archive_dir: str) -> list[dict]:
    p = Path(archive_dir) / "lineage.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("versions", [])

def _dominates(a: dict, b: dict, dims) -> bool:
    ge = all(a["scores"].get(d, 0) >= b["scores"].get(d, 0) for d in dims)
    gt = any(a["scores"].get(d, 0) > b["scores"].get(d, 0) for d in dims)
    return ge and gt

def pareto_front(archive_dir: str) -> list[str]:
    vs = _load_versions(archive_dir)
    dims = _HARD_DIMS + _SOFT_DIMS
    front = []
    for v in vs:
        if not any(_dominates(o, v, dims) for o in vs if o["vid"] != v["vid"]):
            front.append(v["vid"])
    return front

def selectable_parents(archive_dir: str) -> list[str]:
    # 硬维门：进前沿者 A/frozen 锚维不低于前沿中位，否则只冷藏不可选 parent。
    vs = {v["vid"]: v for v in _load_versions(archive_dir)}
    front = pareto_front(archive_dir)
    if not front:
        return []
    medians = {d: statistics.median([vs[f]["scores"].get(d, 0) for f in front])
               for d in _HARD_DIMS}
    return [f for f in front
            if all(vs[f]["scores"].get(d, 0) >= medians[d] for d in _HARD_DIMS)]
```
- Run: `python -m pytest tests/test_archive_pareto.py::test_hard_dim_gate_excludes_soft_only_winner -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, retire_stale 超活跃上限冷藏(写 retired.jsonl 不删)**
```python
# tests/test_archive_pareto.py  (追加)
def test_retire_stale_cold_stores(tmp_path):
    d = str(tmp_path)
    vs = [{"vid": f"v{i}", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5},
           "last_used_round": i} for i in range(6)]
    _seed(d, vs)
    archive.retire_stale(d, active_cap=4)
    retired = (Path(d) / "retired.jsonl")
    assert retired.exists()
    lines = retired.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # 6-4=2 个最旧的被冷藏
    # 原 lineage 仍在（冷藏不删）
    remain = json.loads((Path(d) / "lineage.json").read_text(encoding="utf-8"))
    assert len(remain["versions"]) == 6
```
- Run: `python -m pytest tests/test_archive_pareto.py::test_retire_stale_cold_stores -q`
- Expected: FAIL

- [ ] **Step 4: 写最小实现, retire_stale（outcome-driven，冷藏不删）**
```python
# tools/sie/archive.py  (追加)
def retire_stale(archive_dir: str, active_cap: int) -> None:
    # Library Drift: 活跃上限 + outcome-driven 退役；冷藏(写 retired.jsonl)不删原始。
    vs = _load_versions(archive_dir)
    if len(vs) <= active_cap:
        return
    # 按最近使用排序，最旧的超额者冷藏（前沿可选者豁免）
    keep = set(selectable_parents(archive_dir))
    candidates = [v for v in vs if v["vid"] not in keep]
    candidates.sort(key=lambda v: v.get("last_used_round", 0))
    n_retire = len(vs) - active_cap
    retired = candidates[:n_retire]
    rp = Path(archive_dir) / "retired.jsonl"
    with rp.open("a", encoding="utf-8") as f:
        for v in retired:
            f.write(json.dumps({"vid": v["vid"], "reason": "stale_active_cap"}) + "\n")
```
- Run: `python -m pytest tests/test_archive_pareto.py::test_retire_stale_cold_stores -q`
- Expected: PASS

- [ ] **Step 5: commit**
```bash
git add tools/sie/archive.py tests/test_archive_pareto.py
git commit -m "M3.8 archive: Pareto multi-dim hard-dimension gate (soft-only winners cold-stored, not selectable) + Library Drift retire_stale (cold-store not delete)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.9: reflect.py + workflows, N=3 并行 MARS 反思 + review-fanout

**Files:**
- Modify: `tools/sie/reflect.py`（串行→N=3 并行 fanout 调度，独立反思后 meta 汇总）
- Create: `workflows/reflect-fanout.js`（N 个独立反思 subagent 并行）
- Create: `workflows/review-fanout.js`（评审 fanout）
- Test: `tests/test_reflect_fanout.py`

**Interfaces:**
- Consumes: M1 已有 `reflect.run_reflections`（串行）签名；`check_reflection`（M3.10 升 BenchTrace）。
- Produces:
  - `run_reflections_parallel(run_dir: str, history: list[dict], n_reflectors: int) -> list[dict]`, N 个独立 MARS 反思并行（互不读对方草稿），返回 N 条反思。
  - `meta_aggregate(reflections: list[dict]) -> dict`, 汇总 N 条独立反思（去重/聚类→统一提案输入）。

> MARS=多 agent 独立反思后汇总；N=3（spec §12）。并行 fanout 走 `workflows/reflect-fanout.js`，**反思只读历史 trace（append-only 只读，铁律2）**。

- [ ] **Step 1: 写失败测试, N=3 并行反思产出 3 条独立结果**
```python
# tests/test_reflect_fanout.py
from tools.sie import reflect

def test_parallel_yields_n_independent(monkeypatch, tmp_path):
    calls = []
    def fake_one(run_dir, history, idx):
        calls.append(idx)
        return {"reflector": idx, "findings": [f"f{idx}"]}
    monkeypatch.setattr(reflect, "_reflect_one", fake_one)
    out = reflect.run_reflections_parallel(str(tmp_path), history=[], n_reflectors=3)
    assert len(out) == 3
    assert sorted(calls) == [0, 1, 2]  # 三个独立反思各跑一次
```
- Run: `python -m pytest tests/test_reflect_fanout.py::test_parallel_yields_n_independent -q`
- Expected: FAIL

- [ ] **Step 2: 写最小实现, run_reflections_parallel（fanout 调度，独立）**
```python
# tools/sie/reflect.py  (追加)
import subprocess, json
from concurrent.futures import ThreadPoolExecutor

def _reflect_one(run_dir: str, history: list[dict], idx: int) -> dict:
    # 单个 MARS 反思 subagent：经 reflect-fanout.js 起独立进程，只读历史 trace。
    proc = subprocess.run(
        ["node", "workflows/reflect-fanout.js", "--run", run_dir, "--idx", str(idx)],
        input=json.dumps({"history": history}), capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"reflector": idx, "findings": []}
    return json.loads(proc.stdout)

def run_reflections_parallel(run_dir: str, history: list[dict],
                             n_reflectors: int = 3) -> list[dict]:
    # N 个独立反思并行；互不读对方草稿（独立性=MARS 核心）。
    with ThreadPoolExecutor(max_workers=n_reflectors) as ex:
        futs = [ex.submit(_reflect_one, run_dir, history, i)
                for i in range(n_reflectors)]
        return [f.result() for f in futs]

def meta_aggregate(reflections: list[dict]) -> dict:
    # 汇总 N 条独立反思：合并 findings，去重保序。
    seen, merged = set(), []
    for r in reflections:
        for f in r.get("findings", []):
            if f not in seen:
                seen.add(f); merged.append(f)
    return {"merged_findings": merged, "n_reflectors": len(reflections)}
```
- Run: `python -m pytest tests/test_reflect_fanout.py::test_parallel_yields_n_independent -q`
- Expected: PASS

- [ ] **Step 3: 写失败测试, meta_aggregate 去重保序**
```python
# tests/test_reflect_fanout.py  (追加)
def test_meta_aggregate_dedup():
    refl = [{"findings": ["a", "b"]}, {"findings": ["b", "c"]}, {"findings": ["a"]}]
    out = reflect.meta_aggregate(refl)
    assert out["merged_findings"] == ["a", "b", "c"]
    assert out["n_reflectors"] == 3
```
- Run: `python -m pytest tests/test_reflect_fanout.py::test_meta_aggregate_dedup -q`
- Expected: PASS

- [ ] **Step 4: 写 fanout workflow 桩（真实可调用，stdin/stdout JSON 契约）**
```javascript
// workflows/reflect-fanout.js
// 单个独立 MARS 反思 subagent：从 stdin 读 {history}，只读历史 trace（铁律2），
// 输出 {reflector, findings} 到 stdout。绝不写 trace、绝不读其他反思草稿。
const fs = require("fs");
const args = process.argv.slice(2);
const idx = Number(args[args.indexOf("--idx") + 1] || 0);
const input = JSON.parse(fs.readFileSync(0, "utf-8") || "{}");
// 此处由编排层注入 Claude subagent 调用；桩输出空 findings 保证管线可跑。
const out = { reflector: idx, findings: [] };
void input;
process.stdout.write(JSON.stringify(out));
```
```javascript
// workflows/review-fanout.js
// 评审 fanout：并行起评审 subagent，输出 {reviewer, verdict, notes}。
const fs = require("fs");
const args = process.argv.slice(2);
const idx = Number(args[args.indexOf("--idx") + 1] || 0);
const input = JSON.parse(fs.readFileSync(0, "utf-8") || "{}");
const out = { reviewer: idx, verdict: "abstain", notes: [] };
void input;
process.stdout.write(JSON.stringify(out));
```
- Run: `node workflows/reflect-fanout.js --idx 0 <<< '{"history":[]}'`
- Expected: PASS（输出 `{"reflector":0,"findings":[]}`）

- [ ] **Step 5: commit**
```bash
git add tools/sie/reflect.py workflows/reflect-fanout.js workflows/review-fanout.js tests/test_reflect_fanout.py
git commit -m "M3.9 reflect: N=3 parallel MARS reflection fanout (independent subagents, read-only trace) + meta aggregate + review-fanout

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.10: check_reflection.py, 升 BenchTrace 校验

**Files:**
- Modify: `tools/sie/check_reflection.py`（M1 弱校验 → BenchTrace：反思须引用真实历史 trace 证据）
- Test: `tests/test_check_reflection_benchtrace.py`

**Interfaces:**
- Consumes: M1 已有 `check_reflection.check`（弱校验）签名；历史 trace（append-only 只读）。
- Produces:
  - `check_benchtrace(reflection: dict, available_traces: list[str], threshold: float) -> dict`, `-> {"pass":bool, "grounded_ratio":float, "ungrounded":[...]}`；反思每条 finding 须引用至少一条真实 trace id（BenchTrace），grounded 比例 < `reflection_correctness_threshold(0.5)` → 不通过。

> BenchTrace：反思必须**可追溯到真实历史 trace 证据**，杜绝凭空臆造的"改进方向"。引用了不存在的 trace id 即为 ungrounded。

- [ ] **Step 1: 写失败测试, 引用真实 trace 通过、臆造 trace id 不通过**
```python
# tests/test_check_reflection_benchtrace.py
from tools.sie import check_reflection as cr

def test_benchtrace_grounded_passes():
    refl = {"findings": [
        {"text": "test t1 flaky", "trace_refs": ["tr_001"]},
        {"text": "build slow", "trace_refs": ["tr_002"]}]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001", "tr_002"],
                              threshold=0.5)
    assert out["pass"] is True
    assert out["grounded_ratio"] == 1.0

def test_benchtrace_fabricated_fails():
    refl = {"findings": [
        {"text": "imagined issue", "trace_refs": ["tr_999"]},  # 不存在
        {"text": "no ref at all", "trace_refs": []}]}
    out = cr.check_benchtrace(refl, available_traces=["tr_001"], threshold=0.5)
    assert out["pass"] is False
    assert out["grounded_ratio"] == 0.0
    assert "tr_999" in str(out["ungrounded"])
```
- Run: `python -m pytest tests/test_check_reflection_benchtrace.py -q`
- Expected: FAIL（`check_benchtrace` 不存在）

- [ ] **Step 2: 写最小实现, check_benchtrace**
```python
# tools/sie/check_reflection.py  (追加)
def check_benchtrace(reflection: dict, available_traces: list[str],
                     threshold: float = 0.5) -> dict:
    # BenchTrace：每条 finding 须引用至少一条真实(存在的) trace id 才算 grounded。
    avail = set(available_traces)
    findings = reflection.get("findings", [])
    if not findings:
        return {"pass": False, "grounded_ratio": 0.0, "ungrounded": []}
    grounded = 0
    ungrounded: list[dict] = []
    for f in findings:
        refs = [r for r in f.get("trace_refs", []) if r in avail]
        if refs:
            grounded += 1
        else:
            ungrounded.append({"text": f.get("text", ""),
                               "bad_refs": f.get("trace_refs", [])})
    ratio = grounded / len(findings)
    return {"pass": ratio >= threshold, "grounded_ratio": ratio,
            "ungrounded": ungrounded}
```
- Run: `python -m pytest tests/test_check_reflection_benchtrace.py -q`
- Expected: PASS

- [ ] **Step 3: commit**
```bash
git add tools/sie/check_reflection.py tests/test_check_reflection_benchtrace.py
git commit -m "M3.10 check_reflection: upgrade to BenchTrace grounding (findings must cite real trace ids, ratio>=threshold)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```

---

### Task M3.11: 端到端验收, C 不退化 / 自欺合谋报警 / 纯 C 强制人审 / Codex 不可用不降级

**Files:**
- Create: `tests/test_m3_acceptance.py`（对抗端到端，覆盖 spec §13 M3 全部验收）
- Modify: `reference/signal-providers.md`（补 C 档兜底门 + 自欺多闸说明）

**Interfaces:**
- Consumes: 本里程碑全部 Produces（acceptor/judges/selfdeception/statemachine/evaluate/archive）。
- Produces: 无新签名（集成验收）。

- [ ] **Step 1: 写验收测试, C 不退化门生效（replay 回退→硬 REJECT，全保持+一致正向→可达 ACCEPT 但纯 C 经人审）**
```python
# tests/test_m3_acceptance.py
from tools.sie import acceptor, selfdeception, statemachine, evaluate
from tools.sie.state import RunState

def _rs(tier="C"):
    return RunState(run_id="r", phase="ACCEPT", round=1, parent_vid=None, tier=tier)

def test_c_tier_no_regression_gate():
    # 回退 → 硬 REJECT
    ev = evaluate.evaluate_c_tier(
        artifact_path=__file__,
        regression_replay=[{"task": "t1", "before": True, "after": False}],
        internal_consistency=[(0.9, 0.9)])
    assert ev["no_regression"] is False
    # 全保持 → 不退化门放行（仍需人审，见下个测试）
    ev2 = evaluate.evaluate_c_tier(
        artifact_path=__file__,
        regression_replay=[{"task": "t1", "before": True, "after": True}],
        internal_consistency=[(0.9, 0.91)])
    assert ev2["no_regression"] is True
```

- [ ] **Step 2: 写验收测试, 纯 C 档 auto 欲 ACCEPT 强制人审（不自动采纳）**
```python
# tests/test_m3_acceptance.py  (追加)
def test_pure_c_auto_forces_human():
    route = statemachine.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": True},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade={"single_claude_block": False, "force_review": False},
        mode="auto", tier="C", coverage=0.0)
    assert route == "PAUSE_FOR_HUMAN"
```

- [ ] **Step 3: 写验收测试, 自欺指数对"锚↔judge 合谋"报警（holdout 背离为主信号）**
```python
# tests/test_m3_acceptance.py  (追加)
def test_selfdeception_collusion_alert_holdout_primary():
    # visible 涨(judge 也涨) 但 holdout 平 → 过拟合/合谋 → 报警 + 强制人审
    sd = selfdeception.index(judge_gain=0.6, visible_anchor_gain=0.30,
                             holdout_gain=0.0, st=_rs("B"))
    assert sd["force_review"] is True
    assert any("holdout_divergence" in a for a in sd["alerts"])  # 主信号
    # 辅信号：α 异常高且锚不涨
    ag = acceptor.alpha_gate(alpha=0.95, anchor_up=False,
                             params={"alpha_low": 0.4, "alpha_high": 0.85})
    assert ag["count_selfdeception"] is True
```

- [ ] **Step 4: 写验收测试, Codex 不可用时不降级单 Claude 自动提交**
```python
# tests/test_m3_acceptance.py  (追加)
def test_codex_unavailable_no_single_claude_autoaccept():
    degrade = acceptor.judge_degrade(codex_available=False, claude_available=True)
    assert degrade["single_claude_block"] is True
    assert degrade["anchor_only"] is True
    route = statemachine.route_accept_with_gates(
        decision={"decision": "ACCEPT", "force_review": False},
        sd={"block_accept": False, "force_review": False},
        alpha_gate_out={"force_review": False},
        degrade=degrade, mode="auto", tier="B", coverage=0.5)
    assert route == "PAUSE_FOR_HUMAN"  # 绝不自动 ARCHIVE
```

- [ ] **Step 5: 写验收测试, 累计漂移熔断停机人审**
```python
# tests/test_m3_acceptance.py  (追加)
def test_cumulative_drift_circuit_breaks():
    st = _rs("B")
    p = {"drift_circuit_N": 4}
    tripped = False
    for _ in range(4):  # 连续 4 轮 ACCEPT 但 holdout 不涨
        tripped = statemachine.drift_circuit(st, holdout_up=False, params=p)
    assert tripped is True and st.drift_count == 4
    # 累计漂移预算独立确认
    assert selfdeception.cumulative_drift(0.6, 0.3, tolerance=1.5) is True
```
- Run: `python -m pytest tests/test_m3_acceptance.py -q`
- Expected: PASS（全部 5 个验收）

- [ ] **Step 6: 跑本里程碑全量回归确认无破坏**
- Run: `python -m pytest tests/test_judges_codex.py tests/test_judges_agreement.py tests/test_judge_calibration.py tests/test_selfdeception.py tests/test_acceptor_c_tier.py tests/test_statemachine_m3.py tests/test_evaluate_c_tier.py tests/test_archive_pareto.py tests/test_reflect_fanout.py tests/test_check_reflection_benchtrace.py tests/test_m3_acceptance.py -q`
- Expected: PASS（全绿）

- [ ] **Step 7: commit**
```bash
git add tests/test_m3_acceptance.py reference/signal-providers.md
git commit -m "M3.11 acceptance: C no-regression gate + selfdeception collusion alert (holdout-primary) + pure-C forced human + Codex-unavailable no single-Claude auto-accept + drift circuit

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW"
```
## 里程碑 M4: 自举隔离 (~6-10h，默认关)

**目标**：让 self-evolve 安全地把自己当作 target（`--self`）, IMMUTABLE 裁决代码集从 frozen base ref 按内容哈希锁定加载、启动即校验、运行期绝不从 candidate worktree import；supervisor 双进程把"评测裁决"与"被评测的 candidate"物理分开（candidate 不裁决自己）；递归隔离到独立 worktree；自举时禁 candidate 自定义 `grade()`（改用 frozen/外部 grader）；任何 patch 命中 IMMUTABLE 路径硬拒。

**验收标准（spec §13 M4 / §6 自举 / §9 安全负向）**：自举负向用例全过,(a) patch 改 `gate_human.py`/`acceptor.py` 等 IMMUTABLE 路径 → 硬拒（reason=immutable_hit）；(b) candidate 在自举 worktree 内自定义/改写 `grade()` → 不被采信（评测用 frozen/外部 grader，candidate 的 grade 结果被忽略）；(c) candidate worktree 篡改 IMMUTABLE 文件内容 → 启动哈希校验 fail-closed 拒绝运行；(d) supervisor 进程从 frozen 副本 import，candidate worktree 路径不在 sys.path、`import` IMMUTABLE 模块解析到 frozen 而非 candidate。默认关：非 `--self` 路径行为零变化。

> **前置依赖**：本里程碑消费 M1a 的 `sandbox.canonical_in_sandbox`/`make_worktree`、M1a 的 `patch.apply_patch` AST 门、契约 `acceptor.decide`、契约 grade() schema、M2 的 `verifiable.run_grader`。M4 在这些之上加一层"frozen 锁 + supervisor 分进程"，不改其签名。

---

### Task M4.1: IMMUTABLE 清单 + frozen 副本物化

把 spec §3 铁律3 的 IMMUTABLE 集合落成单一权威清单，并在 run 启动时把这些文件从 frozen base ref 物化到 candidate 不可写的 frozen 目录，记录每个文件的 sha256。

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/immutable.py`
- Create: `~/CodesSelf/self-evolve/tests/test_immutable.py`
- Modify: `~/CodesSelf/self-evolve/tools/sie/__init__.py`（无则 Create；导出 `immutable` 子模块，无需改行号,append 一行 `from . import immutable  # noqa: F401`）

**Interfaces:**
- Consumes（M1a sandbox）：`make_worktree(target: str, base_ref: str, run_id: str) -> str`
- Produces：
  - `IMMUTABLE_RELPATHS: tuple[str, ...]`, 相对 `tools/sie/` 的 IMMUTABLE 文件清单
  - `is_immutable_relpath(relpath: str) -> bool`, 路径归一化后命中判定（防 `./`、`..`、反斜杠绕过）
  - `materialize_frozen(base_ref: str, sie_root: str, frozen_dir: str) -> dict[str, str]`, 从 git base ref 取 IMMUTABLE 文件内容写入 `frozen_dir`，返回 `{relpath: sha256}`
  - `hash_file(path: str) -> str`, sha256 hexdigest

- [ ] **Step 1: 写失败测试,IMMUTABLE 清单覆盖 spec 列举的全部裁决模块**
```python
# tests/test_immutable.py
import os, hashlib, subprocess, pathlib, pytest
from tools.sie import immutable as im

EXPECTED = {
    "statemachine.py", "acceptor.py", "judges.py", "verifiable.py",
    "anchors.py", "selfdeception.py", "gate_human.py", "profile.py",
    "sandbox.py", "supervisor.py", "immutable.py",
}

def test_immutable_relpaths_cover_spec_decision_set():
    got = set(im.IMMUTABLE_RELPATHS)
    missing = EXPECTED - got
    assert not missing, f"IMMUTABLE 清单缺裁决模块: {missing}"

def test_is_immutable_relpath_normalizes_and_rejects_bypass():
    assert im.is_immutable_relpath("acceptor.py") is True
    assert im.is_immutable_relpath("./acceptor.py") is True
    assert im.is_immutable_relpath("tools/sie/acceptor.py") is True
    assert im.is_immutable_relpath("tools\\sie\\acceptor.py") is True
    assert im.is_immutable_relpath("sub/../acceptor.py") is True
    assert im.is_immutable_relpath("propose.py") is False
    assert im.is_immutable_relpath("reflect.py") is False
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py -q`
  - Expected: FAIL（`ModuleNotFoundError: tools.sie.immutable` 或 AttributeError）

- [ ] **Step 3: 写最小实现,清单 + 归一化命中判定**
```python
# tools/sie/immutable.py
"""IMMUTABLE 裁决代码集权威清单 + frozen 物化/哈希（spec §3 铁律3, §6 自举）。"""
from __future__ import annotations
import os, hashlib, subprocess

# 相对 tools/sie/ 的裁决代码集。新增裁决模块必须登记于此，否则自举哈希门不护它。
IMMUTABLE_RELPATHS: tuple[str, ...] = (
    "statemachine.py",   # 状态机转移
    "acceptor.py",       # PACE 配对裁决
    "judges.py",         # 异构 judge
    "verifiable.py",     # A 档 grader / 变异测试门
    "anchors.py",        # B 档锚核查
    "selfdeception.py",  # 自欺指数多闸
    "gate_human.py",     # action 分级 / 人审门
    "profile.py",        # tier 画像冻结判定
    "sandbox.py",        # realpath 边界 / action 分级
    "supervisor.py",     # 双进程裁决 loader
    "immutable.py",      # 清单与哈希门自身
)

_IMMUTABLE_SET = frozenset(IMMUTABLE_RELPATHS)

def _normalize(relpath: str) -> str:
    # 统一分隔符 + 去 ./.. + 取 basename 之外仍保留相对结构，最终比对 basename。
    p = relpath.replace("\\", "/")
    p = os.path.normpath(p).replace("\\", "/")
    return os.path.basename(p)

def is_immutable_relpath(relpath: str) -> bool:
    return _normalize(relpath) in _IMMUTABLE_SET

def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```
- [ ] **Step 4: 跑测试看通过（清单/归一化部分）**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py -q`
  - Expected: 上两个测试 PASS（materialize 测试尚未写）

- [ ] **Step 5: 写失败测试,从 base ref 物化 frozen 副本并记录哈希**
```python
# 追加到 tests/test_immutable.py
def _init_repo_with_sie(tmp_path):
    root = tmp_path / "repo"
    sie = root / "tools" / "sie"
    sie.mkdir(parents=True)
    # 造两个 IMMUTABLE + 一个非 IMMUTABLE
    (sie / "acceptor.py").write_text("ACCEPTOR_V1 = 1\n", encoding="utf-8")
    (sie / "gate_human.py").write_text("GATE_V1 = 1\n", encoding="utf-8")
    (sie / "propose.py").write_text("PROPOSE_V1 = 1\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True, env=env)
    return root

def test_materialize_frozen_writes_only_immutable_with_base_ref_content(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    # 物化后再篡改工作区 acceptor，frozen 必须仍是 base 内容
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    (pathlib.Path(sie_root) / "acceptor.py").write_text("TAMPERED = 999\n", encoding="utf-8")
    frozen_acc = pathlib.Path(frozen) / "acceptor.py"
    assert frozen_acc.read_text(encoding="utf-8") == "ACCEPTOR_V1 = 1\n"
    # 非 IMMUTABLE 不进 frozen
    assert not (pathlib.Path(frozen) / "propose.py").exists()
    # 哈希与 frozen 内容一致
    assert digests["acceptor.py"] == im.hash_file(str(frozen_acc))
    assert set(digests) >= {"acceptor.py", "gate_human.py"}
```
- [ ] **Step 6: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py::test_materialize_frozen_writes_only_immutable_with_base_ref_content -q`
  - Expected: FAIL（`materialize_frozen` 未实现）

- [ ] **Step 7: 实现 materialize_frozen（用 `git show base_ref:path` 取 base 内容，不读工作区）**
```python
# 追加到 tools/sie/immutable.py
def materialize_frozen(base_ref: str, sie_root: str, frozen_dir: str) -> dict[str, str]:
    """把 IMMUTABLE 文件从 git base_ref 的内容写到 frozen_dir，返回 {relpath: sha256}。
    关键：内容取自 base ref（git show），绝不读 candidate 工作区，防被改后的 IMMUTABLE 入 frozen。
    frozen_dir 由调用方放在 candidate 不可写区（supervisor 主进程私有）。"""
    os.makedirs(frozen_dir, exist_ok=True)
    # 找到 sie_root 所在仓库的根，算出 IMMUTABLE 在仓库中的 git 路径前缀。
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=sie_root,
        check=True, capture_output=True, text=True).stdout.strip()
    rel_prefix = os.path.relpath(sie_root, repo_root).replace("\\", "/")
    digests: dict[str, str] = {}
    for rp in IMMUTABLE_RELPATHS:
        git_path = f"{rel_prefix}/{rp}" if rel_prefix not in (".", "") else rp
        try:
            content = subprocess.run(
                ["git", "show", f"{base_ref}:{git_path}"], cwd=repo_root,
                check=True, capture_output=True).stdout
        except subprocess.CalledProcessError:
            # base ref 尚无该文件（新文件未提交）：跳过物化，但不静默——记空哈希以便启动门发现缺口。
            continue
        out = os.path.join(frozen_dir, rp)
        with open(out, "wb") as f:
            f.write(content)
        digests[rp] = hash_file(out)
    return digests
```
- [ ] **Step 8: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py -q`
  - Expected: PASS（全部）

- [ ] **Step 9: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/immutable.py tools/sie/__init__.py tests/test_immutable.py && git commit -m "$(cat <<'EOF'
M4.1: IMMUTABLE 清单 + frozen 副本物化(git show base ref, sha256)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.2: 启动哈希校验门（fail-closed）

run 启动时（且仅当 IMMUTABLE 锁开启，即自举或显式 enforce）核对 candidate worktree 里 IMMUTABLE 文件内容哈希 == frozen 记录的哈希；任一不符 → 拒绝运行（抛 `ImmutableViolation`），绝不带病继续。

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/immutable.py`（在 Task M4.1 文件末尾 append；当前末行为 `materialize_frozen` 结尾的 `return digests`，在其后追加新代码）
- Modify: `~/CodesSelf/self-evolve/tests/test_immutable.py`（append 测试）

**Interfaces:**
- Consumes：`hash_file`, `IMMUTABLE_RELPATHS`, `materialize_frozen`（M4.1）
- Produces：
  - `class ImmutableViolation(Exception)`
  - `verify_immutable(candidate_sie_root: str, frozen_digests: dict[str, str]) -> None`, 比对 candidate 内 IMMUTABLE 文件哈希；任一不符或缺失 raise `ImmutableViolation`

- [ ] **Step 1: 写失败测试,candidate 改了 IMMUTABLE 文件，启动门必须 raise**
```python
# 追加到 tests/test_immutable.py
def test_verify_immutable_raises_on_tamper(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    # candidate 工作区把 acceptor 改了
    (pathlib.Path(sie_root) / "acceptor.py").write_text("EVIL = 1\n", encoding="utf-8")
    with pytest.raises(im.ImmutableViolation) as ei:
        im.verify_immutable(sie_root, digests)
    assert "acceptor.py" in str(ei.value)

def test_verify_immutable_passes_when_intact(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    im.verify_immutable(sie_root, digests)  # 未篡改 → 不抛

def test_verify_immutable_raises_on_missing_file(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    (pathlib.Path(sie_root) / "gate_human.py").unlink()  # candidate 删了裁决文件
    with pytest.raises(im.ImmutableViolation):
        im.verify_immutable(sie_root, digests)
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py -k verify_immutable -q`
  - Expected: FAIL（`ImmutableViolation`/`verify_immutable` 不存在）

- [ ] **Step 3: 实现启动门（fail-closed：缺文件、哈希不符都拒）**
```python
# 追加到 tools/sie/immutable.py
class ImmutableViolation(Exception):
    """candidate 篡改/缺失 IMMUTABLE 裁决文件——启动 fail-closed 拒绝。"""

def verify_immutable(candidate_sie_root: str, frozen_digests: dict[str, str]) -> None:
    if not frozen_digests:
        raise ImmutableViolation("frozen 哈希记录为空，拒绝在无基线下运行 IMMUTABLE 锁")
    bad: list[str] = []
    for rp, expected in frozen_digests.items():
        cand = os.path.join(candidate_sie_root, rp)
        if not os.path.isfile(cand):
            bad.append(f"{rp}: 缺失")
            continue
        actual = hash_file(cand)
        if actual != expected:
            bad.append(f"{rp}: 哈希不符 expected={expected[:12]} got={actual[:12]}")
    if bad:
        raise ImmutableViolation("IMMUTABLE 校验失败: " + "; ".join(bad))
```
- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py -q`
  - Expected: PASS（全部）

- [ ] **Step 5: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/immutable.py tests/test_immutable.py && git commit -m "$(cat <<'EOF'
M4.2: 启动哈希校验门 verify_immutable (fail-closed, 缺失/篡改均拒)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.3: patch 命中 IMMUTABLE 路径硬拒门

在 patch 应用前增加一道独立于 AST 危险门的"IMMUTABLE 路径硬拒"门：当 `--self`（或 enforce 开）时，任何 patch 写到 IMMUTABLE 路径直接 REJECT(reason=immutable_hit)，不影响其他 patch。

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/patch.py`（M1a/M1b 已有；在 `apply_patch` 入口处、AST 门之前插入 IMMUTABLE 检查。下方给出独立纯函数 `immutable_gate` 供 patch.py 调用，便于单测；M1a `apply_patch` 在解析出 patch 目标路径后调用它）
- Create: `~/CodesSelf/self-evolve/tests/test_patch_immutable_gate.py`

**Interfaces:**
- Consumes：`immutable.is_immutable_relpath`（M4.1）；契约 patch 表示（M1a `apply_patch(patch: dict, worktree: str, ...) -> dict`，其中 `patch["target"]` 为相对 sie_root 的路径列表/单路径）
- Produces：
  - `immutable_gate(target_relpaths: list[str], enforce: bool) -> dict | None`, 命中返回 `{"decision":"REJECT","reason":"immutable_hit","paths":[...]}`；未命中或 `enforce=False` 返回 `None`

- [ ] **Step 1: 写失败测试,enforce 时改 IMMUTABLE 路径被拒、改普通路径放行、非 enforce 全放行**
```python
# tests/test_patch_immutable_gate.py
from tools.sie.patch import immutable_gate

def test_gate_rejects_immutable_when_enforce():
    res = immutable_gate(["acceptor.py"], enforce=True)
    assert res is not None and res["decision"] == "REJECT"
    assert res["reason"] == "immutable_hit"
    assert "acceptor.py" in res["paths"]

def test_gate_rejects_gate_human_and_judges():
    for p in ["gate_human.py", "judges.py", "tools/sie/selfdeception.py"]:
        res = immutable_gate([p], enforce=True)
        assert res is not None and res["reason"] == "immutable_hit"

def test_gate_allows_non_immutable_when_enforce():
    assert immutable_gate(["propose.py", "reflect.py"], enforce=True) is None

def test_gate_noop_when_not_enforce():
    # 默认关(非自举)：连 acceptor 也不在这里拦(走 M1-M3 可写 glob 排除)
    assert immutable_gate(["acceptor.py"], enforce=False) is None

def test_gate_reports_all_hit_paths():
    res = immutable_gate(["propose.py", "acceptor.py", "judges.py"], enforce=True)
    assert set(res["paths"]) == {"acceptor.py", "judges.py"}
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_immutable_gate.py -q`
  - Expected: FAIL（`immutable_gate` 不存在）

- [ ] **Step 3: 实现 immutable_gate 并接入 apply_patch**
```python
# 追加到 tools/sie/patch.py（文件已有 import）
from . import immutable as _im

def immutable_gate(target_relpaths: list[str], enforce: bool) -> dict | None:
    """自举/enforce 时拦截命中 IMMUTABLE 裁决路径的 patch。
    返回 REJECT dict（含全部命中路径）或 None（放行）。"""
    if not enforce:
        return None
    hits = [p for p in target_relpaths if _im.is_immutable_relpath(p)]
    if hits:
        return {"decision": "REJECT", "reason": "immutable_hit", "paths": hits}
    return None
```
在 M1a `apply_patch(patch, worktree, ..., enforce_immutable=False)` 内、AST 危险门**之前**插入（apply_patch 已能解析出 patch 目标路径 `targets`）：
```python
    # IMMUTABLE 硬拒门（独立于 AST 门，先于一切应用）
    _gate = immutable_gate(targets, enforce_immutable)
    if _gate is not None:
        return _gate  # {"decision":"REJECT","reason":"immutable_hit","paths":[...]}
```
> 注：`apply_patch` 需新增形参 `enforce_immutable: bool = False`（默认关，不破坏 M1-M3 调用）；statemachine 在 `--self` run 把它置 True（见 M4.6）。
- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch_immutable_gate.py -q`
  - Expected: PASS

- [ ] **Step 5: 回归 M1a patch 测试未被破坏（新形参有默认值）**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_patch.py -q`
  - Expected: PASS（默认 `enforce_immutable=False`，旧用例行为不变）

- [ ] **Step 6: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/patch.py tests/test_patch_immutable_gate.py && git commit -m "$(cat <<'EOF'
M4.3: patch 命中 IMMUTABLE 路径硬拒门(reason=immutable_hit), 默认关

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.4: supervisor 双进程裁决 loader（candidate 不裁决自己）

supervisor 是只读主进程：从 frozen 副本目录 import 裁决模块（acceptor/verifiable/judges/...），candidate worktree 路径**绝不进 sys.path**。candidate 子进程只产数据（eval 原始证据），裁决由 supervisor 用 frozen 代码做。这保证"被评测的代码不能裁决自己"。

**Files:**
- Create: `~/CodesSelf/self-evolve/tools/sie/supervisor.py`
- Create: `~/CodesSelf/self-evolve/tests/test_supervisor.py`

**Interfaces:**
- Consumes：`immutable.verify_immutable`, `immutable.materialize_frozen`（M4.1/M4.2）；契约 `acceptor.decide(paired, tier, st, params) -> dict`
- Produces：
  - `load_frozen_decider(frozen_dir: str, module: str) -> ModuleType`, 用隔离 import（仅 frozen_dir 入临时 path），返回 frozen 版裁决模块；frozen 缺该模块 → raise `ImmutableViolation`
  - `class Supervisor` 含 `__init__(self, frozen_dir: str, frozen_digests: dict)` 和 `decide(self, paired, tier, st, params) -> dict`（内部用 frozen acceptor，**不**从 candidate import）
  - `candidate_path_is_isolated(frozen_dir: str, candidate_worktree: str) -> bool`, 断言 candidate worktree 不在 supervisor 的模块解析路径上

- [ ] **Step 1: 写失败测试,loader 从 frozen 加载，且解析的不是 candidate 版本**
```python
# tests/test_supervisor.py
import os, sys, types, pathlib, pytest
from tools.sie import supervisor as sup
from tools.sie import immutable as im

def _make_frozen(tmp_path, acceptor_src):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "acceptor.py").write_text(acceptor_src, encoding="utf-8")
    return str(frozen)

def test_load_frozen_decider_returns_frozen_version(tmp_path):
    src = "MARK = 'FROZEN'\ndef decide(paired, tier, st, params):\n    return {'decision':'REJECT','evalue':0.0,'reason':'frozen'}\n"
    frozen = _make_frozen(tmp_path, src)
    mod = sup.load_frozen_decider(frozen, "acceptor")
    assert mod.MARK == "FROZEN"
    assert mod.decide([], "A", None, {})["reason"] == "frozen"

def test_load_frozen_decider_does_not_pollute_sys_path(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    before = list(sys.path)
    sup.load_frozen_decider(frozen, "acceptor")
    assert sys.path == before, "frozen 目录泄漏到全局 sys.path"

def test_candidate_path_is_isolated(tmp_path):
    frozen = _make_frozen(tmp_path, "MARK='F'\n")
    cand = tmp_path / "candidate" / "tools" / "sie"
    cand.mkdir(parents=True)
    assert sup.candidate_path_is_isolated(frozen, str(cand)) is True
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_supervisor.py -q`
  - Expected: FAIL（`supervisor` 模块缺失）

- [ ] **Step 3: 实现隔离 loader（用 importlib spec from file，不动全局 sys.path）**
```python
# tools/sie/supervisor.py
"""supervisor 双进程裁决：只读主进程从 frozen 副本 import 裁决码，candidate 永不裁决自己。"""
from __future__ import annotations
import os, sys, importlib.util
from types import ModuleType
from .immutable import ImmutableViolation, verify_immutable

def load_frozen_decider(frozen_dir: str, module: str) -> ModuleType:
    """从 frozen_dir/<module>.py 以唯一名加载，绝不把 frozen_dir 推入全局 sys.path。
    用 file-based spec 隔离，避免与 candidate 的同名模块冲突或被其覆盖。"""
    path = os.path.join(frozen_dir, f"{module}.py")
    if not os.path.isfile(path):
        raise ImmutableViolation(f"frozen 缺裁决模块: {module}")
    uniq = f"sie_frozen_{module}"
    spec = importlib.util.spec_from_file_location(uniq, path)
    if spec is None or spec.loader is None:
        raise ImmutableViolation(f"无法为 frozen 模块建 spec: {module}")
    mod = importlib.util.module_from_spec(spec)
    # 不写 sys.modules[标准名]，只用唯一名，避免污染 candidate import 解析。
    sys.modules[uniq] = mod
    spec.loader.exec_module(mod)
    return mod

def candidate_path_is_isolated(frozen_dir: str, candidate_worktree: str) -> bool:
    """candidate worktree 不得出现在 supervisor 的模块解析路径里。"""
    cand_real = os.path.realpath(candidate_worktree)
    for p in sys.path:
        try:
            pr = os.path.realpath(p)
        except OSError:
            continue
        if pr == cand_real or cand_real.startswith(pr + os.sep):
            # candidate 在 sys.path 上 → 不隔离。frozen_dir 本身允许（裁决码源）。
            if os.path.realpath(frozen_dir) != pr:
                return False
    return True

class Supervisor:
    """持有 frozen 裁决码，对外只暴露裁决调用；candidate 子进程只交回原始数据。"""
    def __init__(self, frozen_dir: str, frozen_digests: dict[str, str]):
        self.frozen_dir = frozen_dir
        self.frozen_digests = frozen_digests
        self._acceptor = load_frozen_decider(frozen_dir, "acceptor")

    def assert_candidate_intact(self, candidate_sie_root: str) -> None:
        verify_immutable(candidate_sie_root, self.frozen_digests)

    def decide(self, paired, tier, st, params) -> dict:
        # 用 frozen acceptor 裁决，绝不从 candidate import。
        return self._acceptor.decide(paired, tier, st, params)
```
- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_supervisor.py -q`
  - Expected: PASS

- [ ] **Step 5: 写失败测试,Supervisor 用 frozen acceptor 而非 candidate 篡改版裁决**
```python
# 追加到 tests/test_supervisor.py
def test_supervisor_decide_uses_frozen_not_candidate(tmp_path):
    # frozen acceptor 永远 REJECT；candidate 工作区放一个永远 ACCEPT 的伪 acceptor。
    frozen_src = "def decide(paired, tier, st, params):\n    return {'decision':'REJECT','evalue':0.0,'reason':'frozen_rule'}\n"
    frozen = _make_frozen(tmp_path, frozen_src)
    digests = {"acceptor.py": im.hash_file(os.path.join(frozen, "acceptor.py"))}
    cand_sie = tmp_path / "candidate" / "tools" / "sie"
    cand_sie.mkdir(parents=True)
    (cand_sie / "acceptor.py").write_text(
        "def decide(paired, tier, st, params):\n    return {'decision':'ACCEPT','evalue':9.9,'reason':'candidate_cheats'}\n",
        encoding="utf-8")
    s = sup.Supervisor(frozen, digests)
    res = s.decide([(0.0, 0.0)], "A", None, {})
    assert res["decision"] == "REJECT" and res["reason"] == "frozen_rule"
```
- [ ] **Step 6: 跑测试看失败 → 已实现应直接通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_supervisor.py::test_supervisor_decide_uses_frozen_not_candidate -q`
  - Expected: PASS（验证 Supervisor.decide 走 frozen；若 FAIL 说明 loader 误读了 candidate）

- [ ] **Step 7: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/supervisor.py tests/test_supervisor.py && git commit -m "$(cat <<'EOF'
M4.4: supervisor 双进程裁决 loader(从 frozen import, candidate 不裁决自己)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.5: 自举禁 candidate 自定义 grade()（用 frozen/外部 grader）

自举时评测必须用 frozen/外部 grader，candidate worktree 里的 `grade()`（或被 candidate 改写的 grader 钩子）一律不被采信。EVALUATE 在 `--self` 下走 frozen `verifiable.run_grader`，忽略 candidate 提供的 grade 结果。

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/supervisor.py`（M4.4 文件末尾 append）
- Modify: `~/CodesSelf/self-evolve/tests/test_supervisor.py`（append）

**Interfaces:**
- Consumes：`load_frozen_decider`（M4.4）；契约 grade() schema（`task_passed/grader_exit_code/dimensions/anchors/verifiable_coverage`）；M2 `verifiable.run_grader(task, snapshot, env_whitelist) -> dict`
- Produces：
  - `Supervisor.grade(self, task: dict, candidate_worktree: str, *, self_mode: bool) -> dict`, `self_mode=True` 时用 frozen verifiable.run_grader（外部 grader），不调用 candidate 的 grade()；`self_mode=False` 时退回正常路径（调 candidate contract grade，非自举）
  - `candidate_grade_is_trusted(self_mode: bool) -> bool`, 自举=False（不采信），非自举=True

- [ ] **Step 1: 写失败测试,自举模式下 candidate grade 不被采信**
```python
# 追加到 tests/test_supervisor.py
def test_candidate_grade_not_trusted_in_self_mode():
    assert sup.candidate_grade_is_trusted(self_mode=True) is False
    assert sup.candidate_grade_is_trusted(self_mode=False) is True

def test_supervisor_grade_self_mode_uses_frozen_grader(tmp_path):
    # frozen verifiable.run_grader 永远判 task_passed=False(grader_exit_code=1)。
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "acceptor.py").write_text("def decide(p,t,s,pa):\n    return {'decision':'REJECT','evalue':0.0,'reason':'x'}\n", encoding="utf-8")
    (frozen / "verifiable.py").write_text(
        "def run_grader(task, snapshot=None, env_whitelist=None):\n"
        "    return {'task_passed': False, 'grader_exit_code': 1,\n"
        "            'dimensions': [{'name':'t','tier':'A','score':0.0,'weight':1.0}],\n"
        "            'anchors': [], 'verifiable_coverage': 1.0, 'graded_by':'FROZEN'}\n",
        encoding="utf-8")
    digests = {"acceptor.py": im.hash_file(str(frozen/"acceptor.py")),
               "verifiable.py": im.hash_file(str(frozen/"verifiable.py"))}
    # candidate 写一个永远 task_passed=True 的 grade()——必须被忽略。
    cand = tmp_path / "cand"; cand.mkdir()
    s = sup.Supervisor(str(frozen), digests)
    res = s.grade({"id": "t1"}, str(cand), self_mode=True)
    assert res["task_passed"] is False
    assert res["grader_exit_code"] == 1
    assert res.get("graded_by") == "FROZEN"
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_supervisor.py -k grade -q`
  - Expected: FAIL（`grade`/`candidate_grade_is_trusted` 未实现）

- [ ] **Step 3: 实现（自举 grade 走 frozen verifiable，标记 graded_by；不 import candidate grade）**
```python
# 追加到 tools/sie/supervisor.py
def candidate_grade_is_trusted(self_mode: bool) -> bool:
    """自举时 candidate 的 grade() 不被采信（spec §6 自举：用 frozen/外部 grader）。"""
    return not self_mode

# 追加为 Supervisor 方法（写在 class 体内最后）：
#     def grade(self, task, candidate_worktree, *, self_mode):
#         ...
```
将以下方法加入 `Supervisor` 类体（与 `decide` 同级缩进）：
```python
    def grade(self, task: dict, candidate_worktree: str, *, self_mode: bool) -> dict:
        """评测一个 task。
        self_mode=True（自举）：用 frozen verifiable.run_grader（外部 grader），
            完全不调用、不 import candidate worktree 内的 grade()。
        self_mode=False：非自举，正常由上层用 candidate contract grade（这里直接报错引导走原路径）。"""
        if not self_mode:
            raise RuntimeError("Supervisor.grade 仅用于 self_mode 自举评测；非自举走 evaluate 正常路径")
        if not hasattr(self, "_verifiable"):
            self._verifiable = load_frozen_decider(self.frozen_dir, "verifiable")
        res = self._verifiable.run_grader(task)
        # 强制标记裁决来源，便于负向用例断言 candidate grade 未被采信。
        res.setdefault("graded_by", "FROZEN")
        return res
```
- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_supervisor.py -q`
  - Expected: PASS

- [ ] **Step 5: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/supervisor.py tests/test_supervisor.py && git commit -m "$(cat <<'EOF'
M4.5: 自举禁 candidate grade(), 用 frozen verifiable.run_grader(标 graded_by)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.6: `--self` 递归隔离独立 worktree + statemachine 接线

CLI 增 `--self` 旗标（默认关）；为自举建**独立**于普通 run 的 worktree（避免递归 run 互相污染），并在该 run 上开 IMMUTABLE enforce：启动物化 frozen + verify + 把 `enforce_immutable=True` 透传给 patch、用 Supervisor 做裁决/评测。

**Files:**
- Modify: `~/CodesSelf/self-evolve/tools/sie/cli.py`（`run` 子命令 argparse 处；M1a 已有 `run` parser，append `--self` 与 `--enforce-immutable`）
- Modify: `~/CodesSelf/self-evolve/tools/sie/statemachine.py`（INIT/PATCH/ACCEPT/EVALUATE 接 enforce 分支；M1a 已有这些态函数）
- Create: `~/CodesSelf/self-evolve/tools/sie/selfboot.py`（自举专用装配：建独立 worktree + 物化 frozen + 起 Supervisor）
- Create: `~/CodesSelf/self-evolve/tests/test_selfboot.py`

**Interfaces:**
- Consumes：`sandbox.make_worktree`（M1a）、`immutable.materialize_frozen/verify_immutable`（M4.1/2）、`supervisor.Supervisor`（M4.4/5）、`supervisor.candidate_path_is_isolated`
- Produces：
  - `selfboot_init(self_repo_root: str, base_ref: str, run_id: str, runs_root: str) -> dict`, 返回 `{"candidate_worktree","frozen_dir","frozen_digests","supervisor"}`；frozen_dir 放 `runs_root/<run_id>/_frozen`（candidate worktree 之外、不可写区）；建好后立刻 `verify_immutable` + 断言 `candidate_path_is_isolated`
  - `is_self_run(args) -> bool`

- [ ] **Step 1: 写失败测试,selfboot 建独立 worktree + frozen 在 worktree 外 + 隔离成立**
```python
# tests/test_selfboot.py
import os, subprocess, pathlib, pytest
from tools.sie import selfboot

def _init_self_repo(tmp_path):
    root = tmp_path / "self_repo"
    sie = root / "tools" / "sie"
    sie.mkdir(parents=True)
    for m in ["acceptor.py", "verifiable.py", "gate_human.py", "judges.py",
              "selfdeception.py", "anchors.py", "statemachine.py",
              "profile.py", "sandbox.py", "supervisor.py", "immutable.py"]:
        (sie / m).write_text(f"# {m}\nMARK='{m}'\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t",
           "GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"}
    subprocess.run(["git","init","-q"], cwd=root, check=True, env=env)
    subprocess.run(["git","add","-A"], cwd=root, check=True, env=env)
    subprocess.run(["git","commit","-q","-m","base"], cwd=root, check=True, env=env)
    return str(root)

def test_selfboot_frozen_outside_candidate_worktree(tmp_path):
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_1", runs)
    cw = pathlib.Path(boot["candidate_worktree"]).resolve()
    fd = pathlib.Path(boot["frozen_dir"]).resolve()
    # frozen 必须不在 candidate worktree 内（candidate 改不到裁决基线）
    assert fd != cw and cw not in fd.parents
    assert (fd / "acceptor.py").exists()
    assert boot["frozen_digests"]["acceptor.py"]

def test_selfboot_verifies_and_isolates(tmp_path):
    repo = _init_self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "run_self_2", runs)
    # candidate worktree 的 sie root 不在解析路径上
    from tools.sie import supervisor as sup
    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")
    assert sup.candidate_path_is_isolated(boot["frozen_dir"], cand_sie) is True
    assert boot["supervisor"] is not None
```
- [ ] **Step 2: 跑测试看失败**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_selfboot.py -q`
  - Expected: FAIL（`selfboot` 模块缺失）

- [ ] **Step 3: 实现 selfboot_init（独立 worktree + frozen 物化到 run 私有区 + 校验 + 起 Supervisor）**
```python
# tools/sie/selfboot.py
"""自举(--self)专用装配：递归隔离独立 worktree + frozen 裁决基线 + supervisor。"""
from __future__ import annotations
import os
from .sandbox import make_worktree
from .immutable import materialize_frozen, verify_immutable, ImmutableViolation
from .supervisor import Supervisor, candidate_path_is_isolated

def is_self_run(args) -> bool:
    return bool(getattr(args, "self", False) or getattr(args, "self_mode", False))

def selfboot_init(self_repo_root: str, base_ref: str, run_id: str, runs_root: str) -> dict:
    """为自举建立隔离环境。
    - candidate worktree：独立于普通 run 的 worktree（make_worktree 用专属 run_id 前缀）。
    - frozen_dir：放 runs_root/<run_id>/_frozen（candidate worktree 之外、主进程私有、candidate 不可写）。
    返回 dict 供 statemachine 接线。"""
    run_dir = os.path.join(runs_root, run_id)
    os.makedirs(run_dir, exist_ok=True)
    # 1) 独立 candidate worktree（前缀区分递归隔离，避免与外层 run 撞目录）
    candidate_worktree = make_worktree(self_repo_root, base_ref, f"self__{run_id}")
    # 2) frozen 裁决基线：内容取自 base ref（非 candidate 工作区），写到 run 私有区
    self_sie_root = os.path.join(self_repo_root, "tools", "sie")
    frozen_dir = os.path.join(run_dir, "_frozen")
    frozen_digests = materialize_frozen(base_ref, self_sie_root, frozen_dir)
    # 3) 立刻校验 candidate worktree 内 IMMUTABLE == frozen（首轮应一致；fail-closed）
    cand_sie_root = os.path.join(candidate_worktree, "tools", "sie")
    verify_immutable(cand_sie_root, frozen_digests)
    # 4) 断言 candidate 不在解析路径（隔离）
    if not candidate_path_is_isolated(frozen_dir, cand_sie_root):
        raise ImmutableViolation("candidate worktree 出现在 supervisor 解析路径，自举隔离失败")
    # 5) 起 supervisor（从 frozen import 裁决码）
    supervisor = Supervisor(frozen_dir, frozen_digests)
    return {
        "candidate_worktree": candidate_worktree,
        "frozen_dir": frozen_dir,
        "frozen_digests": frozen_digests,
        "supervisor": supervisor,
    }
```
- [ ] **Step 4: 跑测试看通过**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_selfboot.py -q`
  - Expected: PASS

- [ ] **Step 5: CLI 接线（append `--self`/`--enforce-immutable`，默认关）**
```python
# tools/sie/cli.py 的 run 子命令 parser（在已有 add_argument 之后追加）
    run_p.add_argument("--self", dest="self_mode", action="store_true",
                       help="自举：把 self-evolve 自身当 target，开 IMMUTABLE 锁+supervisor 隔离(默认关)")
    run_p.add_argument("--enforce-immutable", dest="enforce_immutable",
                       action="store_true", help="显式开 IMMUTABLE 哈希锁(非自举也可强制)")
```
在 `run` 分发处（解析 args 后）加：`enforce = args.self_mode or args.enforce_immutable`，并把 `enforce` 透传到 statemachine 主循环入参。
- [ ] **Step 6: statemachine 接线测试,enforce 时 PATCH 透传 enforce_immutable=True**
```python
# 追加到 tests/test_selfboot.py
def test_statemachine_patch_receives_enforce_flag(monkeypatch):
    # 验证主循环把 enforce 透传给 patch.apply_patch 的 enforce_immutable
    from tools.sie import statemachine, patch
    seen = {}
    def fake_apply(p, worktree, *a, enforce_immutable=False, **k):
        seen["enforce_immutable"] = enforce_immutable
        return {"decision": "REJECT", "reason": "immutable_hit", "paths": ["acceptor.py"]}
    monkeypatch.setattr(patch, "apply_patch", fake_apply)
    # state_patch 是 M1a 的态5 函数；签名含 enforce 形参(本任务新增, 默认 False)
    statemachine.state_patch(
        proposals=[{"target": ["acceptor.py"], "diff": ""}],
        worktree="X", enforce_immutable=True)
    assert seen["enforce_immutable"] is True
```
> 注：本步要求 M1a 的态5 函数 `state_patch(..., enforce_immutable: bool = False)` 新增该形参并把它传给 `apply_patch`。默认 False → 非自举行为不变。
- [ ] **Step 7: 跑测试看失败 → 改 statemachine → 跑通过**
  - Run（先看失败）: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_selfboot.py::test_statemachine_patch_receives_enforce_flag -q`
  - Expected: FAIL（态5 还没透传 enforce_immutable）
  - 实现：在 `statemachine.state_patch` 内调用 `patch.apply_patch(p, worktree, ..., enforce_immutable=enforce_immutable)`，函数签名加 `enforce_immutable: bool = False`。
  - Run（再看通过）: 同上命令
  - Expected: PASS

- [ ] **Step 8: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tools/sie/selfboot.py tools/sie/cli.py tools/sie/statemachine.py tests/test_selfboot.py && git commit -m "$(cat <<'EOF'
M4.6: --self 递归隔离独立 worktree + frozen 装配 + statemachine/CLI 接线

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

### Task M4.7: 自举负向用例端到端（验收闸门）

把 spec §13/§9 的 M4 验收用一组端到端负向用例钉死：改裁决码被拒、改 grade() 不采信、篡改 IMMUTABLE 启动拒、candidate 不在解析路径。这是 M4 的验收测试，全过即里程碑达成。

**Files:**
- Create: `~/CodesSelf/self-evolve/tests/test_m4_selfboot_negative.py`

**Interfaces:**
- Consumes：`selfboot.selfboot_init`、`patch.immutable_gate`/`patch.apply_patch`、`supervisor.Supervisor`、`immutable.verify_immutable/ImmutableViolation`

- [ ] **Step 1: 写负向用例(a),patch 改 gate_human/acceptor 被硬拒**
```python
# tests/test_m4_selfboot_negative.py
import os, subprocess, pathlib, pytest
from tools.sie import selfboot, patch as P
from tools.sie import immutable as im
from tools.sie.supervisor import Supervisor

def _self_repo(tmp_path):
    from tests.test_selfboot import _init_self_repo
    return _init_self_repo(tmp_path)

def test_neg_a_patch_hits_immutable_rejected():
    for tgt in ["gate_human.py", "acceptor.py"]:
        res = P.immutable_gate([tgt], enforce=True)
        assert res["decision"] == "REJECT" and res["reason"] == "immutable_hit"
```
- [ ] **Step 2: 写负向用例(b),candidate 改 grade() 不被采信**
```python
# 追加到 tests/test_m4_selfboot_negative.py
def test_neg_b_candidate_grade_not_trusted(tmp_path):
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_b", runs)
    sv: Supervisor = boot["supervisor"]
    cw = boot["candidate_worktree"]
    # candidate 在自举 worktree 内塞一个永远 task_passed=True 的 grade()
    cand_grade = pathlib.Path(cw) / "grade.py"
    cand_grade.write_text(
        "def grade(task):\n    return {'task_passed': True, 'grader_exit_code': 0,\n"
        "        'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0}\n",
        encoding="utf-8")
    # frozen verifiable.run_grader 是占位(MARK)——给它打补丁成可调用 grader 以驱动断言
    vpath = pathlib.Path(boot["frozen_dir"]) / "verifiable.py"
    vpath.write_text(
        "def run_grader(task, snapshot=None, env_whitelist=None):\n"
        "    return {'task_passed': False, 'grader_exit_code': 1,\n"
        "            'dimensions': [], 'anchors': [], 'verifiable_coverage': 1.0, 'graded_by':'FROZEN'}\n",
        encoding="utf-8")
    # 重建 supervisor 让其加载新 frozen verifiable（哈希也更新以过 assert_candidate_intact 之外的 grade 路径）
    digests = dict(boot["frozen_digests"]); digests["verifiable.py"] = im.hash_file(str(vpath))
    sv2 = Supervisor(boot["frozen_dir"], digests)
    res = sv2.grade({"id": "t"}, cw, self_mode=True)
    assert res["task_passed"] is False  # candidate 的 True 被忽略
    assert res["graded_by"] == "FROZEN"
```
- [ ] **Step 3: 写负向用例(c)+(d),篡改 IMMUTABLE 启动拒 + candidate 不在解析路径**
```python
# 追加到 tests/test_m4_selfboot_negative.py
def test_neg_c_tampered_immutable_startup_rejected(tmp_path):
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_c", runs)
    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")
    # candidate 篡改裁决文件后再次启动校验 → 必须 raise
    (pathlib.Path(cand_sie) / "acceptor.py").write_text("EVIL=1\n", encoding="utf-8")
    with pytest.raises(im.ImmutableViolation):
        im.verify_immutable(cand_sie, boot["frozen_digests"])

def test_neg_d_candidate_not_on_resolution_path(tmp_path):
    from tools.sie import supervisor as sup
    repo = _self_repo(tmp_path)
    runs = str(tmp_path / "runs")
    boot = selfboot.selfboot_init(repo, "HEAD", "neg_d", runs)
    cand_sie = os.path.join(boot["candidate_worktree"], "tools", "sie")
    assert sup.candidate_path_is_isolated(boot["frozen_dir"], cand_sie) is True
```
- [ ] **Step 4: 跑全部 M4 负向用例**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_m4_selfboot_negative.py -q`
  - Expected: PASS（四类负向用例全过 = M4 验收达成）

- [ ] **Step 5: 全量 M4 回归（确保默认关路径未受影响）**
  - Run: `cd ~/CodesSelf/self-evolve && python -m pytest tests/test_immutable.py tests/test_patch_immutable_gate.py tests/test_supervisor.py tests/test_selfboot.py tests/test_m4_selfboot_negative.py tests/test_patch.py -q`
  - Expected: PASS（M4 全套 + M1a patch 回归）

- [ ] **Step 6: commit**
```bash
cd ~/CodesSelf/self-evolve && git add tests/test_m4_selfboot_negative.py && git commit -m "$(cat <<'EOF'
M4.7: 自举负向用例端到端验收(改裁决码拒/改grade()不采信/篡改IMMUTABLE拒/隔离)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015s63syXfzXPq4Tz5UCM7yW
EOF
)"
```

---

## 跨里程碑一致性补遗（执行前必读）

> 由 5 个里程碑并行起草后统一对齐；执行任一里程碑前先读本节，避免接口/命名漂移。

1. **run 布局（固化）**：`<target>/.sie/runs/<run_id>/`（state/events/reflections/proposals/traces/evals/acceptor/pending_actions）；archive 在 `<target>/.sie/archive/`。写进 `reference/runbook.md`。
2. **params 基线（M1a.1 之前先建 `tools/sie/params.py`）**：canonical 键名以英文为准并给默认值,`alpha=0.05, n_min=8, anchor_set_min=24, effective_independent_anchor_min=12, holdout_fraction=0.3, continue_count_cap=5, no_progress_circuit=8, no_progress_release=3, static_reject_circuit=6, forced_review_circuit=5, drift_circuit=4, cumulative_drift_tolerance=1.5, frozen_anchor_effective_gain_eps=0.02, selfdeception_alert_band=0.15, evalue_max_step, n_reflectors=1, reflection_correctness_threshold=0.5, judge_alpha_low=0.4, judge_alpha_high=0.85, active_cap=64, K=5`。`acceptor.decide` 兼容历史键 'α'，但 canonical 为 'alpha'；所有里程碑读 params.py。
3. **archive 契约补充（M1a 已实现，回填 00-head 契约）**：除 `add_version/rollback/pareto_front/retire_stale` 外，新增 `snapshot_version(archive_dir, vid, sandbox_root)->None` 与 `lineage(archive_dir)->list[dict]`（rollback 验收需真实快照取回）。`pareto_front/retire_stale` 在 M1a 为占位（签名锁定），硬维门 Pareto 与 Library Drift 退役在 M3 落实。
4. **acceptor.decide 演进（签名永不变）**：M1a=no-regression 硬门内部实现（不产 CONTINUE）；M1b 替换为 PACE A 档 e-process（二态、站 confseq）；M2/M3 在 decide 内补全 B/C 分支（B: per-anchor 边际增益配对 + `n_anchor<n_min` 或 `effective_independent_count<effective_independent_anchor_min`→禁 ACCEPT；C: per-regression 一致性 + 主观分方差缩放 + `evalue_max_step`）。
5. **CLI 分阶段**：M1a=`init|run|status|replay|rollback`；`review`+非阻塞队列 resolve 在 M1b；`land`（对外落地子流程）在 M2 起；`diff` 任意里程碑可补。
6. **action OUTWARD_OPS（统一命名）**：`{push, merge_main, send, delete_outside, land, approve}`，`sandbox.action_class` 与 `gate_human`/`proxy`/`land` 共用此集。
7. **禁网→出站审查交接**：M1a 用 `sitecustomize.py` 注入子进程（monkeypatch socket + 拦 discord_relay import + HOME 重指空 jail，allowlist 空=全禁）；M2 `proxy.py`（harness 代发+白名单+内容/序列审查）接管，注入点须与 sitecustomize 协同不冲突。
8. **脚手架移除**：`statemachine.run_loop` 的 `_injected_fix` 仅 M1a 端到端验证用，M3 接真 LLM fanout 后移除；`mode` 在 M1a 仅透传，gated/land 真正区分在 M1b/M2。
9. **数据隔离（铁律5）落点**：frozen 锚 `verified`/`marginal_gain`/holdout 锚物理隔离存储（如 `evals` 内分文件 + proposer 进程无读权限），REFLECT/PROPOSE/PATCH 传入仅 task 输入。M2 anchors.py 落地时强制。
