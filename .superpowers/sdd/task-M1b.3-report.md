# Task M1b.3 Report: PACE A 档 e-process (acceptor.py)

## 1. Status
DONE. All acceptance gates passed. Commit: `af684f3`.

---

## 2. _wealth_betting: confseq/ONS 双路径

`_wealth_betting(diffs, alpha)` 尝试顺序:

1. **confseq 路径** (Python 3.10+/conda 环境): `from confseq.betting import betting_mart(u, m=0.5, alpha=alpha)` → 取 wealth array 的路径最大值作 e-value。
2. **ONS-betting 回退** (默认 Python 3.13 环境，confseq 不可用): 使用 Online Newton Step 自洽鞅。

### ONS-betting 实现
```
初始化: wealth=1, λ=0, A=0 (梯度平方和), b=0 (梯度和)
For d in diffs:
    u = 0.5*(d + 1)          # ∈ {0, 0.5, 1}
    payoff = u - 0.5          # null 中心化
    factor = max(1e-10, 1 + λ·payoff)
    wealth *= factor
    g = payoff / factor        # 对数财富梯度
    A += g²; b += g
    λ ← clip(b / (A+1), -2, 2)   # ONS 步长，初始正则项1
e-value = max(wealth_path)    # 路径最大值 = 最优停时
```

**e-value 取路径最大值而非末值**: Ville 不等式: P(∃t: W_t ≥ 1/α | H₀) ≤ α。路径最大值等价于"最优停时"，提升检验功效而不增加 I 类错误。末值在有限样本下功效明显不足（n=40 真增益时末值≈77 vs 路径最大≈3149）。

---

## 3. A 档数学落地

| 要素 | 实现 |
|------|------|
| 配对单元 | per-task `task_passed ∈ {0,1}` |
| 差值映射 | `d = after-before ∈ {-1,0,+1}` → `u = 0.5*(d+1) ∈ {0,0.5,1}` |
| Null | `m=0.5` (零差/不更好) |
| Wealth | `W_t = ∏(1+λ_t(u_t-0.5))`, ONS 自适应 λ |
| e-value | `max(W_1,...,W_n)` (路径最大值) |
| 阈值 | `1/α` (α=0.05 → 20) |
| 决策 | e-value ≥ 1/α → ACCEPT; 否则 REJECT (A档二态禁CONTINUE) |

---

## 4. no-regression 硬覆盖

优先级: no-regression 先于 e-process。

```python
regressed = [i for i, (b, a) in enumerate(paired) if b >= _PASS > a]
if regressed:
    return {"decision": "REJECT", ...}
# 无回退才跑 e-process
```

硬REJECT覆盖任何e-value结果。

---

## 5. 二态决策

A 档 `decide()` 只返回 ACCEPT/REJECT，**禁 CONTINUE**。B/C 档保留 CONTINUE 逻辑（本里程碑占位）。

---

## 6. 噪声误采纳率实测值

| 实验 | 配置 | 结果 |
|------|------|------|
| 纯噪声误采纳率 | 400 trials, n=40 Bernoulli(0.5), α=0.05 | **0.0000** (目标 ≤ 0.05) ✓ |
| 纯噪声拒绝率 | 200 trials, n=40 Bernoulli(0.5) | **1.0000** (目标 ≥ 0.95) ✓ |
| 真增益采纳率 | 100 trials, n=40, before_p=0.3, after_p=0.9 | **1.00** (目标 ≥ 0.90) ✓ |
| 对抗序列 | pairs=(0.6, 0.605)×40, 微涨 | **REJECT** (evalue≈1.005 << 20) ✓ |

---

## 7. evaluate.py: per-task 配对升级

发现 M1a evaluate.py 只产 1 对汇总分数，对 e-process 无统计功效。同步升级为 per-task 配对:
- `_grade_pytest_per_task()`: 运行 `pytest -v --tb=no --no-header`，解析每行 PASSED/FAILED/XFAIL/XPASS。
- XFAIL→score=0.0（预期失败，尚未达标），XPASS→score=1.0（意外通过，修复生效）。
- task_passed 使用 subprocess exit_code（与 profiler 一致）。

---

## 8. 更新了哪些 M1a 用例及原因

### test_acceptor.py (2 个用例名称更新 + 语义翻转)

| 旧用例名 | 新用例名 | 原因 |
|----------|----------|------|
| `test_no_regression_all_improve_accept` | `test_no_regression_small_sample_rejects` | n=3 无法使 wealth≥20，e-process 正确 REJECT（M1a ACCEPT 是兜底逻辑被 supersede） |
| `test_no_change_no_regression_accept` | `test_no_change_no_evidence_rejects` | 纯持平 d=0 → payoff=0 → wealth=1.0 < 20，无统计证据 REJECT（反自欺命门：不能靠"没变差"过关） |

保留的语义:
- `test_any_regression_hard_reject`: 有退化→REJECT（仍成立）
- `test_A_tier_never_continue`: A档二态（仍成立）
- `test_empty_paired_reject`: 无证据REJECT（仍成立）

### test_e2e.py (1 个用例场景重设计)

`test_e2e_accept_and_rollback`: 改用 xfail+xpass 场景：
- 基线 mod.py: add()正确+mul()有 bug；测试文件: 3 add测试(pass) + 15 mul测试(@xfail)。
- profiler 见 exit_code=0(xfail不算fail) → tier A。
- 注入 fix 后: 15 xfail变xpass → 18对(before,after) → 15对(0→1) → wealth=6207 >> 20 → ACCEPT。

---

## 9. TDD 证据

```
Step 1: tests/test_acceptor_noise.py 写入后 → 3/7 FAIL（old M1a acceptor）
Step 2: acceptor.py 实现 → 7/7 PASS
Step 3: test_acceptor.py 更新后 → 5/5 PASS
Step 4: evaluate.py per-task 升级 → test_evaluate.py 2/2 PASS
Step 5: test_e2e.py 场景重设计 → 4/4 PASS
Step 6: 全套 → 136 passed, 1 skipped (confseq intentional skip)
```

---

## 10. 顾虑

1. **ONS λ 初始为 0**: 前几步押注为 0 (factor=1, wealth 不变)，直到梯度积累足够。对于大真实增益场景(n≥10)不影响；但对 n<10 的小样本场景，功效可能有限（这是 anytime-valid 的固有代价）。
2. **evaluate.py per-task 解析脆弱**: 依赖 `pytest -v` 输出格式；不同 pytest 插件/版本可能影响格式。当前已处理 PASSED/FAILED/ERROR/XFAIL/XPASS。
3. **A档 e-value 取路径最大值**: 比 brief "e-value=末值" 理解更激进（实际 brief 写"或路径最大值，按 brief"所以有歧义）。路径最大值是 anytime-valid 理论正确做法，但使 confseq 路径需调整（confseq betting_mart 返回逐步数组，也取 max）。
4. **B/C 档 evaluate.py per-task 兼容**: B/C 档的 _scale_subjective 仍用 diffs 列表，与新 per-task 配对兼容（diffs 从 paired 提取）。

---

## 11. 文件路径

- `~/CodesSelf/self-evolve/tools/sie/acceptor.py`
- `~/CodesSelf/self-evolve/tools/sie/evaluate.py`
- `~/CodesSelf/self-evolve/reference/acceptor_math.md`
- `~/CodesSelf/self-evolve/tests/test_acceptor_noise.py`
- `~/CodesSelf/self-evolve/tests/test_acceptor.py`
- `~/CodesSelf/self-evolve/tests/test_e2e.py`

---

## 12. Re-review 修正（I1/I2/I3）

### I1: e-process 单独 type-I 验证（新增 test_eprocess_standalone_type1）

**问题:** 原测试 `_pure_noise_pairs` 允许 before=1,after=0 的回退对，40 对里必有回退，
硬门直接 REJECT，e-process 根本没跑。0.0000 误采纳是硬门功劳，不是 e-process type-I 证明。

**关键认识:** 二元 A 档的 null（无回退+无增益）在 binary 下只能 d≡0，e-process W≡1，
由"硬门+e-process"组合正确处理。e-process 自身 type-I 须用连续值 null 隔离验证。

**修复:** 新增 `test_eprocess_standalone_type1`：
- 绕过 `decide()` 硬门，直接调 `_wealth_betting`
- diffs 从连续 null 抽样：u~Uniform(0,1)，E[u]=0.5，有方差的连续值
- 统计 `path_max ≥ 1/α` 的比例（400 trials，n_seq=40）
- **实测误采纳率: 0.0075**（目标 ≤ α=0.05）✓
- 原有 binary 系统级测试保留，注释说明验证的是"硬门+e-process 组合"

### I2: ONS 截断破坏鞅 → 收紧 λ-clip

**问题:** `factor = max(1e-10, 1+lam*payoff)` 在 λ=±2、payoff=∓0.5 时 factor=0 被截断，
梯度 g=payoff/factor 爆炸，wealth 永久趋零，且破坏鞅恒等式。

**修复（acceptor.py）:**
- 引入 `_LAM_MAX = 2.0 - 1e-6`，每步先 clip λ 到 `[-LAM_MAX, LAM_MAX]`
- `factor = 1.0 + lam_safe * payoff`（无截断，恒 > 0 由 λ-clip 保证）
- 最坏情况 factor = 5×10⁻⁷ > 0，梯度有界，鞅恒等式成立
- 去掉 `max(1e-10, ...)` 对 factor 的截断（正常路径不再触发任何 floor）

**验证:** 真增益采纳率 **1.00**（100 trials，前后 ≥ 0.90 目标）✓，全套 137 passed, 2 skipped ✓

### I3: 更新 math 文档 path-max = e-value（对 brief 有意修正）

**修复（acceptor_math.md）:**
- Section 3 明确写 "e-value = sup_t W_t（路径最大值，Ville 不等式）"，并标注为对 brief "末值" 的有意修正
- 解释为何 sup_t W_t 比末值 W_n 更优（功效更高，与 anytime-valid 精神一致）
- Section 8 ONS fallback 伪码更新为新 λ-clip 逻辑（`_LAM_MAX = 2-1e-6`），添加 I2 修正说明

**代码无需改动**（代码已正确实现 `evalue = max(path)`）。

### 测试小结

| 测试 | 结果 | 说明 |
|------|------|------|
| test_eprocess_standalone_type1 | **0.0075 ≤ 0.05** ✓ | e-process 单独 type-I（连续null隔离硬门）|
| test_false_commit_rate_under_alpha | 0.0000 ✓ | 硬门+e-process 组合（二元系统级）|
| test_true_gain_accept_rate_high | 1.00 ✓ | λ-clip 修复后功效不受损 |
| 全套 `pytest -q` | 137 passed, 2 skipped ✓ | 无回归 |
