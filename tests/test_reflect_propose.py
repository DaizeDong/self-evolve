from tools.sie.reflect import reflect
from tools.sie.check_reflection import check
from tools.sie.propose import propose


def test_reflect_serial_single(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    (r / "mod.py").write_text("def add(a,b):\n    return a-b\n")  # bug
    refs = reflect(str(r), history=[], n=1)
    assert len(refs) == 1
    assert "target_failure" in refs[0] or "static_review" in refs[0]


def test_check_reflection_weak(tmp_path):
    assert check({"target_failure": "add returns wrong"}, 0.5) is True
    assert check({}, 0.5) is False  # 空反思不过


def test_propose_fallback_builtin(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    (r / "mod.py").write_text("def add(a,b):\n    return a-b\n")
    refs = [{"target_failure": "add returns a-b should be a+b",
             "file_rel": "mod.py",
             "fix_content": "def add(a,b):\n    return a+b\n"}]
    props = propose(str(r), refs, backend="builtin")
    assert len(props) >= 1
    assert props[0]["file_rel"] == "mod.py"
    assert "a+b" in props[0]["new_content"]
