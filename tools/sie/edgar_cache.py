"""Prepare a distinct EDGAR cache in the verified private companion."""
from __future__ import annotations
import os
from pathlib import Path


def prepare_cache(cache_root: str | None = None) -> str:
    """Select a new private cache and preserve earlier versioned cache records.

    Set EDGAR_IDENTITY explicitly. Configure this function before starting
    parallel EDGAR operations because it sets EDGAR_LOCAL_DATA_DIR for the caller.
    """
    from tools.sie.runtime_data import private_root, verify_directory, make_directory, _new_scratch_directory
    if not os.environ.get('EDGAR_IDENTITY', '').strip():
        raise RuntimeError('Configure EDGAR_IDENTITY privately before using EDGAR')
    requested = Path(cache_root) if cache_root is not None else private_root()/'edgar-cache'
    root = make_directory(requested)
    _, repo = verify_directory(root)
    verify_directory(root, expected_repo=repo)
    cache = str(_new_scratch_directory(root, 'run-'))
    verify_directory(cache, expected_repo=repo)
    os.environ['EDGAR_LOCAL_DATA_DIR'] = cache
    return cache
