# Acceptor Math Reference: PACE A-Tier e-Process

## 1. Null Hypothesis and Observation Mapping

For **A-tier** (verifiable 0/1 scores), each paired observation `(before, after)` is transformed as:

```
d = after - before  ∈ {-1, 0, +1}
u = 0.5 * (d + 1)  ∈ {0, 0.5, 1}
```

The null hypothesis is H₀: E[u] = 0.5 (no improvement; the change is at best neutral).
Under H₀, `u - 0.5` has zero mean — the betting payoff is a fair game.

| d | interpretation | u | payoff (u - 0.5) |
|---|---|---|---|
| -1 | regression (pass→fail) | 0 | -0.5 |
| 0  | no change | 0.5 | 0 |
| +1 | improvement (fail→pass) | 1 | +0.5 |

## 2. Betting Martingale (e-Process)

The wealth process is defined as:

```
W_0 = 1
W_t = W_{t-1} * (1 + λ_t * (u_t - 0.5))
```

where `λ_t ∈ (-2, 2)` is the betting fraction chosen adaptively before seeing `u_t`.

**Anytime-valid guarantee (Ville's inequality):** For any nonnegative martingale W_t with W_0=1,

```
P(∃ t: W_t ≥ 1/α) ≤ α
```

This means the probability of *ever* exceeding the threshold under H₀ is at most α, regardless of when we stop. This is the anytime-valid property — no multiple-testing penalty.

## 3. Threshold and Decision

```
threshold = 1/α
e-value = sup_t W_t = max(W_1, ..., W_n)   ← 路径最大值 (Ville 不等式)

Decision:
  e-value ≥ 1/α  →  ACCEPT  (reject H₀; evidence of improvement)
  e-value  < 1/α  →  REJECT  (insufficient evidence under H₀)
```

**e-value = sup_t W_t（路径最大值），而非终值 W_n。** 这是有意对 brief 初稿的修正：
brief 曾描述"取末值 W_n"，但正确选择是路径最大值 sup_t W_t。理由如下：

1. **Ville 不等式直接控制 sup_t W_t：** P(∃ t: W_t ≥ 1/α) ≤ α，即路径最大值超阈的概率
   在 H₀ 下 ≤ α。取 e-value = sup_t W_t 等价于"最优停时决策"——只要财富任一时刻
   超阈即可采纳，获得最大统计功效，同时保持相同 type-I 约束。
2. **末值 W_n 更保守：** 若财富中途超阈后回落（ONS 自适应可能发生），末值 < 1/α 而
   路径最大值 ≥ 1/α，用末值会漏判真实增益，损失功效。
3. **anytime-valid 一致性：** 选 sup_t W_t 与 anytime-valid（任何停时有效）精神一致，
   不依赖固定样本量，不受多重检验惩罚。

代码已正确实现 `evalue = max(path)` (= sup_t W_t)，此文档与代码一致。

## 4. No-Regression Hard Gate (Priority Override)

Before the e-process is evaluated, a **hard gate** checks for regressions:

```
regression := (before ≥ 1.0) AND (after < 1.0)  [pass → fail]
```

If ANY task shows a regression, the decision is immediately **REJECT** regardless of the e-process result. This ensures backward compatibility: a change that breaks passing tests is never accepted.

**Order of precedence:**
1. Check no-regression hard gate → if any regression, REJECT
2. Run e-process → ACCEPT if e-value ≥ 1/α, else REJECT

## 5. A-Tier Binary Decision (No CONTINUE)

A-tier uses discrete 0/1 scores, making the test result unambiguous. There is no intermediate evidence state, so **CONTINUE is prohibited** — every A-tier call returns exactly ACCEPT or REJECT.

## 6. Per-Tier Pairing Table

| Tier | Unit of pairing | Score type | Null m | Scaling |
|------|----------------|------------|--------|---------|
| A | per-task `task_passed` ∈ {0, 1} | Binary | 0.5 | None (discrete) |
| B | per-rubric dimension score | Continuous [0,1] | 0.5 | variance-scaled |
| C | aggregate subjective rating | Continuous [0,1] | 0.5 | variance-scaled + cap |

## 7. B/C Tier: Variance Scaling and Cap (placeholder, M2/M3)

For subjective scores (B/C tiers), raw diffs are scaled before betting:

```
d_scaled = clip(d / (σ_hist * evalue_max_step), -1, 1)
```

where `σ_hist` is the historical population standard deviation of diffs, and `evalue_max_step` is a per-round cap parameter (default 4.0). This prevents a single anomalous round from dominating wealth.

A-tier skips this scaling step entirely (binary scores are already bounded).

## 8. confseq → ONS Fallback Strategy

`_wealth_betting(diffs, alpha)` tries confseq first; falls back to ONS-betting:

### confseq path (if available)
```python
from confseq.betting import betting_mart
u = [0.5*(d+1) for d in diffs]
mart = betting_mart(u, m=0.5, alpha=alpha)  # returns wealth array
e_value = max(mart)
```

### ONS-betting fallback (always available, default env)
Adapts the betting fraction λ using Online Newton Step:
```
Initialize: wealth=1, λ=0, A=0 (sum sq grads), b=0 (sum grads)
LAM_MAX = 2 - 1e-6  # 收紧上界，见下文
For each d_t:
    u_t = 0.5*(d_t + 1)
    payoff_t = u_t - 0.5
    lam_safe_t = clip(λ_t, -LAM_MAX, LAM_MAX)
    factor_t = 1 + lam_safe_t * payoff_t   # 恒 > 0，无需 max(1e-10, ...)
    W_t = W_{t-1} * factor_t
    g_t = payoff_t / factor_t              # gradient of log-wealth
    A ← A + g_t²
    b ← b + g_t
    λ_{t+1} = clip(b / (A + 1), -LAM_MAX, LAM_MAX)  # ONS step
e_value = max(W_1, ..., W_n)              # 路径最大值 = e-value
```

The ONS strategy is **anytime-valid**: it is a proper betting strategy (λ_t is previsible, i.e., chosen before observing u_t), so the wealth process W_t remains a nonneg martingale under H₀. The false commit rate satisfies P(e-value ≥ 1/α | H₀) ≤ α by Ville's inequality.

### λ 收紧到 ±(2−δ) 而非截断 factor（I2 修正）

**旧做法的问题：** 原代码对 factor 做 `max(1e-10, 1+λ·payoff)` 截断。当 λ=±2、
payoff=∓0.5 时 factor=0，截断到 1e-10。此时梯度 `g = payoff/factor` 爆炸（±5×10⁷），
ONS 步长失控，wealth 永久趋零（过保守），且破坏鞅恒等式（财富乘子与梯度计算不一致）。

**新做法：收紧 λ-clip 而非截断 factor。**
- `LAM_MAX = 2 − 1e-6 = 1.999999`
- 最坏情况 payoff = ±0.5：factor = 1 ± LAM_MAX·0.5 = 1 ∓ 0.9999995
  - 最小值 = 0.0000005 = 5×10⁻⁷ > 0，恒正
- 正常路径（λ 远离边界）factor 远大于此，梯度有界，鞅恒等式成立
- ONS 梯度 g = payoff/factor 在所有可能输入下有限，财富更新自洽

**保证：** factor 恒 > 0 → wealth 恒 > 0 → 鞅属性保持 → Ville 不等式成立。

## 9. Params Reference

| Key | Default | Meaning |
|-----|---------|---------|
| `α` / `alpha` | 0.05 | Type I error bound; threshold = 1/α = 20 |
| `n_min` | 8 | Minimum anchor count for B-tier |
| `continue_count_cap` | 5 | Max CONTINUE rounds before forcing decision (B/C) |
| `evalue_max_step` | 4.0 | Per-step wealth multiplier cap (B/C scaling) |
| `effective_independent_anchor_min` | 12 | Min independent anchors for B/C |
