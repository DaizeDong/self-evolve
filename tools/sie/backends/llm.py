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

# proposer 输入的源码上限（防 prompt 过大 / 控成本）
_MAX_FILES = 12
_MAX_FILE_BYTES = 20_000
_MAX_TOTAL_BYTES = 120_000

# artifact proposer 的产物大小上限（防 prompt 过大）
_MAX_ARTIFACT_BYTES = 200_000


def _gather_sources(sandbox_root: str) -> dict[str, str]:
    """收集 candidate 的非测试 .py 源码（相对路径 → 内容），受规模上限约束。"""
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
    files = _gather_sources(sandbox_root)
    if not files:
        return []
    payload = json.dumps({"findings": _extract_findings(reflections), "files": files})
    try:
        proc = subprocess.run(
            ["node", "workflows/claude-propose.js"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 勿用 locale(GBK)解码 UTF-8 输出
            errors="replace",
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        obj = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    fr, nc = obj.get("file_rel"), obj.get("new_content")
    if not isinstance(fr, str) or not isinstance(nc, str) or fr not in files:
        return []
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
            ["node", "workflows/claude-propose-artifact.js"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",      # 勿用 locale(GBK)解码 UTF-8 输出
            errors="replace",
            timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
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
