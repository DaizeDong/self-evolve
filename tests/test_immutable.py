import os, hashlib, subprocess, pathlib, pytest
from tools.sie import immutable as im
from tools.make_fixtures import immutable_samples

EXPECTED = {
    "statemachine.py", "acceptor.py", "judges.py", "verifiable.py",
    "anchors.py", "selfdeception.py", "gate_human.py", "profile.py",
    "sandbox.py", "supervisor.py", "immutable.py",
    "patch.py", "proxy.py", "events.py",
    "runtime_data.py", "llm_adapter.py", "llm_agent_child.py",
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
    assert im.is_immutable_relpath(r"C:\absolute\path\acceptor.py") is True  # 绝对路径绕过防卫
    assert im.is_immutable_relpath("propose.py") is False
    assert im.is_immutable_relpath("reflect.py") is False

def _init_repo_with_sie(tmp_path, line_ending=b"\n"):
    sample = immutable_samples()
    root = tmp_path / "repo"
    sie = root / "tools" / "sie"
    sie.mkdir(parents=True)
    # 造两个 IMMUTABLE + 一个非 IMMUTABLE
    for name, content in sample['files'].items():
        (sie / name).write_bytes(content.replace(b"\n", line_ending))
    env = {**os.environ, "GIT_AUTHOR_NAME": sample['git_name'],
           "GIT_AUTHOR_EMAIL": sample['git_email'],
           "GIT_COMMITTER_NAME": sample['git_name'],
           "GIT_COMMITTER_EMAIL": sample['git_email']}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True, env=env)
    subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", sample["git_message"]], cwd=root, check=True, env=env)
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

def test_verify_immutable_raises_on_tamper(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    # candidate 工作区把 acceptor 改了
    (pathlib.Path(sie_root) / "acceptor.py").write_text("EVIL = 1\n", encoding="utf-8")
    with pytest.raises(im.ImmutableViolation) as ei:
        im.verify_immutable(sie_root, digests)
    assert "acceptor.py" in str(ei.value)

@pytest.mark.parametrize("case,line_ending", immutable_samples()["line_endings"])
def test_verify_immutable_passes_when_intact(tmp_path, case, line_ending):
    root = _init_repo_with_sie(tmp_path, line_ending)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    for name in ('acceptor.py', 'gate_human.py'):
        assert (pathlib.Path(frozen) / name).read_bytes() == (pathlib.Path(sie_root) / name).read_bytes()
    im.verify_immutable(sie_root, digests)

def test_verify_immutable_raises_on_missing_file(tmp_path):
    root = _init_repo_with_sie(tmp_path)
    sie_root = str(root / "tools" / "sie")
    frozen = str(tmp_path / "frozen")
    digests = im.materialize_frozen("HEAD", sie_root, frozen)
    (pathlib.Path(sie_root) / "gate_human.py").unlink()  # candidate 删了裁决文件
    with pytest.raises(im.ImmutableViolation):
        im.verify_immutable(sie_root, digests)
