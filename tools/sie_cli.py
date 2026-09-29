"""Portable self-evolve CLI entrypoint, including installation junctions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.sie.cli import main


if __name__ == '__main__':
    raise SystemExit(main())
