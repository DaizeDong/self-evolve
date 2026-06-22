"""supervisor 双进程裁决：只读主进程从 frozen 副本 import 裁决码，candidate 永不裁决自己。

安全铁律：
- candidate worktree 路径绝不进 sys.path
- 裁决模块解析必须指向 frozen 副本，而非 candidate 工作区版本
- 隔离 import 使用 spec_from_file_location + 唯一模块名，不修改全局 sys.path
- frozen 缺模块 → 立即 raise ImmutableViolation（fail-closed）
"""
from __future__ import annotations

import os
import sys
import importlib.util
from types import ModuleType

from .immutable import ImmutableViolation, verify_immutable


def load_frozen_decider(frozen_dir: str, module: str) -> ModuleType:
    """从 frozen_dir/<module>.py 以唯一名加载，绝不把 frozen_dir 推入全局 sys.path。

    隔离机制：
    - 使用 importlib.util.spec_from_file_location 直接按文件路径建立 spec，
      完全绕过 sys.path 搜索，不修改全局 sys.path。
    - 以唯一名 "sie_frozen_{module}" 注册到 sys.modules，
      避免与 candidate 的同名模块（标准名）冲突或被其覆盖。
    - 标准名（如 "acceptor"）不写入 sys.modules，防止影响 candidate import 解析。
    - exec 后立即移除唯一名（load-and-pop），防止跨版本命名空间污染和多次调用累积。

    Args:
        frozen_dir: frozen 副本目录路径（由 materialize_frozen 生成）。
        module:     模块名（不含 .py 后缀），如 "acceptor"。

    Returns:
        已执行的 ModuleType 对象（frozen 版本）。

    Raises:
        ImmutableViolation: frozen_dir 中缺少 <module>.py，或无法建立 spec。
    """
    path = os.path.join(frozen_dir, f"{module}.py")
    if not os.path.isfile(path):
        raise ImmutableViolation(f"frozen 缺裁决模块: {module}（路径: {path}）")

    # 唯一名：防止与任何已有模块（包括 candidate 版本）在 sys.modules 中冲突。
    uniq = f"sie_frozen_{module}"

    spec = importlib.util.spec_from_file_location(uniq, path)
    if spec is None or spec.loader is None:
        raise ImmutableViolation(f"无法为 frozen 模块建 spec: {module}（路径: {path}）")

    mod = importlib.util.module_from_spec(spec)
    # 注册唯一名供模块内部自引用，exec 后移除（防止跨版本命名空间污染）。
    sys.modules[uniq] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(uniq, None)
    return mod


def candidate_path_is_isolated(frozen_dir: str, candidate_worktree: str) -> bool:
    """断言 candidate worktree 不在 supervisor 的模块解析路径（sys.path）上。

    检查逻辑：
    - 将 candidate_worktree realpath 与 sys.path 中每个条目的 realpath 比对。
    - 若 candidate_worktree == sys.path[i] 或 candidate_worktree 是 sys.path[i]
      的子目录，则视为"candidate 在解析路径上"，返回 False。
    - 空串代表 cwd，展开为 os.getcwd() 再比对（堵隔离漏洞）。
    - frozen_dir 本身允许在 sys.path（虽然 load_frozen_decider 不依赖此），不算违规。
    - Windows 大小写不敏感，用 os.path.normcase 规范化后比对。

    Args:
        frozen_dir:          frozen 副本目录（supervisor 私有，允许存在于解析路径）。
        candidate_worktree:  candidate 工作区路径，不得出现在 sys.path 上。

    Returns:
        True  → candidate 未在解析路径上（隔离正确）。
        False → candidate 在解析路径上（安全违规）。
    """
    cand_real = os.path.normcase(os.path.realpath(candidate_worktree))
    frozen_real = os.path.normcase(os.path.realpath(frozen_dir))

    for p in sys.path:
        # 空串代表 cwd，展开为实际工作目录
        raw = p if p else os.getcwd()
        try:
            pr = os.path.normcase(os.path.realpath(raw))
        except OSError:
            continue
        # candidate 在此 sys.path 条目上（精确匹配或为子目录）
        if pr == cand_real or cand_real.startswith(pr + os.sep):
            # frozen_dir 自身允许（不算 candidate 污染）
            if pr != frozen_real:
                return False
    return True


class Supervisor:
    """持有 frozen 裁决码的只读主进程裁决器。

    candidate 子进程只产原始评测数据；裁决调用由 Supervisor 用 frozen acceptor 执行，
    保证"被评测的代码不能裁决自己"。
    """

    def __init__(self, frozen_dir: str, frozen_digests: dict[str, str]) -> None:
        """初始化 Supervisor，从 frozen_dir 隔离加载裁决模块。

        Args:
            frozen_dir:      frozen 副本目录（由 materialize_frozen 生成，supervisor 私有）。
            frozen_digests:  {relpath: sha256} 哈希基线（由 materialize_frozen 返回）。
        """
        self.frozen_dir = frozen_dir
        self.frozen_digests = frozen_digests
        # 隔离加载 frozen acceptor；绝不从 candidate import。
        self._acceptor = load_frozen_decider(frozen_dir, "acceptor")

    def assert_candidate_intact(self, candidate_sie_root: str) -> None:
        """验证 candidate 的 IMMUTABLE 文件哈希与 frozen 基线一致。

        Raises:
            ImmutableViolation: 任一文件缺失、哈希不符，或 frozen_digests 为空。
        """
        verify_immutable(candidate_sie_root, self.frozen_digests)

    def decide(self, paired, tier: str, st, params: dict) -> dict:
        """用 frozen acceptor 裁决——绝不从 candidate import。

        Args:
            paired: 配对列表 [(before_score, after_score), ...]。
            tier:   档位字符串，如 "A"、"B"、"C"。
            st:     RunState 或 None。
            params: 参数字典。

        Returns:
            {"decision": "ACCEPT"|"REJECT"|"CONTINUE", "evalue": float, "reason": str, ...}
        """
        return self._acceptor.decide(paired, tier, st, params)

    def grade(self, task: dict, candidate_worktree: str, *, self_mode: bool) -> dict:
        """评测一个 task。

        self_mode=True（自举）：用 frozen verifiable.run_grader（外部 grader），
            完全不调用、不 import candidate worktree 内的 grade()。
        self_mode=False：非自举，正常由上层用 candidate contract grade
            （此路径不由 Supervisor 处理，直接 raise 引导走原路径）。

        铁律：自举时被评测代码不能给自己打分——grader 必须是 frozen/外部的。
        """
        if not self_mode:
            raise RuntimeError(
                "Supervisor.grade 仅用于 self_mode 自举评测；非自举走 evaluate 正常路径"
            )
        if not hasattr(self, "_verifiable"):
            self._verifiable = load_frozen_decider(self.frozen_dir, "verifiable")
        res = self._verifiable.run_grader(task)
        # 强制标记裁决来源，便于负向用例断言 candidate grade 未被采信。
        res.setdefault("graded_by", "FROZEN")
        return res


def candidate_grade_is_trusted(self_mode: bool) -> bool:
    """自举时 candidate 的 grade() 不被采信（spec §6 自举：用 frozen/外部 grader）。

    Returns:
        False 当 self_mode=True（自举，不信任 candidate grade）。
        True  当 self_mode=False（非自举，正常信任 candidate contract grade）。
    """
    return not self_mode
