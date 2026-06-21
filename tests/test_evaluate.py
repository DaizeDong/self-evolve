from tools.sie.evaluate import evaluate


def _mk(tmp_path, body):
    r = tmp_path / "repo"; r.mkdir()
    (r / "test_x.py").write_text(body)
    return str(r)


def test_evaluate_pass_pairs(tmp_path):
    tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
    ev = evaluate(tgt, "A", base_result=None)
    assert ev["result"]["task_passed"] is True
    assert ev["coverage"] == 1.0
    assert ev["paired"]  # 非空配对


def test_evaluate_pairs_against_base(tmp_path):
    tgt = _mk(tmp_path, "def test_ok():\n    assert True\n")
    base = {"task_passed": False, "grader_exit_code": 1,
            "dimensions": [{"name": "pytest", "tier": "A", "score": 0.0, "weight": 1.0}],
            "anchors": [], "verifiable_coverage": 1.0}
    ev = evaluate(tgt, "A", base_result=base)
    assert ev["paired"] == [(0.0, 1.0)]  # before fail -> after pass
