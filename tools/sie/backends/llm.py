"""LLM proposer 后端：用真 Claude（cc 优先, claude fallback）据 findings 生成代码改动。

铁律1: proposer 只生成提议；采纳由确定性 harness 裁决。生成内容经 apply_patch 的
import 白名单 + AST 危险门 + 沙箱边界(+自举 IMMUTABLE 硬拒)全门控，proposer 无法绕过。
失败/超时/空 → 返回 []（propose.py 回退 builtin / run_loop 走 static_reject）。绝不抛。
"""
from __future__ import annotations
import glob
import json
import os
import subprocess
import sys

# proposer 输入的源码上限（防 prompt 过大 / 控成本）
#
# 2026-08-20: _MAX_FILE_BYTES 原为 20_000，而它是**静默**跳过的。指向一个唯一源文件 106 KB 的
# 目标时，收集结果是 0 个文件 → generate() 第一行 return [] → propose 回退 builtin（无 fix_content）
# → props 为空 → STATIC_REJECT。连跑四轮，退出码 0，accepted_versions 为空，输出与「真的没有可改进
# 之处」逐字相同。proposer 一次都没被调用过。
#
# 单文件上限提到 160 KB（约 40K token，远在现代上下文窗口内），真正的预算继续由
# _MAX_TOTAL_BYTES 承担。跳过的文件现在**记录下来**，因为一个只会静默变空的输入，跟一个「没有
# 提议」的模型是同一个可观测结果，而它们完全不是一回事。
_MAX_FILES = 12
_MAX_FILE_BYTES = 160_000
_MAX_TOTAL_BYTES = 400_000

# artifact proposer 的产物大小上限（防 prompt 过大）
_MAX_ARTIFACT_BYTES = 200_000


# The workflow scripts, resolved from THIS file rather than from the process working directory.
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def _script(name: str) -> str:
    return os.path.join(_PKG_ROOT, "workflows", name)


def _scratch_cwd() -> str:
    """A throwaway working directory for the proposer subprocess.

    The proposer is a Claude Code agent with file-writing tools, and it was inheriting this
    repository as its working directory. Over four rounds on 2026-08-20 it left
    `proposal_tmp.json`, `proposal_folded.txt`, `proposal_output.json`, `.proposer_out.json`,
    `tools/_tmp_head_pii_guard.py` and `tools/_tmp_output.json` in the repo -- each one a full or
    partial copy of the target's source -- and it also EDITED a real vendored file in place. None
    of that is in the contract; the contract is a JSON object on stdout.

    Adding each new name to .gitignore is chasing it. Giving the subprocess a working directory
    that is not a repository is the fix, and it costs one temp dir per call.
    """
    import tempfile
    return tempfile.mkdtemp(prefix="sie-proposer-")


def _empty(why: str) -> list:
    """Return [] and SAY WHY on stderr.

    Every one of the callers of this used to be a bare `return []`, and `[]` is also what the
    function returns when the model genuinely had no suggestion. One value, two meanings, and only
    the innocent one appears in the run report.
    """
    print("sie: proposer produced nothing -- %s" % why, file=sys.stderr)
    return []


def _gather_sources(sandbox_root: str, skipped: list | None = None) -> dict[str, str]:
    """收集 candidate 的非测试 .py 源码（相对路径 → 内容），受规模上限约束。

    `skipped` 若给出，会被填成 [(rel, 原因)]。调用方必须能分辨「收集到 0 个文件」与「收集到文件
    但模型没有提议」——这两者在此之前是同一个返回值。
    """
    files: dict[str, str] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(sandbox_root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", ".sie", "node_modules")
                       and not d.startswith(".")]
        for fn in sorted(filenames):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            ap = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(ap) > _MAX_FILE_BYTES:
                    if skipped is not None:
                        skipped.append((os.path.relpath(ap, sandbox_root).replace("\\", "/"),
                                        "larger than _MAX_FILE_BYTES (%d bytes)"
                                        % os.path.getsize(ap)))
                    continue
                content = open(ap, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            rel = os.path.relpath(ap, sandbox_root).replace("\\", "/")
            total += len(content)
            if total > _MAX_TOTAL_BYTES:
                return files
            files[rel] = content
            if len(files) >= _MAX_FILES:
                return files
    return files


def _extract_findings(reflections: list[dict]) -> list[str]:
    """从 reflections 提取 findings 字符串：兼容 meta_aggregate 的 merged_findings、
    M1a reflect 的 {target_failure/static_review}、以及注入的 fix 描述。"""
    out: list[str] = []
    for r in reflections or []:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("merged_findings"), list):
            out.extend(str(x) for x in r["merged_findings"])
        for k in ("target_failure", "static_review", "fixes", "finding"):
            if r.get(k):
                out.append(str(r[k]))
    # 去重保序
    seen, uniq = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq[:10]


def generate(sandbox_root: str, reflections: list[dict], timeout_s: int = 600) -> list[dict]:
    """调 workflows/claude-propose.js 生成一个 {file_rel, new_content} 提议。

    Returns [] on any failure (launch/timeout/non-zero/empty/parse) — never raises.
    """
    skipped: list = []
    files = _gather_sources(sandbox_root, skipped)
    if not files:
        # 空输入不是空提议。静默返回 [] 会让上游把「proposer 没东西可看」记成「proposer 看过了没
        # 想法」，而这个 run 的最终报告只有后者。说出来，再返回。
        print("sie: proposer gathered 0 source files from %s%s"
              % (sandbox_root,
                 (" -- skipped: " + "; ".join("%s (%s)" % t for t in skipped[:5]))
                 if skipped else ""),
              file=sys.stderr)
        return []
    payload = json.dumps({"findings": _extract_findings(reflections), "files": files})
    try:
        proc = subprocess.run(
            ["node", _script("claude-propose.js")],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 勿用 locale(GBK)解码 UTF-8 输出
            errors="replace",
            timeout=timeout_s,
            cwd=_scratch_cwd(),    # not this repo: see _scratch_cwd
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return _empty("proposer subprocess failed: %s" % type(e).__name__)
    if proc.returncode != 0:
        return _empty("proposer exited %d: %s"
                      % (proc.returncode, (proc.stderr or "").strip()[:300]))
    if not proc.stdout.strip():
        return _empty("proposer produced no stdout at all")
    try:
        obj = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        # This is NOT "no proposal". Observed 2026-08-20 on a 106 KB target: the agent decided a
        # hundred kilobytes of new_content was too much to emit inline, wrote it to a file in the
        # working directory instead, and printed prose. The contract only reads stdout, so the
        # loop recorded STATIC_REJECT while a complete, usable proposal sat on disk.
        return _empty("proposer stdout was not JSON (first 200 chars: %r). If the target file is "
                      "large the agent may have written the content to a file instead of "
                      "returning it inline; the contract only reads stdout."
                      % proc.stdout.strip()[:200])
    fr, nc = obj.get("file_rel"), obj.get("new_content")
    if not isinstance(fr, str) or not isinstance(nc, str):
        return _empty("proposer JSON lacked file_rel/new_content strings (keys: %s)"
                      % sorted(obj) if isinstance(obj, dict) else "not an object")
    if fr not in files:
        return _empty("proposer named %r, which was not one of the files it was given" % fr)
    return [{"file_rel": fr, "new_content": nc, "fixes": "llm-proposer"}]


# ---------------------------------------------------------------------------
# artifact proposer, 改研究产物 JSON（非 .py），用于 B 档 ACCEPT 闭环
# ---------------------------------------------------------------------------


def _find_target_artifact(sandbox_root: str, artifact_rel: str | None) -> str | None:
    """定位 B 档目标产物 JSON 的相对路径（相对 sandbox_root，正斜杠）。

    artifact_rel 指定时优先用它（须存在）；否则扫含结构化锚的 .json 中锚数最多者。
    找不到 → None。
    """
    if artifact_rel:
        ap = os.path.join(sandbox_root, artifact_rel)
        if os.path.isfile(ap):
            return artifact_rel.replace("\\", "/")
        return None

    from .. import anchors as _anchors  # 惰性 import: builtin/code 路径不依赖

    best_rel, best_n = None, 0
    for ap in sorted(glob.glob(os.path.join(sandbox_root, "**", "*.json"), recursive=True)):
        rel = os.path.relpath(ap, sandbox_root).replace("\\", "/")
        # 跳过 sandbox 内部目录（仅看相对路径的段，避免 sandbox_root 自身位于
        # .sie/worktrees/... 下时把目标产物误判为内部文件）
        segs = rel.split("/")
        if any(s in (".git", ".sie", "__pycache__") for s in segs[:-1]):
            continue
        try:
            n = len(_anchors.extract_anchors(ap))
        except Exception:
            continue
        if n > best_n:
            best_n = n
            best_rel = rel
    return best_rel if best_n > 0 else None


def generate_artifact(sandbox_root: str, reflections: list[dict],
                      artifact_rel: str | None = None,
                      timeout_s: int = 600) -> list[dict]:
    """调 workflows/claude-propose-artifact.js 改进研究产物 JSON。

    定位目标产物 → 读当前文本 → 调 JS（cc 优先）→ 返回 [{file_rel, new_content}]。
    铁律5: 真值字段(expected/verified/...)由 JS 在 prompt 前剥离，proposer 看不到。
    Returns [] on any failure — never raises.
    """
    target_rel = _find_target_artifact(sandbox_root, artifact_rel)
    if not target_rel:
        return []
    ap = os.path.join(sandbox_root, target_rel)
    try:
        if os.path.getsize(ap) > _MAX_ARTIFACT_BYTES:
            return []
        artifact_text = open(ap, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return []

    payload = json.dumps({
        "findings": _extract_findings(reflections),
        "artifact_path": target_rel,
        "artifact": artifact_text,
    })
    try:
        proc = subprocess.run(
            ["node", _script("claude-propose-artifact.js")],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 勿用 locale(GBK)解码 UTF-8 输出
            errors="replace",
            timeout=timeout_s,
            cwd=_scratch_cwd(),    # not this repo: see _scratch_cwd
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return _empty("artifact proposer subprocess failed: %s" % type(e).__name__)
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        obj = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    fr, nc = obj.get("file_rel"), obj.get("new_content")
    if not isinstance(fr, str) or not isinstance(nc, str) or fr != target_rel:
        return []
    # new_content 必须是合法 JSON 产物（结构门，与 JS 侧一致的二次防御）
    try:
        parsed = json.loads(nc)
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
        return []
    return [{"file_rel": fr, "new_content": nc, "fixes": "llm-artifact-proposer"}]
