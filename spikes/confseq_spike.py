"""confseq 第 0 步硬前置 spike: 纯噪声序列验证 e-process 拒绝率。
失败(纯噪声误报率高 / 拿不到 e-value 接口)则 M1 acceptor 方案需重选。

实际使用接口: confseq.betting.betting_mart
  - 输入: x (0-1 bounded obs), m (null mean)
  - 输出: martingale wealth 逐步累积数组 (e-process)
  - H0: 配对差均值 <= 0 (diff=0 -> x=0.5 @ null)
  - 越过 1/alpha 阈值 = 拒绝 H0 = 判定"有增益"

NOTE: confseq 需在 Python 3.10 + Boost 环境下编译安装。
  建议使用: conda run -n confseq_test python -m pytest tests/test_confseq_spike.py
"""
from __future__ import annotations

import numpy as np
from confseq.betting import betting_mart  # e-process martingale (wealth)

_E_INTERFACE = "confseq.betting.betting_mart"


def _e_process_wealth(diffs: np.ndarray) -> np.ndarray:
    """把配对差序列喂 betting martingale, 返回逐步 wealth(e-value 数组).

    H0: 真实均值 <= 0 (无增益); 把 diff 映射到 [0,1] 后检验 mean > 0.5.
    diff=0  -> x=0.5 (null 中心, wealth 不增)
    diff>0  -> x>0.5 (偏向有增益, wealth 可增)
    diff<0  -> x<0.5 (反向, wealth 可减)
    """
    x = np.clip(0.5 + diffs, 0.0, 1.0)
    return np.asarray(betting_mart(x, m=0.5), dtype=float)


def run_noise_spike(
    n_trials: int,
    n_steps: int,
    alpha: float,
    seed: int,
    drift: float = 0.0,
) -> dict:
    """纯噪声(或有漂移)配对差序列 e-process 实验.

    Parameters
    ----------
    n_trials : int
        重复试验次数.
    n_steps : int
        每次试验配对观测步数.
    alpha : float
        显著性水平; 采纳阈值 = 1/alpha.
    seed : int
        随机种子(可复现).
    drift : float
        配对差的真实均值; 0.0 = 纯噪声 (H0 成立), >0 = 真实正向增益.

    Returns
    -------
    dict
        - ``e_interface`` (str): 实际使用的 confseq 接口全名.
        - ``threshold`` (float): 采纳阈值 1/alpha.
        - ``false_reject_rate`` (float, 仅 drift==0): 纯噪声被误判"有增益"比例.
        - ``detect_rate`` (float, 仅 drift!=0): 真实增益被正确检出比例.
    """
    rng = np.random.default_rng(seed)
    thresh = 1.0 / alpha
    crossed = 0
    for _ in range(n_trials):
        # 配对差 ~ N(drift, 0.1); scale=0.1 使 x 大部分留在 [0,1]
        diffs = rng.normal(loc=drift, scale=1.0, size=n_steps) * 0.1
        wealth = _e_process_wealth(diffs)
        if np.nanmax(wealth) >= thresh:
            crossed += 1
    rate = crossed / n_trials
    out: dict = {"e_interface": _E_INTERFACE, "threshold": thresh}
    if drift == 0.0:
        out["false_reject_rate"] = rate
    else:
        out["detect_rate"] = rate
    return out
