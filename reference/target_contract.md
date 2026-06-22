# target_contract: grade(task)

目标侧实现 `grade(task)`，返回 A-grade contract dict。harness 用此 contract 判
ACCEPT/REJECT——LLM 只提议，代码裁决（铁律1）。

## Contract 结构

```json
{
  "task_passed": true,
  "grader_exit_code": 0,
  "dimensions": [
    {"name": "pytest", "tier": "A", "score": 1.0, "weight": 1.0}
  ],
  "anchors": [
    {
      "claim": "",
      "span": "",
      "source_url": "",
      "fetched_at": "",
      "verified": false,
      "marginal_gain": 0.0
    }
  ],
  "verifiable_coverage": 1.0
}
```

## 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_passed` | bool | 总体是否通过（A 档由 `grader_exit_code==0` 映射） |
| `grader_exit_code` | int | pytest 退出码（0=全绿，非0=失败） |
| `dimensions` | list[dict] | 各维度分值（M1a 只有 "pytest" 维度） |
| `anchors` | list[dict] | 锚点列表（B 档使用；A 档为空列表） |
| `verifiable_coverage` | float | 可验证覆盖度（M1a A 档固定 1.0） |

### dimensions 维度结构

| 字段 | 说明 |
|------|------|
| `name` | 维度名（M1a: `"pytest"`） |
| `tier` | 档位（`"A"`） |
| `score` | 分值，A 档 ∈{0.0, 1.0}（grader_exit_code 二态映射） |
| `weight` | 权重（M1a: 1.0） |

### anchors 锚点结构（B 档，M2 实现）

| 字段 | 说明 |
|------|------|
| `claim` | 可验证声明文本 |
| `span` | 证据文本段 |
| `source_url` | 来源 URL |
| `fetched_at` | 抓取时间戳 |
| `verified` | 是否已独立验证 |
| `marginal_gain` | 边际增益估计 |

## M1a acceptor 判定逻辑

`acceptor.decide(paired, tier, st, params)` 接受 `paired = [(before_score, after_score)]`：

- 任一任务从 pass（score ≥ 1.0）退化到 fail（score < 1.0）→ **硬 REJECT**（no-regression 门）。
- 无退化 → **ACCEPT**（M1a 兜底）。

M1b 将把 acceptor 内部换为 PACE A 档 anytime-valid e-process（confseq），
`decide()` 签名不变，contract 结构不变。

## 铁律约束

- **铁律1**：judge 主观分由 `evaluate.py` 在 contract 外注入，非 candidate 提供。
- **铁律5**：自举时 `grade()` 必须使用 frozen/外部版（不得读当前被迭代版本的 grader）。
- **数据隔离**：frozen 锚真值/测试真值对 REFLECT/PROPOSE/PATCH 阶段不可读。

## M1a 实现位置

- `grade_pytest`：`tools/sie/verifiable.py:grade_pytest()`
- `evaluate`：`tools/sie/evaluate.py:evaluate()`
- acceptor：`tools/sie/acceptor.py:decide()`
