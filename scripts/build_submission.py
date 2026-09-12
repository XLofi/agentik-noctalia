#!/usr/bin/env python3
"""Build the exact Agentik directory copied into community-plugins."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "LICENSE",
    "README.md",
    "THIRD_PARTY_LICENSES",
    "chat_bridge.py",
    "desktop_widget.luau",
    "monitor.luau",
    "omp_sessions.py",
    "panel.luau",
    "plugin.toml",
    "thumbnail.webp",
    "widget.luau",
)
DIRECTORIES = ("orbs", "translations")


def build(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents and destination.parent == ROOT:
        raise ValueError("submission destination must not replace a source directory")
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, mode=0o755)
    for relative in FILES:
        source = ROOT / relative
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"required submission file is unavailable: {relative}")
        shutil.copy2(source, destination / relative)
    for relative in DIRECTORIES:
        source = ROOT / relative
        if not source.is_dir() or source.is_symlink():
            raise FileNotFoundError(f"required submission directory is unavailable: {relative}")
        shutil.copytree(source, destination / relative, copy_function=shutil.copy2)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=ROOT / "dist" / "agentik-noctalia",
    )
    args = parser.parse_args()
    print(build(args.destination))


if __name__ == "__main__":
    main()
