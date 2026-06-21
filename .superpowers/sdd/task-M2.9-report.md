# Task M2.9 Report: proxy.py — 跨请求序列异常检测

## 实现概述

### record_outbound
- 签名：`record_outbound(run_dir: str, kind: str, params: dict) -> None`
- 实现：`os.makedirs` 保证目录存在，以 append 模式写 `run_dir/outbound_seq.jsonl`，每行一条 `{"kind": ..., "params": ...}` JSON（sort_keys=True 保证可重放）。

### sequence_anomaly
- 签名：`sequence_anomaly(run_dir: str, params_seq_window: int = 32) -> dict`
- 返回：`{"anomalous": bool, "score": float, "reasons": [str, ...]}`
- 损坏行（json.JSONDecodeError）静默跳过，不崩溃。
- 任一信号触发 → `anomalous=True`，`score` 累加。

## 三征实现状态

### ① 枚举熵异常 / 单调字典序（做实）
- 函数 `_longest_monotone_run(values)` 计算窗口内单参数最长严格递增字典序连续段。
- 阈值 `_MONOTONE_RUN_MIN = 6`：窗口内任意参数名的连续单调序长度 ≥ 6 即触发。
- 触发 reason 含 `"monotone"` 和 `"sequence"` 关键词，满足测试断言。
- 仅看最近 `params_seq_window`（默认 32）条记录。

### ② 与答案锚的相关性（**降级为接口占位**）
- `sequence_anomaly` 无法访问 holdout 答案/标签数据（答案数据在独立评测数据路径，不在 `run_dir`，也未注入函数签名）。
- 本任务**不实现**该征的实质检测；docstring 明示接口设计：调用方若持有答案数据，可在 `reasons` 列表外部注入该征的判定，再合并 `anomalous`。
- 此为已知边界，spec §6 残余风险接受范围内。

### ③ 单 run 出站频次突刺（做实）
- 阈值 `_FREQ_SPIKE_MAX = 100`：同 kind 请求总次数超过 100 即触发。
- 触发 reason 含 `"frequency"` 和 `"spike"` 关键词，满足测试断言。
- 统计全部记录（非仅窗口），反映 run 级别全局频次。

## dispatch 接线
- 在 `dispatch` 成功 return 前（`f(...)` 调用之后）追加一行：
  ```python
  record_outbound(run_dir, kind, params)
  ```
- M2.8 原有 `screen_request`/`dispatch` 契约保持不变，仅在成功路径末尾新增该调用。

## 残余风险说明
- **低带宽时序信道**：candidate 可通过请求时间间隔（非内容）编码信息；本实现不检测时序（未存时间戳到 jsonl），spec §6 已接受此残余风险。
- **征②**（答案锚相关）无法在无答案数据的上下文中封闭；同上为 §6 接受范围。
- **单调阈值**可被绕过：攻击者隔几条插随机请求可使窗口不触发；启发式性质，非加密强度。

## 测试结果

### test_proxy_sequence.py（新增，6 项）
| 测试 | 结果 |
|---|---|
| test_monotone_param_sequence_flagged | PASSED |
| test_normal_diverse_sequence_ok | PASSED |
| test_frequency_spike_flagged | PASSED |
| test_empty_run_dir_not_anomalous | PASSED |
| test_insufficient_window_not_anomalous | PASSED |
| test_record_outbound_creates_jsonl | PASSED |

### test_proxy_outbound.py（M2.8 回归，18 项）
全部 PASSED — dispatch 接线未破坏已有契约。

### 合计
24 passed, 0 failed, 0 errors

## TDD 证据
1. 先写 `tests/test_proxy_sequence.py` → 运行 → 6 FAILED（AttributeError: no attribute 'record_outbound'）。
2. 追加实现到 `tools/sie/proxy.py` → 运行 → 6 PASSED。
3. 合并 `test_proxy_outbound.py` 回归 → 24 PASSED。

## 顾虑
- 征① 阈值 `_MONOTONE_RUN_MIN=6` 是经验值，短于 6 的单调段（如 3~5 个连续 ticker）不触发，可被低速信道规避。
- 频次阈值 `_FREQ_SPIKE_MAX=100` 同样为硬编码常量；生产环境应可配置。
- 征② 的检测能力缺口是本实现最大的残余风险，已在 docstring 和本报告中明示。
