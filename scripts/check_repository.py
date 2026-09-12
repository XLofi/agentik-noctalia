#!/usr/bin/env python3
"""Reject stale product branding, private keys, and proprietary gates."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".json", ".luau", ".md", ".py", ".sh", ".svg", ".toml", ".txt", ".yaml", ".yml"}
KEY_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
STALE_BRANDS = (
    "Agent" "Peek",
    "agent" "peek",
    "AGENT" "PEEK",
    "Agent" "Peak",
    "agent" "peak",
    "AGENT" "PEAK",
)
PROPRIETARY_MARKERS = (
    "Entitlement" "Store",
    "verify_" "entitlement",
    "read_license_" "token",
    "LICENSE_" "PUBLIC_KEY",
)


def fail(message: str) -> None:
    raise SystemExit(f"repository check failed: {message}")


def check_repository() -> None:
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or "__pycache__" in path.parts
            or "dist" in path.parts
        ):
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in KEY_SUFFIXES:
            fail(f"key material is present: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for marker in (*STALE_BRANDS, *PROPRIETARY_MARKERS):
            if marker in source:
                fail(f"obsolete or private marker {marker!r} appears in {relative}")


def main() -> None:
    check_repository()
    print("check_repository: ok (single Agentik brand, no private gates or keys)")


if __name__ == "__main__":
    main()
