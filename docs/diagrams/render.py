#!/usr/bin/env python3
"""Regenerate the two README workflow PNGs with Graphviz.

Install Graphviz, then run: python docs/diagrams/render.py
Use --dot /path/to/dot if Graphviz is not on PATH. Chinese labels require a
CJK font; --font "Noto Sans CJK SC" selects one for both diagrams on Linux.
Run --check to compare fresh renders without changing the committed images.
Font and Graphviz versions can affect rendering; review the images after updates.
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def render(dot, source, destination, font):
    command = [dot, "-Tpng", "-Gdpi=144"]
    if font:
        command.extend(f"-{kind}fontname={font}" for kind in ("G", "N", "E"))
    command.extend([str(source), "-o", str(destination)])
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dot", default="dot", help="Graphviz executable or path")
    parser.add_argument("--font", help="Override all diagram fonts")
    parser.add_argument("--check", action="store_true", help="Check PNG drift only")
    args = parser.parse_args()
    dot = shutil.which(args.dot)
    if not dot:
        parser.error("Graphviz was not found; install it or supply --dot PATH")

    directory = Path(__file__).resolve().parent
    sources = [directory / f"workflow-{language}.dot" for language in ("en", "cn")]
    for source in sources:
        if not source.is_file():
            parser.error(f"Missing diagram source: {source.name}")

    if not args.check:
        for source in sources:
            render(dot, source, source.with_suffix(".png"), args.font)
            print(f"Rendered {source.with_suffix('.png').name}")
        return 0

    changed = []
    with tempfile.TemporaryDirectory(prefix="readme-diagrams-") as temporary:
        for source in sources:
            committed = source.with_suffix(".png")
            generated = Path(temporary) / committed.name
            render(dot, source, generated, args.font)
            if not committed.is_file() or generated.read_bytes() != committed.read_bytes():
                changed.append(committed.name)
    if changed:
        print("PNG drift: " + ", ".join(changed))
        return 1
    print("Both PNGs match their DOT sources with this renderer and font setup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
