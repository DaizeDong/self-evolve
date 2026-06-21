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
e-value = max(W_1, ..., W_n)  (running maximum, for early stopping)

Decision:
  e-value ≥ 1/α  →  ACCEPT  (reject H₀; evidence of improvement)
  e-value  < 1/α  →  REJECT  (insufficient evidence under H₀)
```

The running maximum is used because it corresponds to the optimal stopping rule: stop as soon as wealth first exceeds 1/α. This yields more power than using the terminal value W_n while maintaining the same Type I error bound α.

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
For each d_t:
    u_t = 0.5*(d_t + 1)
    payoff_t = u_t - 0.5
    factor_t = max(1e-10, 1 + λ_t * payoff_t)
    W_t = W_{t-1} * factor_t
    g_t = payoff_t / factor_t          # gradient of log-wealth
    A ← A + g_t²
    b ← b + g_t
    λ_{t+1} = clip(b / (A + 1), -2, 2)  # ONS step
e_value = max(W_1, ..., W_n)
```

The ONS strategy is **anytime-valid**: it is a proper betting strategy (λ_t is previsible, i.e., chosen before observing u_t), so the wealth process W_t remains a nonneg martingale under H₀. The false commit rate satisfies P(e-value ≥ 1/α | H₀) ≤ α by Ville's inequality.

### Why λ ∈ (-2, 2)?
With u ∈ {0, 0.5, 1} and payoff ∈ {-0.5, 0, +0.5}, the worst case is payoff = ±0.5.
For `1 + λ * payoff > 0`, we need |λ| < 2. Clipping to (-2, 2) with a small buffer (max(1e-10, ...)) ensures wealth stays positive.

## 9. Params Reference

| Key | Default | Meaning |
|-----|---------|---------|
| `α` / `alpha` | 0.05 | Type I error bound; threshold = 1/α = 20 |
| `n_min` | 8 | Minimum anchor count for B-tier |
| `continue_count_cap` | 5 | Max CONTINUE rounds before forcing decision (B/C) |
| `evalue_max_step` | 4.0 | Per-step wealth multiplier cap (B/C scaling) |
| `effective_independent_anchor_min` | 12 | Min independent anchors for B/C |
