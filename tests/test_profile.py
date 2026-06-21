import os
import subprocess as sp
import textwrap

import pytest

from tools.sie.profile import run_profile


def _mk_repo(tmp_path, src, test):
    r = tmp_path / "repo"
    r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "mod.py").write_text(src)
    (r / "test_mod.py").write_text(test)
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "init"], cwd=r, check=True)
    return str(r)


def test_real_test_repo_is_A(tmp_path):
    src = "def add(a, b):\n    return a + b\n"
    test = "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    tgt = _mk_repo(tmp_path, src, test)
    prof = run_profile(tgt, "HEAD")
    assert prof["tier"] == "A", prof
    assert prof["probes"]["exec"]["mutation_killed"] is True


def test_fake_skip_test_is_C(tmp_path):
    src = "def add(a, b):\n    return a + b\n"
    test = "import pytest\n\n@pytest.mark.skip\ndef test_add():\n    assert False\n"
    tgt = _mk_repo(tmp_path, src, test)
    prof = run_profile(tgt, "HEAD")
    # 全 skip: 无真断言执行 -> 变异杀不死 -> 不可信 -> C
    assert prof["tier"] == "C", prof


from tools.sie.profile import freeze_target, load_target


def test_freeze_and_resume_no_reprofile(tmp_path):
    run_dir = str(tmp_path / "run")
    prof = {
        "tier": "A",
        "verifiability_score": 1.0,
        "visible": [],
        "holdout": [],
        "probes": {},
        "base_ref": "HEAD",
    }
    freeze_target(run_dir, prof)
    assert load_target(run_dir)["tier"] == "A"
