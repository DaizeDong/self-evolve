# /self-evolve-resume

从已存在的 run 续跑（不重跑 PROFILE，tier 已冻结=铁律4）。

## 用法

```
/self-evolve-resume <run_id>
```

`<run_id>` 为之前 `sie init` 返回的 run 标识符。需同时提供 `--target`。

## 底层命令

```
python -m tools.sie.cli run --target <target> --run-id <run_id> --base-ref HEAD
```

## 适用场景

- 进程意外中断（崩溃/超时）后恢复——harness 从 events.jsonl 重建 RunState，
  不重跑 PROFILE（tier 已冻结）。
- 主动暂停后手动续跑。

## 崩溃一致性保证

`sie` 的 crash-replay 不变量：每次状态转换先 `append_event`（events.jsonl），
再 `save_state`（state.json）。崩溃时 state.json 可能落后，但删除后执行：

```
python -m tools.sie.cli replay --target <target> --run-id <run_id>
```

可从 events.jsonl 重建出与崩溃前一致的 RunState。续跑直接调用 `sie run` 即可，
harness 内部会检测 target.json 是否存在，若存在则跳过 PROFILE（铁律4）。

## 铁律提示

- **tier 不重算**：续跑使用已冻结的 target.json（铁律4），保证 A/C 档判定一致。
- **沙箱内全自动**：续跑仍在沙箱（`sie` harness 驱动），落地须走人审（M1b+）。
- **LLM 只提议，代码裁决**：ACCEPT/REJECT 仍由 harness 代码执行。

## 查看 run 状态

```
/self-evolve-status <run_id>
```
