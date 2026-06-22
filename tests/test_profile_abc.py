import os
import json

import pytest

from tools.sie import profile


def _anchored_target(tmp_path, n=30):
    secs = [
        {
            "text": f"f{i}",
            "anchors": [
                {
                    "claim": f"c{i}",
                    "span": f"s{i}",
                    "source_url": f"https://h{i % 5}.com",
                    "cik": str(i),
                    "period": "FY",
                    "metric": "Revenues",
                    "expected": float(i),
                }
            ],
        }
        for i in range(n)
    ]
    (tmp_path / "artifact.json").write_text(
        json.dumps({"sections": secs}), encoding="utf-8"
    )
    return str(tmp_path)


def test_profile_emits_b_tier_with_anchors(tmp_path, monkeypatch):
    # 强制 exec 探针无 A 信号, 只测 B 路径
    monkeypatch.setattr(profile, "_exec_signal", lambda *a, **k: None, raising=False)
    target = _anchored_target(tmp_path, 30)
    tj = profile.run_profile(target, base_ref="HEAD")
    assert "B" in tj["tier"]
    assert len(tj["anchors_visible"]) == 21  # 30 - round(0.3*30)=9
    assert tj["anchors_holdout_ref"]["count"] == 9


def test_holdout_truth_not_in_target_json(tmp_path):
    target = _anchored_target(tmp_path, 30)
    tj = profile.run_profile(target, base_ref="HEAD")
    # 铁律5: anchors_holdout_ref 仅含引用(path/count/ref)，绝不含 holdout 真值
    ref = tj["anchors_holdout_ref"]
    # 断言: anchors_holdout_ref 只允许三个引用键
    assert set(ref.keys()) <= {"path", "count", "ref"}, f"anchors_holdout_ref 含意外键: {set(ref.keys())}"

    # 断言: target.json 的 holdout ref 中绝无真值字段
    ref_str = json.dumps(ref)
    for truth_field in ("verified", "expected", "claim", "span", "source_url"):
        assert truth_field not in ref_str, f"holdout ref 泄漏真值字段 {truth_field}: {ref_str}"

    # 对照: 隔离文件存在且含真值（确认 holdout 真值已正确隔离）
    hpath = ref["path"]
    assert os.path.exists(hpath), f"holdout.json not found at {hpath}"
    with open(hpath, encoding="utf-8") as f:
        hdata = json.load(f)
    assert len(hdata) == ref["count"], f"holdout.json record count mismatch: {len(hdata)} != {ref['count']}"
    # 隔离文件中应含有 claim/span 等真值字段（即真值已落隔离文件）
    assert any("claim" in str(anchor) for anchor in hdata), "holdout.json 应含 claim 等真值字段"


def test_holdout_file_exists_with_truth(tmp_path):
    """holdout.json 文件应在隔离路径且含锚明细（verified 字段等真值）."""
    target = _anchored_target(tmp_path, 30)
    tj = profile.run_profile(target, base_ref="HEAD")
    holdout_path = tj["anchors_holdout_ref"]["path"]
    assert os.path.exists(holdout_path), f"holdout.json not found at {holdout_path}"
    with open(holdout_path, encoding="utf-8") as f:
        holdout_data = json.load(f)
    assert isinstance(holdout_data, list)
    assert len(holdout_data) == 9
    # holdout 文件中含有锚结构（anchor_id, claim 等）
    assert all("anchor_id" in a for a in holdout_data)


def test_no_anchors_no_b_tier(tmp_path):
    (tmp_path / "x.json").write_text(
        json.dumps({"sections": [{"text": "prose only"}]}), encoding="utf-8"
    )
    tj = profile.run_profile(str(tmp_path), base_ref="HEAD")
    assert "B" not in tj["tier"]


def test_resume_does_not_reprofile(tmp_path):
    """铁律4：freeze 后 load_target 读回，不重跑 profile（tier 不变）."""
    from tools.sie.profile import freeze_target, load_target

    prof = {
        "tier": "A+B",
        "verifiability_score": 1.0,
        "visible": [],
        "holdout": [],
        "probes": {},
        "base_ref": "HEAD",
    }
    run_dir = str(tmp_path / "run")
    freeze_target(run_dir, prof)
    loaded = load_target(run_dir)
    assert loaded["tier"] == "A+B"


def test_a_b_combined_tier(tmp_path, monkeypatch):
    """A+B 可叠加：exec 有信号 + fact 锚充足 -> tier 含 A 和 B."""
    import subprocess as sp

    # Build a real git repo with passing tests (A signal)
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    (r / "test_mod.py").write_text(
        "from mod import add\ndef test_add():\n    assert add(2,3)==5\n"
    )
    # Add enough anchors for B signal (>= 24)
    secs = [
        {
            "text": f"f{i}",
            "anchors": [
                {
                    "claim": f"c{i}",
                    "span": f"s{i}",
                    "source_url": f"https://h{i % 5}.com",
                    "cik": str(i),
                    "period": "FY",
                    "metric": "Revenues",
                    "expected": float(i),
                }
            ],
        }
        for i in range(30)
    ]
    (r / "research.json").write_text(json.dumps({"sections": secs}), encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)

    tj = profile.run_profile(str(r), base_ref="HEAD")
    assert "A" in tj["tier"]
    assert "B" in tj["tier"]


def test_c_tier_no_signal(tmp_path):
    """无 exec 信号、无 fact 锚 -> tier == 'C'."""
    # Empty dir with no git repo, no tests, no anchors
    (tmp_path / "readme.txt").write_text("hello")
    tj = profile.run_profile(str(tmp_path), base_ref="HEAD")
    assert tj["tier"] == "C"
