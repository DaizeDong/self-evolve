# Acceptor Math Reference: PACE A-Tier e-Process

## 1. Null Hypothesis and Observation Mapping

For **A-tier** (verifiable 0/1 scores), each paired observation `(before, after)` is transformed as:

```
d = after - before  ∈ {-1, 0, +1}
u = 0.5 * (d + 1)  ∈ {0, 0.5, 1}
```

For the two-sided betting formula below, the conditional null is H₀: E[u_t | F_{t-1}] = 0.5, where F_{t-1} contains prior observations and all information used to choose the next bet. An unconditional average of 0.5 is insufficient. Extending this result to the composite claim "no improvement" requires an additional argument; bounded deterministic task scores alone do not establish the conditional null.

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

This controls repeated looks within that one valid process under its conditional null. It does not cover repeatedly starting fresh tests on new proposals. Current `decide()` calls reconstruct wealth from their supplied pairs; the loop has no run-wide alpha allocation or persistent statistical wealth account. Accordingly, the implementation does not establish run-wide family-wise error at most α.

## 3. Threshold and Decision

```
threshold = 1/α
path_max = max(W_1, ..., W_n)

A-tier statistical decision, subject to all applicable hard gates:
  path_max ≥ 1/α  →  ACCEPT
  path_max  < 1/α  →  REJECT
```

The code retains the field name `evalue` for compatibility, but `_ons_betting_wealth` and `_wealth_betting` return a path maximum. Ville controls its threshold-crossing event when the underlying process is valid. The maximum is not automatically an e-value with expectation at most one, and must not be multiplied or averaged with other such maxima as if it were.

A process may cross the boundary and later fall below it; recording the crossing is valid under the same process assumptions. Resetting wealth for another proposal is a new test, outside this guarantee. B/C preprocessing and anchor clustering also require their own validity arguments; counting distinct clusters does not prove conditional independence.

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

A-tier uses discrete 0/1 scores, making the test result unambiguous. There is no intermediate evidence state, so **CONTINUE is prohibited**, every A-tier call returns exactly ACCEPT or REJECT.

## 6. Per-Tier Pairing Table

| Tier | Unit of pairing | Score type | Null m | Scaling |
|------|----------------|------------|--------|---------|
| A | per-task `task_passed` ∈ {0, 1} | Binary | 0.5 | none (discrete) |
| B | per-anchor marginal gain | Continuous [0,1] | 0.5 | none; de-correlation downweight + clip to [-1,1] + e-value total clamp |
| C | aggregate subjective rating | Continuous [0,1] | 0.5 | variance-scaled + cap, then `c_tier_weight` |

## 7. C Tier: Variance Scaling and Cap

Scaling applies to the **C tier only**. For C (aggregate subjective judge scores), raw diffs are scaled before betting, in `acceptor._scale_subjective`:

```
d_scaled = clip(d / (σ * evalue_max_step), -1, 1)
```

where `σ` is the population standard deviation of the current round's diffs (`statistics.pstdev`, replaced by 1.0 when it comes out 0) and `evalue_max_step` is a cap parameter, default 4.0 **on this path**. This prevents a single anomalous round from dominating wealth. A round with fewer than two diffs is returned unscaled, since there is no dispersion to estimate from one point. The scaled diffs are then multiplied by `c_tier_weight` (default 0.05) before betting, which is why pure C essentially never clears the threshold on its own.

**A and B do not use this scaling:**

- **A** bets on the raw binary diffs; they are already bounded to {-1, 0, +1}.
- **B** bets on per-anchor marginal gain, which is an objective quantity, so it is deliberately left unscaled (the B branch is annotated `不走 _scale_subjective` in the code). B applies instead, in order: optional same-source de-correlation downweighting (`_decorrelate_downweight`), an input clip of each diff to [-1, 1], and finally a clamp of the **resulting e-value** to `evalue_max_step`, whose default on that path is `1e6`, i.e. effectively off unless set lower. Same parameter name as the C path, different default and different meaning; see §9.

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
path_max = max(W_1, ..., W_n)             # returned as the legacy evalue field
```

ONS chooses λ_t from prior observations. Together with bounded payoffs, positive factors and the conditional null in §1, this yields a nonnegative martingale for that process. Ville then controls its boundary-crossing probability. Predictable betting alone does not validate the observation model, a composite no-improvement null, or repeated fresh proposal tests.

### 为什么收紧 λ 到 ±(2−δ)，而不是给 factor 兜底截断

**λ 的 clip 边界收紧到 ±(2−δ)，factor 一律不截断。** 另一条看似等价的路是让 factor
兜底：`max(1e-10, 1+λ·payoff)`。那条路是错的,当 λ=±2、payoff=∓0.5 时 factor=0，被兜到
1e-10，此时梯度 `g = payoff/factor` 爆炸（±5×10⁷），ONS 步长失控，wealth 永久趋零
（过保守），且破坏鞅恒等式（财富乘子与梯度计算不一致）。

**本实现收紧 λ-clip，不截断 factor：**
- `LAM_MAX = 2 − 1e-6 = 1.999999`（代码：`tools/sie/acceptor.py` 的 `_LAM_MAX`）
- 最坏情况 payoff = ±0.5：factor = 1 ± LAM_MAX·0.5 = 1 ∓ 0.9999995
  - 最小值 = 0.0000005 = 5×10⁻⁷ > 0，恒正
- 正常路径（λ 远离边界）factor 远大于此，梯度有界，鞅恒等式成立
- ONS 梯度 g = payoff/factor 在所有可能输入下有限，财富更新自洽

**前提分开检查：** factor 恒 > 0 只能保证 wealth 为正。鞅属性还需要可预测下注和条件零均值；满足这些前提后才能使用 Ville 不等式。

## 9. Params Reference

| Key | Default | Meaning |
|-----|---------|---------|
| `α` / `alpha` | 0.05 | Threshold parameter: 1/α = 20; conditional single-process bound, not a run-wide guarantee |
| `n_min` | 8 | Minimum anchor count for B-tier |
| `continue_count_cap` | 5 | Max CONTINUE rounds before forcing decision (B/C) |
| `evalue_max_step` | 4.0 on the C path, `1e6` on the B path | One key, two call sites. C: the divisor in the variance scaling of §7. B: a clamp on the total e-value returned by one `decide()` call. |
| `c_tier_weight` | 0.05 | Weight applied to scaled C diffs; keeps pure C from clearing the threshold alone |
| `effective_independent_anchor_min` | 12 | Min independent anchors for B/C |
