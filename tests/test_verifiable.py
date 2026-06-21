import os
import subprocess as sp
from tools.sie.verifiable import grade_pytest, snapshot_hash, minimal_env


def _mk(tmp_path, test_body):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "test_x.py").write_text(test_body)
    return str(r)


def test_pass_maps_to_score_1(tmp_path):
    tgt = _mk(tmp_path, "def test_ok():\n    assert 1 == 1\n")
    res = grade_pytest(tgt)
    assert res["grader_exit_code"] == 0
    assert res["task_passed"] is True
    assert res["dimensions"][0]["score"] == 1.0
    assert res["dimensions"][0]["tier"] == "A"
    assert res["verifiable_coverage"] == 1.0


def test_fail_maps_to_score_0(tmp_path):
    tgt = _mk(tmp_path, "def test_bad():\n    assert 1 == 2\n")
    res = grade_pytest(tgt)
    assert res["grader_exit_code"] != 0
    assert res["task_passed"] is False
    assert res["dimensions"][0]["score"] == 0.0


def test_minimal_env_strips_secrets():
    os.environ["MY_API_TOKEN"] = "leak"
    try:
        env = minimal_env()
        assert "MY_API_TOKEN" not in env
        assert env.get("SIE_NO_NETWORK") == "1"
    finally:
        del os.environ["MY_API_TOKEN"]


def test_network_blocked_in_grader(tmp_path):
    # Grader subprocess has socket patched -> connection raises -> test fails -> task_passed False
    body = (
        "import socket\n"
        "def test_net():\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
    )
    tgt = _mk(tmp_path, body)
    res = grade_pytest(tgt)
    assert res["task_passed"] is False  # network blocked -> test red


def test_snapshot_hash_changes(tmp_path):
    tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
    h1 = snapshot_hash(tgt)
    (tmp_path / "repo" / "test_x.py").write_text(
        "def test_ok():\n    assert True  # edit\n"
    )
    h2 = snapshot_hash(tgt)
    assert h1 != h2


def test_credentials_unreadable(tmp_path):
    body = (
        "import os\n"
        "def test_cred():\n"
        "    p = os.path.join(os.path.expanduser('~'), '.credentials.json')\n"
        "    assert not os.path.exists(p)  # HOME re-pointed to empty jail\n"
    )
    tgt = _mk(tmp_path, body)
    res = grade_pytest(tgt)
    assert res["task_passed"] is True  # jail has no credentials file


def test_discord_import_blocked(tmp_path):
    body = (
        "def test_imp():\n"
        "    import discord_relay\n"
    )
    tgt = _mk(tmp_path, body)
    res = grade_pytest(tgt)
    assert res["task_passed"] is False  # import blocked by sitecustomize
