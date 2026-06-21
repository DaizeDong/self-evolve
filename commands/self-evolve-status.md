# /self-evolve-status

查看某 run 的当前态、archive Pareto 前沿、三计数器、待审队列。

## 用法

```
/self-evolve-status <run_id>
```

`<run_id>` 为 `sie init` 返回的 run 标识符（12 位 hex）。需同时提供 `--target`。

## 底层命令

```
python -m tools.sie.cli status --target <target> --run-id <run_id>
```

## 输出格式（JSON）

```json
{
  "phase": "REFLECT",
  "round": 2,
  "tier": "A",
  "no_progress": 0,
  "static_reject": 1,
  "forced_review": 0,
  "pareto": [
    {"vid": "v1", "scores": [{"name": "pytest", "score": 1.0}], "parent": "base"}
  ],
  "pending": []
}
```

| 字段 | 说明 |
|------|------|
| `phase` | 当前所在态（INIT/PROFILE/REFLECT/PROPOSE/PATCH/EVALUATE/ACCEPT/ARCHIVE） |
| `round` | 当前轮次 |
| `tier` | 目标档位（A=有效 pytest；C=无法验证） |
| `no_progress` | 连续无改进轮次计数（M1b 加熔断阈） |
| `static_reject` | 静态拒绝累计（无有效反思/提案/patch） |
| `forced_review` | 强制人审累计（M1b 完整实现） |
| `pareto` | archive Pareto 前沿（已采纳版本及分值） |
| `pending` | 待人审动作队列（出沙箱动作，M1b+） |

## 说明

- 此命令只读，不修改任何状态（`sie status` 只查询 state.json + archive + gate_human）。
- 若 run 目录不存在会报错，先用 `/self-evolve <target>` 开跑。
