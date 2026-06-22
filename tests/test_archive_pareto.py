"""Tests for M3.8 archive.py — Pareto multi-dim hard-dimension gate + Library Drift retire_stale.

Lineage format: a plain JSON list (matching M1a add_version format).
"""
import json
from pathlib import Path
from tools.sie import archive


def _seed(d, versions):
    """Write a lineage.json with the given version list (plain list, M1a format)."""
    lin = Path(d) / "lineage.json"
    lin.write_text(json.dumps(versions), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 1 tests: hard-dimension gate
# ---------------------------------------------------------------------------

def test_hard_dim_gate_excludes_soft_only_winner(tmp_path):
    """v3 has highest judge (soft) but low A/anchor (hard) → must not be selectable."""
    d = str(tmp_path)
    _seed(d, [
        {"vid": "v1", "scores": {"A": 0.8, "anchor": 0.7, "judge": 0.5}},
        {"vid": "v2", "scores": {"A": 0.8, "anchor": 0.7, "judge": 0.6}},
        # v3: judge最高但 A/anchor 低于前沿中位 → 冷藏不可选
        {"vid": "v3", "scores": {"A": 0.3, "anchor": 0.2, "judge": 0.99}},
    ])
    sel = archive.selectable_parents(d)
    assert "v3" not in sel, "soft-only winner must not be selectable"
    assert "v2" in sel, "v2 dominates v1 across all dims and passes hard gate"


def test_hard_dim_winner_is_selectable(tmp_path):
    """Version with true hard-dim advantage must appear in selectable_parents."""
    d = str(tmp_path)
    _seed(d, [
        {"vid": "v1", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5}},
        {"vid": "v2", "scores": {"A": 0.9, "anchor": 0.8, "judge": 0.7}},
    ])
    sel = archive.selectable_parents(d)
    assert "v2" in sel
    assert "v1" not in sel  # dominated by v2 on all dims


def test_pareto_front_multi_dim(tmp_path):
    """pareto_front must correctly identify non-dominated versions across all dims."""
    d = str(tmp_path)
    _seed(d, [
        {"vid": "v1", "scores": {"A": 0.9, "anchor": 0.5, "judge": 0.5}},
        {"vid": "v2", "scores": {"A": 0.5, "anchor": 0.9, "judge": 0.5}},
        {"vid": "v3", "scores": {"A": 0.1, "anchor": 0.1, "judge": 0.1}},
    ])
    front = archive.pareto_front(d)
    assert "v1" in front
    assert "v2" in front
    assert "v3" not in front  # dominated by both v1 and v2


def test_pareto_front_empty(tmp_path):
    """pareto_front returns empty list when no versions exist."""
    d = str(tmp_path)
    # No lineage.json
    front = archive.pareto_front(d)
    assert front == []


def test_selectable_parents_empty(tmp_path):
    """selectable_parents returns empty list when no versions exist."""
    d = str(tmp_path)
    sel = archive.selectable_parents(d)
    assert sel == []


def test_selectable_parents_all_equal_hard_dims(tmp_path):
    """When all front members have equal hard dims, all pass the median gate."""
    d = str(tmp_path)
    _seed(d, [
        {"vid": "v1", "scores": {"A": 0.7, "anchor": 0.7, "judge": 0.5}},
        {"vid": "v2", "scores": {"A": 0.7, "anchor": 0.7, "judge": 0.8}},
    ])
    sel = archive.selectable_parents(d)
    # v2 dominates v1 (same hard dims, better judge), v1 not in front
    assert "v2" in sel


# ---------------------------------------------------------------------------
# Step 3 tests: retire_stale cold-stores without deleting
# ---------------------------------------------------------------------------

def test_retire_stale_cold_stores(tmp_path):
    """retire_stale must write retired.jsonl but NOT remove versions from lineage."""
    d = str(tmp_path)
    vs = [{"vid": f"v{i}", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5},
           "last_used_round": i} for i in range(6)]
    _seed(d, vs)
    archive.retire_stale(d, active_cap=4)
    retired = Path(d) / "retired.jsonl"
    assert retired.exists(), "retired.jsonl must be created"
    lines = retired.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, f"6-4=2 versions should be cold-stored, got {len(lines)}"
    # Original lineage must still contain all 6 versions (cold-store, not delete)
    remain = json.loads((Path(d) / "lineage.json").read_text(encoding="utf-8"))
    assert len(remain) == 6, "lineage must not be modified (cold-store semantics)"


def test_retire_stale_no_op_within_cap(tmp_path):
    """retire_stale must do nothing when version count is within cap."""
    d = str(tmp_path)
    vs = [{"vid": f"v{i}", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5},
           "last_used_round": i} for i in range(3)]
    _seed(d, vs)
    archive.retire_stale(d, active_cap=5)
    retired = Path(d) / "retired.jsonl"
    assert not retired.exists(), "no retired.jsonl should be created when within cap"


def test_retire_stale_retires_oldest_by_last_used(tmp_path):
    """retire_stale should retire the versions with the lowest last_used_round."""
    d = str(tmp_path)
    vs = [
        {"vid": "v_old", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5}, "last_used_round": 1},
        {"vid": "v_mid", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5}, "last_used_round": 5},
        {"vid": "v_new", "scores": {"A": 0.5, "anchor": 0.5, "judge": 0.5}, "last_used_round": 10},
    ]
    _seed(d, vs)
    archive.retire_stale(d, active_cap=2)
    retired = Path(d) / "retired.jsonl"
    lines = [json.loads(l) for l in retired.read_text(encoding="utf-8").strip().splitlines()]
    assert len(lines) == 1
    assert lines[0]["vid"] == "v_old", "oldest by last_used_round should be retired first"


def test_retire_stale_selectable_parents_exempt(tmp_path):
    """Selectable parents (hard-dim front) must not be retired even if stale."""
    d = str(tmp_path)
    vs = [
        # v_best is on the hard-dim front: must not be retired
        {"vid": "v_best", "scores": {"A": 0.9, "anchor": 0.9, "judge": 0.9}, "last_used_round": 0},
        {"vid": "v2", "scores": {"A": 0.1, "anchor": 0.1, "judge": 0.1}, "last_used_round": 5},
        {"vid": "v3", "scores": {"A": 0.1, "anchor": 0.1, "judge": 0.1}, "last_used_round": 6},
    ]
    _seed(d, vs)
    archive.retire_stale(d, active_cap=2)
    retired = Path(d) / "retired.jsonl"
    if retired.exists():
        lines = [json.loads(l) for l in retired.read_text(encoding="utf-8").strip().splitlines()]
        retired_vids = {l["vid"] for l in lines}
        assert "v_best" not in retired_vids, "selectable parent must be exempt from retirement"
