"""test_m1b_acceptance.py — M1b 验收套件（端到端组合断言）.

5 组验收:
① 安全门 scan_ast_dangerous: 拒三类绕过(别名/importlib/builtins 下标) + 危险模块;
  合法代码(client.get / from os import path)不误杀。
② 变异门 mutation_validity_gate: 放水测试集 → invalid, 有效测试集 → valid。
③ acceptor decide: 纯噪声/无真增益 → REJECT; 真增益(无回退) → ACCEPT; 回退 → REJECT。
④ 人审队列 enqueue/pending/resolve: enqueue→pending 含该项; resolve → pending 不含。
⑤ 活性/计数 apply_acceptor_outcome + circuit_check: REJECT→no_progress++; 连续达阈 → 熔断 token。

用各函数真实签名实质调用; pytest 默认环境, 无需 confseq。
"""
from __future__ import annotations

import os
import random
import textwrap

from tools.sie.state import RunState
from tools.sie.patch import scan_ast_dangerous
from tools.sie.verifiable import mutation_validity_gate
from tools.sie.acceptor import decide
from tools.sie.gate_human import enqueue, pending, resolve
from tools.sie.statemachine import (
    apply_acceptor_outcome,
    circuit_check,
    note_static_reject,
)

# ---------------------------------------------------------------------------
# Shared params (mirrors statemachine default + acceptor α)
# ---------------------------------------------------------------------------
P = {
    "α": 0.05,
    "n_min": 8,
    "continue_count_cap": 5,
    "no_progress_circuit_N": 8,
    "static_reject_circuit": 6,
    "forced_review_circuit": 5,
    "drift_circuit": 4,
    "no_progress_release_M": 3,
    "evalue_max_step": 4.0,
    "effective_independent_anchor_min": 12,
}


def _rs(tier: str = "A") -> RunState:
    return RunState(run_id="t", phase="ACCEPT", round=1, parent_vid=None, tier=tier)


# ---------------------------------------------------------------------------
# ① 安全门: scan_ast_dangerous 负向全过 + 正向不误杀
# ---------------------------------------------------------------------------

def test_security_negatives_all_rejected():
    """危险源码(别名绕过/importlib/builtins 下标/危险模块)必须全部拒绝."""
    dangerous_snippets = [
        # 危险模块直接 import
        "import socket\nsocket.socket()\n",
        "import ctypes\n",
        "import subprocess\nsubprocess.run([])\n",
        # 别名绕过
        "fn = eval\nfn('1+1')\n",
        # importlib 绕过
        "import importlib\nimportlib.import_module('os')\n",
        # builtins 下标绕过
        "__builtins__['eval']('1')\n",
        # __import__ 裸调用
        "m = __import__('os')\n",
        # requests 危险模块
        "import requests\n",
    ]
    for src in dangerous_snippets:
        violations = scan_ast_dangerous(src)
        assert violations, (
            f"scan_ast_dangerous should reject dangerous source, but got empty: {src!r}"
        )


def test_security_legit_code_not_rejected():
    """合法代码(client.get / from os import path)不应被误杀."""
    safe_snippets = [
        # client.get 是普通 HTTP 客户端方法调用(不是顶层危险模块)
        "def fetch(client, url):\n    return client.get(url)\n",
        # from os import path 在 DEFAULT_IMPORT_ALLOW 中
        "from os import path\nresult = path.join('a', 'b')\n",
        # 普通数学计算
        "import math\nx = math.sqrt(4)\n",
        # 普通 json 操作
        "import json\ndata = json.dumps({'key': 'value'})\n",
    ]
    for src in safe_snippets:
        violations = scan_ast_dangerous(src)
        assert not violations, (
            f"scan_ast_dangerous falsely flagged safe code: {src!r}\n"
            f"Violations: {violations}"
        )


# ---------------------------------------------------------------------------
# ② 变异门: mutation_validity_gate 放水 → invalid, 有效 → valid
# ---------------------------------------------------------------------------

def test_mutation_gate_watering_test_invalid(tmp_path):
    """放水测试集(永远 pass 的 run_one)→ valid=False (mutant 存活)."""
    # 被变异的源文件: 包含可变异点(比较/算术)
    src_dir = tmp_path / "wt"
    src_dir.mkdir()
    src_file = src_dir / "calc.py"
    src_file.write_text(textwrap.dedent("""\
        def add(a, b):
            return a + b

        def gt(a, b):
            return a > b
    """))

    # 放水: run_one 永远返回 True (不论代码是否正确)
    def watering_run_one(worktree: str) -> bool:
        return True

    result = mutation_validity_gate(
        str(src_dir),
        ["calc.py"],
        watering_run_one,
        min_kill_ratio=1.0,
    )
    # 放水测试集不杀任何 mutant → valid=False
    assert not result["valid"], (
        f"Watering test suite should yield valid=False; got result={result}"
    )
    assert result["total"] > 0, "Should have found mutation sites"
    assert result["kill_ratio"] == 0.0, (
        f"Watering run_one should kill 0 mutants; got kill_ratio={result['kill_ratio']}"
    )


def test_mutation_gate_strong_test_valid(tmp_path):
    """有效测试集(真运行+断言捕突变)→ valid=True (mutant 全杀)."""
    import subprocess
    import sys

    src_dir = tmp_path / "wt"
    src_dir.mkdir()

    # 源文件: 单一加法函数(有 +, 一个变异点)
    src_file = src_dir / "calc.py"
    src_file.write_text(textwrap.dedent("""\
        def add(a, b):
            return a + b
    """))

    # 测试文件: 严格断言覆盖 +/- 变异
    test_file = src_dir / "test_calc.py"
    test_file.write_text(textwrap.dedent("""\
        from calc import add

        def test_add_positive():
            assert add(2, 3) == 5

        def test_add_zero():
            assert add(0, 0) == 0

        def test_add_negative():
            assert add(-1, 1) == 0
    """))

    def real_run_one(worktree: str) -> bool:
        """Run pytest in the given worktree; return True iff exit code 0."""
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=no"],
            cwd=worktree,
            capture_output=True,
        )
        return proc.returncode == 0

    result = mutation_validity_gate(
        str(src_dir),
        ["calc.py"],
        real_run_one,
        min_kill_ratio=1.0,
    )
    # Strong tests should kill the + → - mutant
    assert result["valid"], (
        f"Strong test suite should yield valid=True; got result={result}"
    )
    assert result["killed"] == result["total"], (
        f"All mutants should be killed; killed={result['killed']}, total={result['total']}"
    )


# ---------------------------------------------------------------------------
# ③ acceptor decide: 噪声/无增益 → REJECT; 真增益(无回退) → ACCEPT; 回退 → REJECT
# ---------------------------------------------------------------------------

def test_acceptor_pure_noise_rejected():
    """纯噪声配对(before/after 各 Bernoulli(0.5)) → REJECT (e-value 不过阈)."""
    r = random.Random(0)
    noise_pairs = [(float(r.random() < 0.5), float(r.random() < 0.5)) for _ in range(40)]
    result = decide(noise_pairs, "A", _rs(), P)
    assert result["decision"] == "REJECT", (
        f"Pure noise should REJECT, got {result['decision']} (evalue={result['evalue']:.4f})"
    )


def test_acceptor_true_gain_accepted():
    """真增益(before=0→after=1 高概率, 无回退)→ ACCEPT."""
    # Guaranteed no regression: if before=1, after=1 (no regression possible).
    # before~Bern(0.1) low fail rate; after=1 when before=0 (strong improvement).
    r = random.Random(7)
    gain_pairs: list[tuple[float, float]] = []
    for _ in range(60):
        before = float(r.random() < 0.1)  # mostly 0 (failing)
        if before == 1.0:
            after = 1.0  # preserve passing (no regression)
        else:
            after = float(r.random() < 0.95)  # very likely to improve
        gain_pairs.append((before, after))

    result = decide(gain_pairs, "A", _rs(), P)
    assert result["decision"] == "ACCEPT", (
        f"True gain (no regression) should ACCEPT, got {result['decision']} "
        f"(evalue={result['evalue']:.4f})"
    )
    assert result["evalue"] >= 1.0 / P["α"], (
        f"ACCEPT requires evalue >= 1/α={1/P['α']:.1f}, got {result['evalue']:.4f}"
    )


def test_acceptor_regression_hard_rejected():
    """有退化(pass→fail)→ 硬 REJECT (no-regression 门覆盖 e-process)."""
    # Mix of improvements with one clear regression (before=1 → after=0)
    pairs = [(0.0, 1.0)] * 5 + [(1.0, 0.0)] + [(0.0, 1.0)] * 5
    result = decide(pairs, "A", _rs(), P)
    assert result["decision"] == "REJECT", (
        f"Regression should cause hard REJECT, got {result['decision']}"
    )
    assert "regress" in result["reason"].lower(), (
        f"Rejection reason should mention regression, got: {result['reason']!r}"
    )


def test_acceptor_a_tier_binary_no_continue():
    """A 档决策为二态: 只有 ACCEPT 或 REJECT, 不允许 CONTINUE."""
    r = random.Random(42)
    pairs = [(float(r.random() < 0.5), float(r.random() < 0.5)) for _ in range(20)]
    result = decide(pairs, "A", _rs("A"), P)
    assert result["decision"] in ("ACCEPT", "REJECT"), (
        f"A-tier must be binary (ACCEPT/REJECT), got {result['decision']}"
    )


# ---------------------------------------------------------------------------
# ④ 人审队列: enqueue→pending 含该项; resolve → pending 不含
# ---------------------------------------------------------------------------

def test_human_queue_enqueue_shows_in_pending(tmp_path):
    """enqueue 后 pending 返回包含该项."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {"info": "test"}, "ttl": 3600})
    items = pending(rd)
    assert len(items) == 1, f"Should have 1 pending item, got {len(items)}"
    assert items[0]["aid"] == aid, f"Pending item aid mismatch: {items[0]['aid']} != {aid}"
    assert items[0]["action_type"] == "land", f"action_type mismatch: {items[0]}"


def test_human_queue_resolve_removes_from_pending(tmp_path):
    """resolve(approved) 后 pending 不再含该项."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    assert len(pending(rd)) == 1, "Should have 1 pending before resolve"

    resolve(rd, aid, "approved")

    items = pending(rd)
    assert items == [], f"After resolve, pending should be empty, got {items}"


def test_human_queue_skipped_removes_from_pending(tmp_path):
    """resolve(skipped) 同样使该项从 pending 消失."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "human_review", "payload": {}, "ttl": 3600})
    resolve(rd, aid, "skipped")
    assert pending(rd) == [], "After skipped resolve, pending should be empty"


def test_human_queue_nonblocking(tmp_path):
    """enqueue 是非阻塞的 (立即返回 aid); resolve 后 pending 清空."""
    rd = str(tmp_path)
    aid = enqueue(rd, {"action_type": "land", "payload": {}, "ttl": 3600})
    # Non-blocking check: we got a valid aid immediately
    assert isinstance(aid, str) and len(aid) > 0, f"aid should be non-empty str, got {aid!r}"
    assert len(pending(rd)) == 1
    resolve(rd, aid, "skipped")
    assert pending(rd) == []


# ---------------------------------------------------------------------------
# ⑤ 活性/计数: REJECT→no_progress++; 连续达阈 → circuit_check 返回熔断 token
# ---------------------------------------------------------------------------

def test_reject_increments_no_progress():
    """REJECT 决策 → no_progress 每次增 1, 返回 'LOOP'."""
    st = _rs()
    for i in range(1, 4):
        nxt = apply_acceptor_outcome(st, {"decision": "REJECT", "evalue": 0.0, "reason": ""}, P)
        assert nxt == "LOOP", f"REJECT should return LOOP, got {nxt}"
        assert st.no_progress == i, (
            f"no_progress should be {i} after {i} REJECTs, got {st.no_progress}"
        )


def test_no_progress_circuit_trips_at_threshold():
    """no_progress 达 no_progress_circuit_N → circuit_check 返回 'no_progress_circuit'."""
    st = _rs()
    threshold = P["no_progress_circuit_N"]
    for _ in range(threshold):
        apply_acceptor_outcome(st, {"decision": "REJECT", "evalue": 0.0, "reason": ""}, P)
    assert st.no_progress == threshold
    token = circuit_check(st, P)
    assert token == "no_progress_circuit", (
        f"Expected 'no_progress_circuit' at no_progress={threshold}, got {token!r}"
    )


def test_static_reject_circuit_trips():
    """note_static_reject × static_reject_circuit → circuit_check 返回 'static_reject_circuit'."""
    st = _rs()
    for _ in range(P["static_reject_circuit"]):
        note_static_reject(st)
    assert st.static_reject == P["static_reject_circuit"]
    token = circuit_check(st, P)
    assert token == "static_reject_circuit", (
        f"Expected 'static_reject_circuit', got {token!r}"
    )


def test_accept_clears_no_progress():
    """ACCEPT 决策清零 no_progress, 返回 'ARCHIVE'."""
    st = _rs()
    st.no_progress = 5
    st.continue_count = 2
    nxt = apply_acceptor_outcome(st, {"decision": "ACCEPT", "evalue": 99.0, "reason": "ok"}, P)
    assert nxt == "ARCHIVE", f"ACCEPT should return ARCHIVE, got {nxt}"
    assert st.no_progress == 0, f"no_progress should be cleared, got {st.no_progress}"
    assert st.continue_count == 0, f"continue_count should be cleared, got {st.continue_count}"


def test_circuit_none_before_threshold():
    """no_progress 未达阈值时 circuit_check 返回 None 或释放阀 token (非熔断)."""
    st = _rs()
    # Below both release threshold and circuit threshold → None
    assert circuit_check(st, P) is None, "No counters triggered → should return None"

    # At release threshold (M=3) but not circuit threshold (N=8)
    st.no_progress = P["no_progress_release_M"]
    token = circuit_check(st, P)
    assert token == "no_progress_release", (
        f"At release threshold should return 'no_progress_release', got {token!r}"
    )
    # Must NOT be a hard circuit-breaker token
    assert token != "no_progress_circuit", "Release valve should not be circuit-breaker"
