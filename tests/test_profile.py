import os
import subprocess as sp
import textwrap

import pytest

from tools.sie.profile import run_profile, freeze_target, load_target


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


def test_pick_src_excludes_noise_files(tmp_path):
    """Ensure _pick_src excludes __init__.py, setup.py, conftest.py, test_*.py and skips to real src."""
    from tools.sie.probes.exec_probe import _pick_src

    r = tmp_path / "repo"
    r.mkdir()
    (r / "__init__.py").write_text("# init")
    (r / "setup.py").write_text("# setup")
    (r / "conftest.py").write_text("# conftest")
    (r / "test_foo.py").write_text("# test")
    (r / "real_mod.py").write_text("def main(): pass")
    (r / "another_mod.py").write_text("def helper(): pass")

    picked = _pick_src(str(r))
    # Should pick one of the real modules, not noise files
    assert picked is not None
    assert os.path.basename(picked) in ("another_mod.py", "real_mod.py")
    # Verify it's sorted (earliest alphabetically among candidates)
    assert os.path.basename(picked) == "another_mod.py"


def test_run_profile_with_freeze_integration(tmp_path):
    """Test run_profile(run_dir=...) auto-freezes and load_target reads frozen value."""
    src = "def add(a, b):\n    return a + b\n"
    test = "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    tgt = _mk_repo(tmp_path, src, test)
    run_dir = str(tmp_path / "run")

    # Call run_profile with run_dir → should auto-freeze
    prof = run_profile(tgt, "HEAD", run_dir=run_dir)
    assert prof["tier"] == "A"

    # Verify target.json exists and load_target reads it back
    loaded = load_target(run_dir)
    assert loaded["tier"] == "A"
    assert loaded["verifiability_score"] == 1.0
    assert loaded["base_ref"] == "HEAD"
