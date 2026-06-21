# /self-evolve

对 `<target>` 启动一次自迭代 run（沙箱内全自动）。

## 用法

```
/self-evolve <target>
```

`<target>` 为目标仓库/目录的绝对路径（必须有 git 历史）。

## 步骤

1. 调用 `python -m tools.sie.cli init --target <target>` 取 run_id。
2. 调用 `python -m tools.sie.cli run --target <target> --run-id <run_id> --base-ref HEAD`
   启动闭环（PROFILE → REFLECT → PROPOSE → PATCH → EVALUATE → ACCEPT/ARCHIVE）。
3. 采纳的版本进 archive lineage；沙箱内全自动，出沙箱落地须走人审（land，M1b+）。

## 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--base-ref` | `HEAD` | 基线 git ref，worktree 从此分叉 |
| `--max-rounds` | `3` | 最大迭代轮数 |
| `--mode` | `auto` | `auto`=沙箱内全自动；`gated`=每步人审（M1b+完整实现） |

## 输出

运行结束后打印 JSON：

```json
{
  "run_id": "<run_id>",
  "accepted_versions": ["v1", "v2"],
  "final_phase": "REFLECT",
  "run_dir": "<target>/.sie/runs/<run_id>"
}
```

## 铁律提示

- **LLM 只提议，代码裁决**：ACCEPT/REJECT 由 harness 确定性代码执行，非 LLM 自判。
- 沙箱内全自动（`sie` harness 驱动）；落地到真目标须走人审（`land`，M1b+）。
- 被采纳 = 无退化（no-regression 硬门，M1a）。M1b 升级为 PACE e-process。

## 查看进度

```
/self-evolve-status <run_id>
```

## 续跑（恢复中断）

```
/self-evolve-resume <run_id>
```
