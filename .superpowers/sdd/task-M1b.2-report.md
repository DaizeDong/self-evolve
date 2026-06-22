# Task M1b.2 Report: 变异测试有效性门

## inject_mutants 覆盖哪些变异

| 节点类型 | 变异规则 |
|----------|----------|
| `BinOp` (Add) | `+` → `-` |
| `BinOp` (Sub) | `-` → `+` |
| `Compare` (Eq) | `==` → `!=` |
| `Compare` (NotEq) | `!=` → `==` |
| `Compare` (Lt) | `<` → `>=` |
| `Compare` (GtE) | `>=` → `<` |
| `Compare` (LtE) | `<=` → `>` |
| `Compare` (Gt) | `>` → `<=` |
| `Constant` (bool) | `True` → `False`, `False` → `True` |

策略：DFS 遍历，每次只改一个站点（single-point mutation），`_Mutator(target_idx=i)` 遍历 n 次产生 n 个 mutant。mutant_id 为 `mut_0`、`mut_1`… 唯一可读。语法错误返回 `[]`。

## gate 流程与文件还原保证

1. **基线检查**：首先调用 `run_one(worktree)`，若返回 False（或抛出异常），直接返回 `valid=False`（基线不绿无法判断测试质量）。
2. **逐 mutant 循环**：对每个 source_file 读取原内容 → 对每个 mutant：
   - `try`：写入变异源 → 调 `run_one` → 记录 killed/survivor
   - `finally`：**无论成功/异常，都把原内容写回**（open+write，不依赖 shutil.copy）
3. **还原保证**：finally 块直接写回 `original` 字符串，即使 `run_one` 抛出异常也不会污染文件。

## valid 判定

```
kill_ratio = killed / total  (total=0 时 kill_ratio=0.0)
valid = total > 0 and kill_ratio >= min_kill_ratio
```

默认 `min_kill_ratio=1.0`（任一存活即 invalid）。`total=0`（无变异点/文件不可解析）时 valid=False。

## 测试覆盖

### test_mutation_gate.py（14 个）

| 测试 | 验证点 |
|------|--------|
| `test_inject_mutants_produces_variants` | `+` 产生变异 |
| `test_inject_mutants_arithmetic_sub` | `-` 翻转为 `+` |
| `test_inject_mutants_comparison_eq` | `==` 翻转为 `!=` |
| `test_inject_mutants_comparison_lt_gte` | `<` 产生变异 |
| `test_inject_mutants_bool_constant` | `True` 翻转为 `False` |
| `test_inject_mutants_syntax_error_returns_empty` | 语法错误返回 `[]` |
| `test_inject_mutants_unique_ids` | 多站点 ID 唯一 |
| `test_real_test_kills_all_mutants` | 真测试 killed=total, valid=True |
| `test_fake_test_lets_mutant_survive` | 放水测试 survivors 非空, valid=False |
| `test_file_restored_after_gate` | gate 后原文件内容不变（watering 路径）|
| `test_file_restored_even_after_exception` | run_one 抛异常后文件仍还原 |
| `test_gate_baseline_false_marks_invalid` | 基线不绿 → valid=False |
| `test_gate_partial_kill_ratio` | min_kill_ratio=0.0 时部分 kill 仍可 valid |
| `test_gate_returns_expected_keys` | 返回 dict 含所有必需 key |

### test_verifiable.py（8 个，既有）

全部 8 个既有测试通过，grade_pytest / snapshot_hash / minimal_env 签名未改动。

## TDD 证据

- Step 1：写 test_mutation_gate.py → ImportError（inject_mutants 不存在）确认失败
- Step 2：在 verifiable.py 添加实现 → 14/14 通过
- Step 3：test_verifiable.py 8/8 通过（无回归）

## 顾虑

- `and`/`or` 布尔运算符目前未变异（brief 标注"视情"，保守未加）；若需要可扩展 `visit_BoolOp`。
- `shutil` 已在 verifiable.py 顶层 import，但 grade_pytest 的 finally 里有内联 `import shutil`——重复无害，已统一为顶层 import。
- 变异产生的 `ast.unparse` 输出与原始字符串格式可能不同（如空格），但不影响语义正确性；`run_one` 用 importlib 加载而非字符串比较，因此无影响。
