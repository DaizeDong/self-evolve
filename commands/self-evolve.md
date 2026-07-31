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
3. 采纳的版本进 archive lineage；沙箱内全自动，出沙箱的动作（`land` / `push` / `merge_main`
   / `send` 等）一律判为 gated，进人审队列，harness 自己不落地。

## 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `--base-ref` | `HEAD` | 基线 git ref，worktree 从此分叉 |
| `--max-rounds` | `3` | 最大迭代轮数 |
| `--mode` | `auto` | 只在**纯 C 档接受门**这一处被读到：`auto` 时，一轮纯 C（`coverage=0`）本可 ACCEPT 的结果被强制改判 PAUSE_FOR_HUMAN 进人审队列；`gated` 关掉这条兜底。**尚未实现「每步人审」**，见 ROADMAP。 |

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
- 沙箱内全自动（`sie` harness 驱动）；落地到真目标须走人审（`land` 属 `OUTWARD_OPS`，恒 gated）。
- 被采纳 = PACE e-process 判定证据足够（`evalue ≥ 1/α`），且 A 档另有 no-regression 硬门：
  任一 pass→fail 直接 REJECT，覆盖 e-process 结果。

## 查看进度

```
/self-evolve-status <run_id>
```

## 续跑（恢复中断）

```
/self-evolve-resume <run_id>
```
