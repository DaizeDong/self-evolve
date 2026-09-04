#!/usr/bin/env python
"""setup_btarget_repo.py — 把 B 档目标做成一个独立 git repo，供夜跑 run_loop 用.

run_loop 的 make_worktree 会对 --target 跑 `git worktree add`，要求 target 自身是
一个 git repo（且 worktree 只含该目标的文件，fact_probe 才能数对锚）。
examples/btarget/report.json 在父仓库里是普通追踪文件；夜跑前用本脚本把它
拷成一个独立 repo（默认解析到私有伴生仓，绝不落在本仓内），再把那个目录当 --target。

用法:
    python scripts/setup_btarget_repo.py                       # 默认输出到私有伴生仓
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


def _resolve_dest(explicit: str | None) -> str:
    """决定 B 档目标 repo 落在哪。默认走私有伴生仓，且绝不允许落在本仓内部。

    这里原来的默认值是 `_REPO/.btarget_run/btarget_repo`，也就是**公开仓内部**。文档里那条
    无参数命令是被推荐的用法，所以每跑一次就在公开仓里造一个真的 git repo；2026-08-30 实测
    复现过一次。`guards/tools/datadir.py` 本来会拒绝这种路径（DataDirInsideOwnRepo），但这个脚本
    从不 import 它，所以从来没被问过。127 个运行产出就是这么攒出来的。

    显式 --dest 仍然优先，因为把目标放在别处是正当用法。但无论来自默认值还是 --dest，只要
    解析结果落在本仓内部就硬失败：一个入口修好、另一个没修，等于没修。

    未初始化时抛 DataDirNotInitialized 并带上初始化指引，而不是悄悄退回仓内路径。退回仓内
    不是便利，它就是那个泄漏本身。
    """
    dd = _load_datadir()
    if explicit is not None:
        dest = os.path.abspath(os.path.expanduser(explicit))
    elif dd is None:
        raise SystemExit(
            "找不到 guards/tools/datadir.py，无法解析私有伴生仓，也不会退回仓内路径。\n"
            "请用 --dest 指定一个本仓之外的目录。")
    else:
        # create=True：伴生仓存在但还没有这个子目录时直接建，不存在伴生仓时抛异常。
        dest = str(dd.data_path("self-evolve", os.path.join("btarget_run", "btarget_repo"),
                                create=True))
    inside = os.path.normcase(dest).startswith(os.path.normcase(_REPO) + os.sep)
    if inside:
        raise SystemExit(
            "拒绝把 B 档目标建在本仓内部：\n  %s\n"
            "公开 skill 仓只装工具；真实运行产出属于旁边那个私有伴生仓。\n"
            "不带 --dest 即可解析到正确位置，或把 --dest 指向本仓之外。" % dest)
    return dest


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
            "找不到 %s，伴生仓解析器根本没有运行。
"
            "guards 子模块没有 checkout：请跑 `git submodule update --init`。
"
            "这跟「没有配置伴生仓」不是一回事，不能当成一回事。" % p)
    import importlib.util
    spec = importlib.util.spec_from_file_location("_dd_for_btarget", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=None,
                    help="独立 repo 输出目录（默认解析到私有伴生仓，见 guards/COMPANION.md）")
    ap.add_argument("--force", action="store_true", help="若 dest 已存在则先删除重建")
    args = ap.parse_args(argv)
    args.dest = _resolve_dest(args.dest)

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
