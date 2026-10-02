#!/usr/bin/env python
"""Prepare an explicit B-target artifact in a separate PRIVATE Git repository.

Choose --artifact PATH inside the configured PRIVATE companion, or --synthetic.
The destination must be beneath that companion's data root. --private-remote
must identify the destination's own PRIVATE repository; it is never inferred
from the companion. Visibility is verified before any artifact is written.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _git(args, cwd):
    """Use the configured Git identity and all installed commit hooks."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="strict",
    )
    return result.stdout.strip()


def _safe_local_path(value):
    """Check lexical ancestors before resolving a local input or destination."""
    path = Path(os.path.abspath(value))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("B-target paths cannot traverse symlinks or reparse points")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("B-target paths cannot use hard-linked files")
    return path


def _resolve_dest(explicit: str | None) -> str:
    """Validate containment before creating or replacing a destination."""
    from tools.sie.runtime_data import private_root, runtime_directory
    root = private_root()
    requested = Path(explicit).expanduser() if explicit is not None else root / "btarget_run/btarget_repo"
    if not requested.is_absolute():
        raise ValueError("--dest must be absolute")
    dest = _safe_local_path(requested).resolve()
    if dest == root or not dest.is_relative_to(root):
        raise ValueError("B-target must stay beneath the configured PRIVATE data root")
    # The target becomes a distinct PRIVATE repo, so validate its enclosing
    # companion here and verify the target's own visibility after Git setup.
    runtime_directory(dest.parent)
    return str(dest)


def _artifact_content(artifact=None, *, synthetic=False):
    """Read one selected PRIVATE artifact or generate an explicitly synthetic one."""
    if (artifact is not None) == synthetic:
        raise ValueError("select exactly one of --artifact PATH or --synthetic")
    if synthetic:
        from tools.make_fixtures import synthetic_artifact
        payload = synthetic_artifact()
    else:
        from tools.sie.runtime_data import private_file_path
        requested = Path(artifact).expanduser()
        if not requested.is_absolute():
            raise ValueError("--artifact must be an absolute PRIVATE file path")
        path = private_file_path(_safe_local_path(requested))
        if not path.is_file():
            raise ValueError("--artifact must name an existing PRIVATE JSON file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        raise ValueError("artifact must be a JSON object with a sections list")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _load_datadir():
    """按路径加载 guards/tools/datadir.py。缺失直接抛，其余错误照常抛出。

    解析器搬进了 guards 子模块：全 fleet 一份，而不是每个仓一份（那些拷贝已经开始互相漂移）。

    缺失不再返回 None。这两个答案意思相反：None 是「这台机器还没配伴生仓」，一个正常状态；
    文件不在则意味着子模块根本没 checkout，**什么都没查过**。把后者报成前者，正是「没装的闸门」
    看起来跟「装好且干净的闸门」一模一样的原因。
    """
    p = os.path.join(_REPO, "guards", "tools", "datadir.py")
    if not os.path.isfile(p):
        raise SystemExit(
            "找不到 %s，伴生仓解析器根本没有运行。\n"
            "guards 子模块没有 checkout：请跑 `git submodule update --init`。\n"
            "这跟「没有配置伴生仓」不是一回事，不能当成一回事。" % p)
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dd_for_btarget", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact", help="absolute JSON artifact path in the PRIVATE companion")
    source.add_argument("--synthetic", action="store_true", help="use generated example.com anchors")
    parser.add_argument("--dest", help="absolute destination beneath the PRIVATE data root")
    parser.add_argument("--private-remote", required=True,
                        help="destination's own PRIVATE GitHub remote; refresh visibility before setup")
    parser.add_argument("--force", action="store_true", help="replace the validated destination")
    args = parser.parse_args(argv)
    dest = Path(_resolve_dest(args.dest))
    content = _artifact_content(args.artifact, synthetic=args.synthetic)
    if dest.exists():
        if not args.force:
            parser.error(f"destination already exists; use --force to replace: {dest}")
        if not dest.is_dir():
            parser.error("destination exists and is not a directory")
        # Check every descendant before recursive removal, including .git.
        for directory, dirs, files in os.walk(dest, followlinks=False):
            _safe_local_path(directory)
            for name in dirs + files:
                _safe_local_path(Path(directory) / name)
        _safe_local_path(dest)
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=dest)
    _git(["remote", "add", "origin", args.private_remote], cwd=dest)
    from tools.sie.runtime_data import verify_directory
    verify_directory(dest)  # Missing, PUBLIC or unknown visibility blocks artifact writes.
    _safe_local_path(dest / "report.json").write_text(content, encoding="utf-8", newline="\n")
    _git(["add", "report.json"], cwd=dest)
    _git(["commit", "-qm", "Initialize the selected B-tier target"], cwd=dest)
    head = _git(["rev-parse", "--short", "HEAD"], cwd=dest)
    print(f"standalone PRIVATE B-target repo ready: {dest} (HEAD={head})")
    print("Choose a run ID, then run:")
    print(f'  python -m tools.sie.cli run --target "{dest}" --run-id <run-id> '
          '--base-ref HEAD --max-rounds 30 --mode auto --proposer llm-artifact')
    print("Synthetic anchors demonstrate structure only; this does not establish real factual improvement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
