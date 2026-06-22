"""独立 EDGAR 本地缓存管理: 每 run 独立目录 + WinError 145 (句柄锁删非空) 规避。

WinError 145: Windows 拒绝删非空目录。规避策略:
  先递归删文件 (chmod 解锁只读), 再 rmtree 删空目录; 任一步失败均容忍不崩溃。
"""
from __future__ import annotations
import os
import stat
import shutil


def _force_rmtree(path: str) -> None:
    """Robustly remove a directory tree, tolerating WinError 145 and handle locks."""

    def _on_error(func, p, exc):
        # Try to remove read-only attribute before retrying deletion
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass  # WinError 145 / handle lock: tolerate, don't let cache cleanup crash the run

    if os.path.isdir(path):
        # First pass: remove all files recursively to empty subdirs
        for dirpath, dirnames, filenames in os.walk(path, topdown=False):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    os.chmod(fpath, stat.S_IWRITE)
                    os.remove(fpath)
                except Exception:
                    pass
            # Remove now-empty subdirectories
            for dname in dirnames:
                dpath = os.path.join(dirpath, dname)
                try:
                    os.rmdir(dpath)
                except Exception:
                    pass
        # Final pass: attempt full rmtree with error handler
        try:
            shutil.rmtree(path, onerror=_on_error)
        except Exception:
            pass  # Still stuck (e.g. antivirus lock): tolerate


def prepare_cache(cache_root: str | None = None) -> str:
    """Clear (if exists) and create an isolated EDGAR local cache directory.

    Sets the ``EDGAR_LOCAL_DATA_DIR`` environment variable so edgartools uses
    this directory instead of the default ``~/.edgar``, avoiding WinError 145
    caused by handle locks on Windows.

    Also sets ``EDGAR_IDENTITY`` if not already set (required by edgartools).

    Args:
        cache_root: Path to use as cache root. Defaults to ``~/.sie_edgar_cache``.

    Returns:
        Absolute path string of the prepared (empty) cache directory.
    """
    if cache_root is None:
        cache_root = os.path.join(os.path.expanduser("~"), ".sie_edgar_cache")

    _force_rmtree(cache_root)
    os.makedirs(cache_root, exist_ok=True)

    # Point edgartools local data to isolated directory, avoiding ~/.edgar handle locks
    os.environ["EDGAR_LOCAL_DATA_DIR"] = cache_root
    os.environ.setdefault("EDGAR_IDENTITY", "self-evolve harness sie@local")

    return cache_root
