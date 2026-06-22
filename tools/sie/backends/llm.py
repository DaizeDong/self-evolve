"""LLM proposer 后端：用真 Claude（cc 优先, claude fallback）据 findings 生成代码改动。

铁律1: proposer 只生成提议；采纳由确定性 harness 裁决。生成内容经 apply_patch 的
import 白名单 + AST 危险门 + 沙箱边界(+自举 IMMUTABLE 硬拒)全门控，proposer 无法绕过。
失败/超时/空 → 返回 []（propose.py 回退 builtin / run_loop 走 static_reject）。绝不抛。
"""
from __future__ import annotations
import json
import os
import subprocess

# proposer 输入的源码上限（防 prompt 过大 / 控成本）
_MAX_FILES = 12
_MAX_FILE_BYTES = 20_000
_MAX_TOTAL_BYTES = 120_000


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
