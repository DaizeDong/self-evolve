#!/usr/bin/env python
"""setup_btarget_repo.py — 把 B 档目标做成一个独立 git repo，供夜跑 run_loop 用.

run_loop 的 make_worktree 会对 --target 跑 `git worktree add`，要求 target 自身是
一个 git repo（且 worktree 只含该目标的文件，fact_probe 才能数对锚）。
examples/btarget/report.json 在父仓库里是普通追踪文件；夜跑前用本脚本把它
拷成一个独立 repo（默认 .btarget_run/btarget_repo/），再把那个目录当 --target。

用法:
    python scripts/setup_btarget_repo.py                       # 默认输出 .btarget_run/btarget_repo
    python scripts/setup_btarget_repo.py --dest D:/tmp/btgt    # 自定义输出目录
脚本结束会打印可直接用的 `python -m tools.sie.cli run ...` 夜跑命令。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "examples", "btarget", "report.json")


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=sie@local", "-c", "user.name=sie", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.join(_REPO, ".btarget_run", "btarget_repo"),
                    help="独立 repo 输出目录（默认 .btarget_run/btarget_repo）")
    ap.add_argument("--force", action="store_true", help="若 dest 已存在则先删除重建")
    args = ap.parse_args(argv)

    if not os.path.isfile(_SRC):
        print(f"missing source artifact: {_SRC}", file=sys.stderr)
        return 1

    dest = os.path.abspath(args.dest)
    if os.path.exists(dest):
        if not args.force:
            print(f"dest already exists (use --force to overwrite): {dest}", file=sys.stderr)
            return 1
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    shutil.copy(_SRC, os.path.join(dest, "report.json"))
    _git(["init", "-q"], cwd=dest)
    _git(["add", "report.json"], cwd=dest)
    _git(["commit", "-qm", "B-tier night-run target: real SEC/EDGAR anchors"], cwd=dest)

    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=dest,
                          capture_output=True, text=True).stdout.strip()
    print(f"standalone B-target repo ready: {dest} (HEAD={head})")
    print("\n夜跑启动命令:")
    print(
        f'  python -m tools.sie.cli run --target "{dest}" '
        f'--run-id btier_accept_$(date +%Y%m%d_%H%M%S) '
        f'--base-ref HEAD --max-rounds 30 --mode auto --proposer llm-artifact'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
