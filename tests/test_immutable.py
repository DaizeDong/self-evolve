import os, hashlib, subprocess, pathlib, pytest
from tools.sie import immutable as im

EXPECTED = {
    "statemachine.py", "acceptor.py", "judges.py", "verifiable.py",
    "anchors.py", "selfdeception.py", "gate_human.py", "profile.py",
    "sandbox.py", "supervisor.py", "immutable.py",
}

def test_immutable_relpaths_cover_spec_decision_set():
    got = set(im.IMMUTABLE_RELPATHS)
    missing = EXPECTED - got
    assert not missing, f"IMMUTABLE 清单缺裁决模块: {missing}"

def test_is_immutable_relpath_normalizes_and_rejects_bypass():
    assert im.is_immutable_relpath("acceptor.py") is True
    assert im.is_immutable_relpath("./acceptor.py") is True
    assert im.is_immutable_relpath("tools/sie/acceptor.py") is True
    assert im.is_immutable_relpath("tools\\sie\\acceptor.py") is True
    assert im.is_immutable_relpath("sub/../acceptor.py") is True
    assert im.is_immutable_relpath("propose.py") is False
    assert im.is_immutable_relpath("reflect.py") is False

def _init_repo_with_sie(tmp_path):
    root = tmp_path / "repo"
    sie = root / "tools" / "sie"
    sie.mkdir(parents=True)
    # 造两个 IMMUTABLE + 一个非 IMMUTABLE
    (sie / "acceptor.py").write_text("ACCEPTOR_V1 = 1\n", encoding="utf-8")
    (sie / "gate_human.py").write_text("GATE_V1 = 1\n", encoding="utf-8")
    (sie / "propose.py").write_text("PROPOSE_V1 = 1\n", encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True, env=env)
    return root

def test_materialize_frozen_writes_only_immutable_with_base_ref_content(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    # 物化后再篡改工作区 acceptor，frozen 必须仍是 base 内容
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    (pathlib.Path(sie_root) / "acceptor.py").write_text("TAMPERED = 999\n", encoding="utf-8")
    frozen_acc = pathlib.Path(frozen) / "acceptor.py"
    assert frozen_acc.read_text(encoding="utf-8") == "ACCEPTOR_V1 = 1\n"
    # 非 IMMUTABLE 不进 frozen
    assert not (pathlib.Path(frozen) / "propose.py").exists()
    # 哈希与 frozen 内容一致
    assert digests["acceptor.py"] == im.hash_file(str(frozen_acc))
    assert set(digests) >= {"acceptor.py", "gate_human.py"}
