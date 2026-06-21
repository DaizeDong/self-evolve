# Task M2.13 Report: statemachine B 档接线 + M2 端到端验收

## B 接线点

`tools/sie/statemachine.py` 新增公开函数 `resolve_accept(st, eval_out, params) -> dict`（位于 M1b.6 契约函数块之后、`_run_dir` 辅助函数之前）。

B 档判定流程：
1. `acceptor.decide(b_paired, "B", st, {anchors: anchors_visible_verified})`
2. `selfdeception.index(judge_gain, visible_anchor_gain, holdout_gain, st, params)`
3. `judge_anchor_divergence` alert → `st.drift_count += 1`（in-memory）

## 态9.5 触发条件

强制人审条件（`force = True`）在 acceptor 返回 **ACCEPT 或 CONTINUE**（`not_rejected`）时均触发：

- `eval_out["coverage_floor_violation"] == True`（覆盖率 < floor）
- `sd["force_human"] == True`（selfdeception: visible 涨 holdout 平 → overfit_holdout）
- `"low_anchor_gain" in sd["alerts"]`（visible 锚增益过低）

触发后：`st.forced_review += 1`、`gate_human.enqueue()`、返回 `next_state="9.5"`、`acceptor_decision="FORCED_REVIEW"`。

REJECT 路径不额外拦截（REJECT 已阻断进展）。

## drift_count event-delta 持久化

- `selfdeception.index` 在 `|judge_gain - visible_anchor_gain| > band` 时返回 `"judge_anchor_divergence"` alert（不直接修改 st）
- `resolve_accept` 检测到该 alert 后执行 `st.drift_count += 1`（in-memory 层）
- **replay 持久化**：调用方（run_loop）在 `_step` 中写入事件 `{"type": "DRIFT_SIGNAL", "drift_count_delta": 1}`，`events._apply` 通过 `drift_count_delta` 机制在 replay 时重建递增的 drift_count
- 测试 `test_drift_count_persists_via_event_delta` 直接写4个 delta=1 事件，replay 重建 drift_count=4，再经 `circuit_check` 验证 drift_circuit 触发（阈=4）
- 测试 `test_drift_count_replay_survives_restart` 删除 state.json 后 replay 仍重建 drift_count=3（crash-replay 不变式）

## 5 条验收各如何端到端验

| # | 验收语句 | 测试函数 | 端到端组件链 |
|---|---------|---------|------------|
| ① | small-cap 形态产物跑 B 出三态 | `test_smallcap_runs_btier_and_emits_decision`、`test_smallcap_b_accept_path`、`test_smallcap_b_reject_path` | `extract_anchors(FIX)` → `acceptor.decide` → ACCEPT/REJECT/CONTINUE |
| ② | coverage<floor 欲 ACCEPT→人审 | `test_coverage_floor_blocks_auto_accept` | `resolve_accept(coverage_floor_violation=True)` → `not_rejected && force` → 态9.5、forced_review++ |
| ③ | visible↑ holdout=0 → force_human → 人审 | `test_long_slow_overfit_visible_up_holdout_flat_forces_human`、`test_selfdeception_holdout_blocks_auto_accept_via_resolve` | `selfdeception.index(visible_gain=0.04, holdout=0)` → `overfit_holdout` + `force_human=True` → `resolve_accept` → 态9.5 |
| ④ | 8同源锚→有效独立<12→REJECT | `test_small_correlated_anchor_set_rejected`、`test_effective_independent_count_8_same_source` | `anchors.effective_independent_count`（floor(1+log2(8))=4）→ `acceptor.decide` 门2 → REJECT |
| ⑤ | 长期微涨→拒/人审 | `test_long_slow_overfit_reject_or_human`、`test_resolve_accept_long_slow_overfit_routes_9_5` | `selfdeception.index(visible=0.03, holdout=0)` → `overfit_holdout` + `force_human=True` → `resolve_accept` → 态9.5 |

## fixture 规模

`tests/fixtures/smallcap_artifact.json`：
- 24 个 section，每 section 一个锚，共 24 个锚
- 每个锚 source_url host 互异（sec.gov / macrotrends.net / yahoo / stockanalysis / … 24 不同域）
- 每个锚 cik 互异（1000001–1000024）
- `extract_anchors` 得 24；`effective_independent_count` 得 24（>=12 门槛）

## 是否破坏既有

全量回归：310 passed, 2 skipped（原 294+2；16 新增测试全绿）。A/C 档行为由 `_resolve_accept_legacy` 兜底不变；M1a/M1b/M2 既有测试全部通过。

## 不打网

- fixture 内锚预设 `verified=False`（提取后）；测试用 `{**x, "verified": True}` 构造已核验锚集，绕过 edgar/edgar_cache
- `_verify_visible` 在 resolve_accept 路径中不被调用（eval_out 直接提供 `anchors_visible_verified`）
- `selfdeception.index` 和 `acceptor.decide` 均为纯 Python 计算，不打网

## TDD 证据

1. 写 fixture → 写测试 → 跑失败（7 FAILED: AttributeError: no attribute 'resolve_accept'）
2. 实现 `resolve_accept` 初版 → 3 FAILED（force 只检查 `want_accept`，但 evalue_max_step 限制导致 CONTINUE 路径漏检）
3. 改为 `not_rejected` 逻辑（ACCEPT|CONTINUE 均检查 force 条件）→ 16/16 PASSED
4. 全量回归 310+2 PASSED

## 顾虑

- `evalue_max_step` 参数含义双重：既作为每轮 e-value 上限，也影响 ACCEPT/CONTINUE 分支决策。测试 `test_resolve_accept_b_accept_routes_to_state_8` 使用 `evalue_max_step=1e6` 方能使 e-value 超过 1/alpha=20 触发 ACCEPT。生产环境若 evalue_max_step=5.0，B 档几乎不会走 ACCEPT 路径（总返回 CONTINUE）；M3 可考虑澄清参数语义。
- `resolve_accept` 中 `judge_gain` 默认为 0.0（eval_out 未提供时）。在真实 run_loop 中，judge_gain 需从 evaluate/reflect 结果中计算并注入 eval_out，M3 接线时需补齐。
- `force` 对 CONTINUE 路径也触发（非严格 "欲 ACCEPT"），这是有意为之：coverage 低/holdout 背离时允许 CONTINUE 迭代是危险的；如 M3 有不同规格可在 brief 中明确。

---

## M2.13 Critical 集成修复 (本次追加)

### Critical 1 — resolve_accept 接入 run_loop (B 档生产路径)

**接线点** (`statemachine.py` ~line 458): `ev_result = evaluate(...)` 之后，按 `"B" in str(prof["tier"])` 分支：

- **B 档**: 调用 `resolve_accept(st, ev_result, params, run_dir=run_dir)`，根据返回的 `next_state` ("8"/"9.5"/"6"/"9") 路由到 ARCHIVE/PAUSE_FOR_HUMAN/CONTINUE/REJECT 四个路径，每条路径均经 `_step` 写事件落地。
- **A 档**: 保留原 `decide + apply_acceptor_outcome` 路径不变，完全兼容 M1。

B 档四走向均经事件流 (`_step` → `append_event` → `replay` → `save_state`) 落地，计数 (no_progress/forced_review) 经 `_delta` 持久。

### Critical 2 — drift_count 经真实事件持久化

- `resolve_accept` 在内存层执行 `st.drift_count += 1`（局部立即效果）。
- **run_loop** 在 B 档分支中，检查 `ra["selfdeception"]["alerts"]` 含 `"judge_anchor_divergence"` 时，立即调用 `_step(run_dir, {"type":"DRIFT_SIGNAL","drift_count_delta":1,...})`，写入 events.jsonl。
- `events._apply` 处理 `drift_count_delta` 字段，replay 可完全重建 drift_count 递增 → drift_circuit(阈4) 触发。
- **测试验证真实路径**：`test_resolve_accept_drift_signal_written_to_events` 已改为先断言 `"judge_anchor_divergence" in alerts`（非条件式），再断言 `st.drift_count >= 1`，无静默通过风险。

### Critical 3 — gate_human.enqueue 传参修正

- `resolve_accept` 签名新增 `run_dir: str | None = None`。
- enqueue 调用改为传 `_enqueue_dir = run_dir or os.path.join(tempfile.gettempdir(), "sie_gate_human_fallback")`，对齐 run_loop 第496行已有正确用法。
- 测试不传 run_dir 时走 tempdir 兜底，不影响 forced_review 计数逻辑。

### holdout_gain=None 处理 (Important)

- `selfdeception.index` 签名改为 `holdout_gain: float | None`。
- 闸③条件改为 `if holdout_gain is not None and visible_anchor_gain > 0.0 and holdout_gain <= 0.0`，None 时跳过不报 overfit_holdout/force_human。
- `resolve_accept` 调用直接传 `holdout_gain=holdout_gain`（去掉 `if holdout_gain is not None else 0.0` 错误映射）。
- 新测试：`test_holdout_none_no_overfit_alert`（selfdeception 层），`test_resolve_accept_holdout_none_no_overfit`（resolve 层），`test_holdout_none_skips_overfit_gate`、`test_holdout_none_preserves_other_gates`（selfdeception_holdout 套件）。

### 三态断言加强

- `test_smallcap_runs_btier_and_emits_decision`: `len(decisions) >= 1` → `>= 2`，注释说明 ACCEPT 由独立 1e6-cap 用例覆盖。
- `test_resolve_accept_drift_signal_written_to_events`: 条件式 `if "judge_anchor_divergence" in alerts` → 无条件先断言 alert 存在再断言 drift_count。

### 测试结果

- 目标套件: `tests/test_m2_acceptance.py tests/test_statemachine_counters.py tests/test_selfdeception_holdout.py` → **46 passed**
- 全量: **314 passed, 2 skipped, 0 failed** (无回归)
