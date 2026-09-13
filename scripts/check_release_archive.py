#!/usr/bin/env python3
"""Verify the Agentik for Noctalia release archive."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import PurePosixPath

from check_repository import KEY_SUFFIXES, PROPRIETARY_MARKERS, STALE_BRANDS, TEXT_SUFFIXES

MAX_MEMBER_SIZE = 8 * 1024 * 1024
MAX_ARCHIVE_CONTENT = 128 * 1024 * 1024
ARCHIVE_ROOT = "agentik"
REQUIRED_PATHS = {
    f"{ARCHIVE_ROOT}/LICENSE",
    f"{ARCHIVE_ROOT}/THIRD_PARTY_LICENSES",
    f"{ARCHIVE_ROOT}/README.md",
    f"{ARCHIVE_ROOT}/build_orbs.py",
    f"{ARCHIVE_ROOT}/chat_bridge.py",
    f"{ARCHIVE_ROOT}/scripts/check_repository.py",
}


def fail(message: str) -> None:
    raise SystemExit(f"release archive check failed: {message}")


def normalized_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != ARCHIVE_ROOT:
        fail(f"unsafe archive path: {name}")
    return path


def read_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        fail(f"cannot read archive member: {member.name}")
    return stream.read()


def check_archive(path: str) -> None:
    names: set[str] = set()
    content_size = 0
    try:
        archive = tarfile.open(path, mode="r:gz")
    except (OSError, tarfile.TarError) as error:
        fail(f"cannot read archive: {error}")
    with archive:
        for member in archive:
            member_path = normalized_member(member.name)
            normalized = member_path.as_posix().rstrip("/")
            if normalized in names:
                fail(f"duplicate archive path: {member.name}")
            names.add(normalized)
            relative = PurePosixPath(*member_path.parts[1:])
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                fail(f"unsupported archive member type: {member.name}")
            if relative == PurePosixPath(".git") or ".git" in relative.parts:
                fail(f"Git metadata is present: {member.name}")
            if relative.suffix.lower() in KEY_SUFFIXES:
                fail(f"key material is present: {member.name}")
            if not member.isfile():
                continue
            if member.size > MAX_MEMBER_SIZE:
                fail(f"archive member exceeds size limit: {member.name}")
            content_size += member.size
            if content_size > MAX_ARCHIVE_CONTENT:
                fail("archive content exceeds size limit")
            content = read_member(archive, member)
            if relative.as_posix() == "THIRD_PARTY_LICENSES":
                notice = content.decode("utf-8", errors="replace")
                required_notice_text = (
                    "Thinking Orbs",
                    "Copyright (c) 2026 Jakub Antalik",
                    "https://github.com/Jakubantalik/thinking-orbs",
                    "MIT License",
                )
                if any(text not in notice for text in required_notice_text):
                    fail("THIRD_PARTY_LICENSES does not preserve the Thinking Orbs MIT attribution")
            if relative.suffix.lower() not in TEXT_SUFFIXES:
                continue
            source = content.decode("utf-8", errors="replace")
            for marker in (*STALE_BRANDS, *PROPRIETARY_MARKERS):
                if marker in source:
                    fail(f"obsolete or private marker {marker!r} appears in {member.name}")
    missing = sorted(REQUIRED_PATHS - names)
    if missing:
        fail(f"required files are absent: {', '.join(missing)}")
    print(f"check_release_archive: ok ({len(names)} members, {content_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    args = parser.parse_args()
    check_archive(args.archive)


if __name__ == "__main__":
    main()
