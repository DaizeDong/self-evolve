import os, subprocess as sp
from tools.sie.patch import import_gate, apply_patch


def test_allowed_import_passes():
    ok, why = import_gate("import json\nimport math\n", allow={"json", "math"})
    assert ok, why


def test_non_whitelisted_import_rejected():
    ok, why = import_gate("import requests\n", allow={"json"})
    assert not ok and "requests" in why


def test_dangerous_call_rejected():
    for bad in ("import os\nos.system('x')\n", "eval('1')\n",
                "import subprocess\n", "import socket\n", "__import__('os')\n"):
        ok, why = import_gate(bad, allow={"os", "subprocess", "socket"})
        assert not ok, bad  # 即便 import 在白名单, 危险调用本身被拒


def _wt(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    sp.run(["git", "init", "-q"], cwd=r, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "seed.txt").write_text("x")
    sp.run(["git", "add", "-A"], cwd=r, check=True)
    sp.run(["git", "commit", "-qm", "i"], cwd=r, check=True)
    return str(r)


def test_apply_inside_ok(tmp_path):
    root = _wt(tmp_path)
    res = apply_patch(root, "mod.py", "import json\nx = json.dumps({})\n", allow={"json"})
    assert res["status"] == "APPLIED"
    assert os.path.isfile(os.path.join(root, "mod.py"))


def test_apply_outside_rejected(tmp_path):
    root = _wt(tmp_path)
    res = apply_patch(root, "../escape.py", "x=1\n", allow=set())
    assert res["status"] == "REJECT" and "sandbox" in res["reason"].lower()


def test_apply_dangerous_rejected(tmp_path):
    root = _wt(tmp_path)
    res = apply_patch(root, "m.py", "import socket\n", allow={"socket"})
    assert res["status"] == "REJECT"
    assert not os.path.exists(os.path.join(root, "m.py"))  # 未落盘
