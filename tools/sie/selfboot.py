"""selfboot.py — 自举(--self)专用装配：递归隔离独立 worktree + frozen 裁决基线 + supervisor。

Public API:
  selfboot_init(self_repo_root, base_ref, run_id, runs_root) -> dict
  is_self_run(args) -> bool
"""
from __future__ import annotations

import os

from .sandbox import make_worktree
from .immutable import materialize_frozen, verify_immutable, ImmutableViolation
from .supervisor import Supervisor, candidate_path_is_isolated
from . import runtime_data


def is_self_run(args) -> bool:
    """True 当 args.self_mode 或 args.self 为真（--self 旗标开启）。"""
    return bool(getattr(args, "self_mode", False) or getattr(args, "self", False))


def selfboot_init(
    self_repo_root: str,
    base_ref: str,
    run_id: str,
    runs_root: str,
) -> dict:
    """为自举建立隔离环境。

    步骤：
    1. 建独立 candidate worktree（前缀 self__ 区分递归隔离，避免与外层 run 撞目录）。
    2. frozen 裁决基线：内容取自 base ref（git show），写到 runs_root/<run_id>/_frozen
       （candidate worktree 之外、主进程私有、candidate 不可写）。
    3. 立刻 verify_immutable：首轮 candidate 与 base ref 应完全一致；fail-closed。
    4. 断言 candidate sie root 不在 sys.path 解析路径（隔离）；失败 raise ImmutableViolation。
    5. 起 Supervisor（从 frozen import 裁决码）。

    Args:
        self_repo_root: self-evolve 仓库根目录（被自举的仓库）。
        base_ref:       git 基准引用（如 "HEAD"）。
        run_id:         run 唯一 ID（用于命名 worktree 和 run 目录）。
        runs_root:      run 根目录（frozen_dir 放这里，不在 candidate worktree 内）。

    Returns:
        {
            "candidate_worktree": str,   # candidate 独立 worktree 路径
            "frozen_dir":         str,   # frozen 副本路径（candidate 之外）
            "frozen_digests":     dict,  # {relpath: sha256}
            "supervisor":         Supervisor,
        }

    Raises:
        ImmutableViolation: verify_immutable 不通过，或 candidate 隔离断言失败。
        subprocess.CalledProcessError: git worktree 创建失败。
    """
    runtime_data.validate_run_id(run_id)
    root = runtime_data.runtime_directory(runs_root)
    _, repository = runtime_data.verify_directory(root)
    run_path, _ = runtime_data.verify_directory(root/run_id, expected_repo=repository)
    if run_path.parent != root or run_path.name != run_id:
        raise runtime_data.DataBoundaryError('Selfboot run escaped its PRIVATE root')
    frozen_path, _ = runtime_data.verify_directory(run_path/'_frozen', expected_repo=repository)
    if frozen_path.parent != run_path:
        raise runtime_data.DataBoundaryError('Selfboot frozen directory escaped its run')
    run_dir = str(run_path)
    runtime_data.make_directory(run_dir)
    runtime_data.verify_directory(run_dir, expected_repo=repository)

    # 1) 独立 candidate worktree（前缀 self__ 区分递归隔离）
    candidate_worktree = make_worktree(self_repo_root, base_ref, f"self__{run_id}")

    # 2) frozen 裁决基线（内容取自 base ref，不读 candidate 工作区）
    self_sie_root = os.path.join(self_repo_root, "tools", "sie")
    frozen_dir = str(frozen_path)
    frozen_digests = materialize_frozen(base_ref, self_sie_root, frozen_dir)

    # 3) 立刻校验 candidate 内 IMMUTABLE == frozen（首轮应一致；fail-closed）
    cand_sie_root = os.path.join(candidate_worktree, "tools", "sie")
    verify_immutable(cand_sie_root, frozen_digests)

    # 4) 断言 candidate sie root 不在 supervisor 解析路径（隔离）
    if not candidate_path_is_isolated(frozen_dir, candidate_worktree):
        raise ImmutableViolation(
            "candidate worktree 出现在 supervisor 解析路径，自举隔离失败"
        )

    # 5) 起 Supervisor（从 frozen import 裁决码，绝不从 candidate import）
    supervisor = Supervisor(frozen_dir, frozen_digests)

    return {
        "candidate_worktree": candidate_worktree,
        "frozen_dir": frozen_dir,
        "frozen_digests": frozen_digests,
        "supervisor": supervisor,
    }
