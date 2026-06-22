"""Tests for the artifact proposer (B 档研究产物 proposer).

全程 mock，不真调 Claude/node（除一个 opt-in 的 node 脱敏单测，缺 node 时跳过）。
覆盖:
  - _find_target_artifact: 指定 rel / 自动扫锚数最多 / 找不到
  - generate_artifact: 成功(mock subprocess) / node 缺失→[] / 非法 JSON→[] / 锚为空目标→[]
  - propose dispatch: backend="llm-artifact" 走 generate_artifact, 空→[] 不回退 builtin
  - 铁律5: claude-propose-artifact.js 给 Claude 的 prompt 绝不含 expected 真值
"""
import json
import os
import shutil
import subprocess
import types

import pytest

from tools.sie.backends import llm as _llm
from tools.sie.propose import propose


def _artifact(n_anchors=3, with_expected=True):
    secs = []
    for i in range(n_anchors):
        a = {
            "claim": f"claim {i}",
            "span": f"span text {i}",
            "source_url": f"https://www.sec.gov/x?CIK={i}",
            "metric": "us-gaap:Assets",
            "cik": str(i),
            "period": "2024-FY",
        }
        if with_expected:
            a["expected"] = 1000000000 + i
            a["verified"] = True
        secs.append({"text": f"t{i}", "anchors": [a]})
    return {"title": "doc", "sections": secs}


def _write(tmp_path, doc, name="report.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# _find_target_artifact
# ---------------------------------------------------------------------------

def test_find_target_artifact_explicit_rel(tmp_path):
    root = _write(tmp_path, _artifact(3))
    assert _llm._find_target_artifact(root, "report.json") == "report.json"


def test_find_target_artifact_explicit_missing_returns_none(tmp_path):
    root = _write(tmp_path, _artifact(3))
    assert _llm._find_target_artifact(root, "nope.json") is None


def test_find_target_artifact_auto_picks_most_anchors(tmp_path):
    _write(tmp_path, _artifact(2), name="small.json")
    _write(tmp_path, _artifact(7), name="big.json")
    rel = _llm._find_target_artifact(str(tmp_path), None)
    assert rel == "big.json"


def test_find_target_artifact_none_when_no_anchors(tmp_path):
    (tmp_path / "plain.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert _llm._find_target_artifact(str(tmp_path), None) is None


# ---------------------------------------------------------------------------
# generate_artifact (mock subprocess — 不真调 node/Claude)
# ---------------------------------------------------------------------------

def _fake_run_factory(stdout, returncode=0):
    def _fake_run(cmd, **kw):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return _fake_run


def test_generate_artifact_success(tmp_path, monkeypatch):
    root = _write(tmp_path, _artifact(3))
    new_doc = _artifact(3)
    new_doc["sections"][0]["anchors"][0]["expected"] = 999  # proposer 改了值
    out = {"file_rel": "report.json", "new_content": json.dumps(new_doc)}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(json.dumps(out)))
    props = _llm.generate_artifact(root, [{"merged_findings": ["fix it"]}],
                                   artifact_rel="report.json")
    assert len(props) == 1
    assert props[0]["file_rel"] == "report.json"
    assert props[0]["fixes"] == "llm-artifact-proposer"
    assert json.loads(props[0]["new_content"])["sections"][0]["anchors"][0]["expected"] == 999


def test_generate_artifact_node_missing_returns_empty(tmp_path, monkeypatch):
    root = _write(tmp_path, _artifact(3))

    def _boom(*a, **k):
        raise FileNotFoundError("node not found")
    monkeypatch.setattr(subprocess, "run", _boom)
    assert _llm.generate_artifact(root, [], artifact_rel="report.json") == []


def test_generate_artifact_invalid_json_stdout_returns_empty(tmp_path, monkeypatch):
    root = _write(tmp_path, _artifact(3))
    monkeypatch.setattr(subprocess, "run", _fake_run_factory("not json at all"))
    assert _llm.generate_artifact(root, [], artifact_rel="report.json") == []


def test_generate_artifact_new_content_not_artifact_returns_empty(tmp_path, monkeypatch):
    """new_content 是合法 JSON 但缺 sections → 结构门拒。"""
    root = _write(tmp_path, _artifact(3))
    out = {"file_rel": "report.json", "new_content": json.dumps({"foo": 1})}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(json.dumps(out)))
    assert _llm.generate_artifact(root, [], artifact_rel="report.json") == []


def test_generate_artifact_wrong_file_rel_returns_empty(tmp_path, monkeypatch):
    root = _write(tmp_path, _artifact(3))
    out = {"file_rel": "other.json", "new_content": json.dumps(_artifact(3))}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(json.dumps(out)))
    assert _llm.generate_artifact(root, [], artifact_rel="report.json") == []


def test_generate_artifact_no_artifact_in_sandbox_returns_empty(tmp_path, monkeypatch):
    # 空目录，无锚 → _find_target_artifact None → []（不应调 subprocess）
    called = {"n": 0}

    def _track(*a, **k):
        called["n"] += 1
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(subprocess, "run", _track)
    assert _llm.generate_artifact(str(tmp_path), [], artifact_rel=None) == []
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# propose dispatch
# ---------------------------------------------------------------------------

def test_propose_llm_artifact_dispatch(tmp_path, monkeypatch):
    root = _write(tmp_path, _artifact(3))
    out = {"file_rel": "report.json", "new_content": json.dumps(_artifact(3))}
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(json.dumps(out)))
    props = propose(root, [{"merged_findings": ["x"]}], backend="llm-artifact")
    assert len(props) == 1
    assert props[0]["file_rel"] == "report.json"


def test_propose_llm_artifact_empty_does_not_fallback_builtin(tmp_path, monkeypatch):
    """llm-artifact 空 → 直接 []（不回退 builtin，builtin 改代码对产物无意义）。"""
    root = _write(tmp_path, _artifact(3))

    def _boom(*a, **k):
        raise FileNotFoundError("node not found")
    monkeypatch.setattr(subprocess, "run", _boom)
    # 若回退 builtin 会试图改 .py；这里目录无 .py，且我们断言结果为 []
    assert propose(root, [], backend="llm-artifact") == []


def test_propose_builtin_unaffected(tmp_path):
    """默认 builtin 路径零回归。"""
    r = tmp_path / "repo"
    r.mkdir()
    (r / "mod.py").write_text("def add(a, b):\n    return a-b\n")
    refs = [{"target_failure": "add wrong", "file_rel": "mod.py",
             "fix_content": "def add(a, b):\n    return a+b\n"}]
    props = propose(str(r), refs, backend="builtin")
    assert props and props[0]["file_rel"] == "mod.py"


# ---------------------------------------------------------------------------
# 铁律5: claude-propose-artifact.js 给 Claude 的内容绝不含 expected 真值
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_js_strips_truth_values_from_prompt(tmp_path, monkeypatch):
    """以 dry-run 模式跑 JS：注入一个假 launcher 把收到的 prompt 落盘，
    断言 prompt 不含任何 expected 真值，但保留 claim/span/source_url。"""
    repo = os.getcwd()
    js = os.path.join(repo, "workflows", "claude-propose-artifact.js")
    assert os.path.isfile(js)

    # 用一个 stub 的 _claude_launch，把 prompt 写到文件并返回 ok=false（不真调）。
    spy = tmp_path / "prompt_seen.txt"
    stub_dir = tmp_path / "workflows"
    stub_dir.mkdir()
    # 复制真 JS 到 stub 目录，旁边放一个假的 _claude_launch.js
    shutil.copy(js, stub_dir / "claude-propose-artifact.js")
    (stub_dir / "_claude_launch.js").write_text(
        "const fs=require('fs');\n"
        "module.exports={launchClaude:(a,p)=>{fs.writeFileSync("
        + json.dumps(str(spy)) + ",p,'utf-8');return {ok:false};}};\n",
        encoding="utf-8",
    )

    doc = _artifact(3, with_expected=True)
    payload = json.dumps({
        "findings": ["fix wrong numbers"],
        "artifact_path": "report.json",
        "artifact": json.dumps(doc),
    })
    proc = subprocess.run(
        ["node", str(stub_dir / "claude-propose-artifact.js")],
        input=payload, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0
    prompt = spy.read_text(encoding="utf-8")
    # 真值绝不外泄: expected 数值 / verified 真值在脱敏后的产物块里不得出现。
    # (注: prompt 指令文本里会出现 "expected"/"verified" 这两个词——那是要求 Claude
    #  自己填值的说明，不是真值；故只断言真值本身不外泄。)
    assert "1000000000" not in prompt          # expected 真值数字
    # 脱敏产物块（从 "CURRENT ARTIFACT" 之后）里不得含真值字段
    art_block = prompt.split("CURRENT ARTIFACT", 1)[-1]
    assert '"expected"' not in art_block
    assert '"verified"' not in art_block
    # 非真值线索保留
    assert "claim 0" in prompt
    assert "span text 0" in prompt
    assert "us-gaap:Assets" in prompt
