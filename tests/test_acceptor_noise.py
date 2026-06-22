"""test_acceptor_noise.py — M1b.3: PACE A 档 e-process 噪声/真增益/对抗验收测试.

验收门:
① 纯噪声配对序列 → 误采纳率 ≤ α (False-commit control)
② 真增益序列 → 高采纳率 (Power)
③ A 档二态 (无 CONTINUE)
④ 对抗序列 (微漂移, 无真实配对增益) → REJECT
⑤ e-process 单独 type-I (隔离硬门, 连续 null 直接喂 _wealth_betting)

注意:
  test_false_commit_rate_under_alpha / test_pure_noise_reject_rate_near_one 测试的是
  "硬门 + e-process 组合"系统级行为。二元 null 下无回退 + 无增益 ⇒ d≡0, e-process
  W≡1, 此时 0.0 误采纳完全由 decide() 内硬门+组合机制正确处理, 不单独验证 e-process。
  e-process 自身的 type-I 须用连续值 null 序列隔离验证 (test_eprocess_standalone_type1)。

无需 confseq 安装; 全走 ONS 回退路径.
"""
import random
import pytest
from tools.sie.state import RunState
from tools.sie.acceptor import decide, _wealth_betting

PARAMS = {"α": 0.05, "n_min": 8, "continue_count_cap": 5,
          "evalue_max_step": 4.0, "effective_independent_anchor_min": 12}


def _rs(tier="A"):
    return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None,
                    tier=tier)


def _pure_noise_pairs(n, seed):
    """before/after 各独立 Bernoulli(0.5), 无真实增益."""
    r = random.Random(seed)
    return [(float(r.random() < 0.5), float(r.random() < 0.5)) for _ in range(n)]


def _true_gain_pairs(n, seed, before_p=0.3, after_p=0.9):
    """True gain pairs: before~Bern(before_p), after drawn so that after>=before.

    Models a "genuinely better" patch: improvements are common (before=0→after=1
    with high probability) and regressions are structurally absent (if before=1,
    after stays 1 — the pass is preserved). This reflects the intended usage in
    self-evolve: a truly beneficial patch does not break existing passing tasks.

    Statistical signal: E[u] = E[0.5*(after-before+1)] >> 0.5 under the true gain
    distribution, so the betting martingale wealth rapidly exceeds 1/α.
    """
    r = random.Random(seed)
    pairs = []
    for _ in range(n):
        before = float(r.random() < before_p)
        # Avoid regression: if before=1, after must be 1;
        # if before=0, after~Bern(after_p).
        if before == 1.0:
            after = 1.0
        else:
            after = float(r.random() < after_p)
        pairs.append((before, after))
    return pairs


def test_pure_noise_reject_rate_near_one():
    """纯噪声拒绝率应接近 1 (≥ 0.95)."""
    rejects = 0
    trials = 200
    for s in range(trials):
        d = decide(_pure_noise_pairs(40, s), "A", _rs(), PARAMS)
        if d["decision"] == "REJECT":
            rejects += 1
    rate = rejects / trials
    assert rate >= 0.95, f"纯噪声拒绝率 {rate:.3f} < 0.95"


def test_false_commit_rate_under_alpha():
    """真 null 下误 ACCEPT 率必须 ≤ α=0.05 (anytime-valid 保证)."""
    commits = 0
    trials = 400
    for s in range(trials):
        d = decide(_pure_noise_pairs(40, s + 9000), "A", _rs(), PARAMS)
        if d["decision"] == "ACCEPT":
            commits += 1
    rate = commits / trials
    assert rate <= 0.05, f"误采纳率 {rate:.4f} > 0.05 (α=0.05)"


def test_true_gain_accept_rate_high():
    """真增益(before_p=0.3, after_p=0.9)采纳率应 ≥ 0.9."""
    accepts = 0
    trials = 100
    for s in range(trials):
        d = decide(_true_gain_pairs(40, s), "A", _rs(), PARAMS)
        if d["decision"] == "ACCEPT":
            accepts += 1
    rate = accepts / trials
    assert rate >= 0.9, f"真增益采纳率 {rate:.2f} < 0.90"


def test_A_tier_never_continue():
    """A 档决策必须是 ACCEPT 或 REJECT, 禁 CONTINUE."""
    d = decide(_true_gain_pairs(40, 1), "A", _rs(), PARAMS)
    assert d["decision"] in ("ACCEPT", "REJECT"), f"A 档返回非法决策: {d['decision']}"


def test_adversarial_drift_rejected():
    """对抗: 主观微涨(+0.005 绝对值)在 A 档配对差≈0 → REJECT.

    pairs=(0.6, 0.605) — 两值均非 {0,1}, diff=0.005 极小,
    e-value 无法积累到阈值 1/α=20 → 正确拒绝.
    """
    pairs = [(0.6, 0.6 + 0.005) for _ in range(40)]
    d = decide(pairs, "A", _rs(), PARAMS)
    assert d["decision"] == "REJECT", (
        f"对抗序列应 REJECT, 得 {d['decision']} (evalue={d['evalue']:.4f})")


def test_evalue_threshold_is_inverse_alpha():
    """ACCEPT 时 evalue 必须 ≥ 1/α (阈值语义正确)."""
    d = decide(_true_gain_pairs(60, 3, before_p=0.1, after_p=0.95), "A", _rs(), PARAMS)
    if d["decision"] == "ACCEPT":
        assert d["evalue"] >= 1.0 / PARAMS["α"], (
            f"ACCEPT 但 evalue={d['evalue']:.4f} < 1/α={1/PARAMS['α']}")


def test_regression_hard_rejects_even_with_gain():
    """no-regression 覆盖: 有退化 → 硬 REJECT (覆盖 e-process)."""
    # 前 3 对有增益, 最后 1 对退化 (pass→fail)
    pairs = [(0.0, 1.0)] * 3 + [(1.0, 0.0)]
    d = decide(pairs, "A", _rs(), PARAMS)
    assert d["decision"] == "REJECT", f"有退化应 REJECT, 得 {d['decision']}"
    assert "regress" in d["reason"].lower(), f"原因须提 regression: {d['reason']}"


def test_eprocess_standalone_type1():
    """e-process 单独 type-I 验证 (隔离硬门，连续 null 直接喂 _wealth_betting).

    设计说明:
    - 二元 A 档的 null 由"硬门 + e-process(W=1 当 d≡0)"组合正确处理, 无需单独验证。
    - e-process 自身的 type-I 必须用连续值 null 来隔离, 此测试做到这一点:
      直接构造 diffs 序列满足 E[d]=0 (即 u~Uniform(0,1), payoff 均值=0, null 成立),
      绕过 decide() 的硬门, 直接调 _wealth_betting, 统计 path_max ≥ 1/α 的比例。

    断言: 误采纳率 ≤ α=0.05 (Ville 不等式 e-process 保证).
    """
    alpha = PARAMS["α"]
    threshold = 1.0 / alpha  # 20.0
    n_seq = 40    # 每 trial 序列长度
    n_trials = 400
    rng = random.Random(42)

    false_accepts = 0
    for _ in range(n_trials):
        # u ~ Uniform(0,1): null H₀: E[u]=0.5, 连续值, 无配对回退语义
        # diff = 2*(u - 0.5) ∈ (-1,1), E[diff]=0
        diffs = [2.0 * (rng.random() - 0.5) for _ in range(n_seq)]
        evalue, path = _wealth_betting(diffs, alpha)
        path_max = max(path) if path else 1.0
        if path_max >= threshold:
            false_accepts += 1

    rate = false_accepts / n_trials
    print(f"\n[e-process standalone type-I] 实测误采纳率 = {rate:.4f} "
          f"(trials={n_trials}, n_seq={n_seq}, α={alpha})")
    assert rate <= alpha, (
        f"e-process 单独 type-I 误采纳率 {rate:.4f} > α={alpha:.2f}; "
        f"e-process 鞅属性可能被破坏"
    )
