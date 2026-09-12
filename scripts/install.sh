#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${AGENTIK_REPOSITORY:-XLofi/agentik-noctalia}"
DESTINATION="${AGENTIK_PLUGIN_DIR:-$HOME/.local/share/noctalia/plugins/agentik-noctalia}"
BASE_URL="https://github.com/$REPOSITORY/releases/latest/download"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

fetch() {
    local asset="$1"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error "$BASE_URL/$asset" --output "$TEMP_DIR/$asset"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet "$BASE_URL/$asset" --output-document "$TEMP_DIR/$asset"
    else
        echo "error: curl or wget is required" >&2
        exit 1
    fi
}

fetch agentik-noctalia.tar.gz
fetch agentik-noctalia.tar.gz.sha256
(
    cd "$TEMP_DIR"
    read -r CHECKSUM_NAME CHECKSUM_FILE < agentik-noctalia.tar.gz.sha256
    [[ "$CHECKSUM_NAME" =~ ^[0-9a-fA-F]{64}$ && "$CHECKSUM_FILE" == "agentik-noctalia.tar.gz" ]] || {
        echo "error: invalid release checksum manifest" >&2
        exit 1
    }
    printf '%s  %s\n' "$CHECKSUM_NAME" "$CHECKSUM_FILE" | sha256sum --check
)
python3 - "$TEMP_DIR/agentik-noctalia.tar.gz" "$TEMP_DIR" <<'PY'
import sys
import tarfile
from pathlib import Path, PurePosixPath

archive_path, destination = sys.argv[1:]
seen = set()
total_size = 0
with tarfile.open(archive_path, "r:gz") as archive:
    for member in archive:
        path = PurePosixPath(member.name)
        normalized = path.as_posix().rstrip("/")
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.parts[0] != "agentik-noctalia"
            or normalized in seen
        ):
            raise SystemExit(f"error: unsafe release archive path: {member.name}")
        seen.add(normalized)
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise SystemExit(f"error: unsupported release archive member: {member.name}")
        if member.isfile():
            if member.size > 8 * 1024 * 1024:
                raise SystemExit(f"error: oversized release archive member: {member.name}")
            total_size += member.size
            if total_size > 128 * 1024 * 1024:
                raise SystemExit("error: release archive exceeds size limit")
    archive.extractall(Path(destination), filter="data")
PY

[[ -f "$TEMP_DIR/agentik-noctalia/plugin.toml" ]] || {
    echo "error: release archive does not contain agentik-noctalia/plugin.toml" >&2
    exit 1
}

mkdir -p "$(dirname "$DESTINATION")"
BACKUP="${DESTINATION}.previous"
rm -rf "$BACKUP"
if [[ -e "$DESTINATION" ]]; then mv "$DESTINATION" "$BACKUP"; fi
if ! mv "$TEMP_DIR/agentik-noctalia" "$DESTINATION"; then
    [[ -e "$BACKUP" ]] && mv "$BACKUP" "$DESTINATION"
    exit 1
fi
rm -rf "$BACKUP"

echo "Installed Agentik at $DESTINATION"
if command -v noctalia >/dev/null 2>&1; then
    noctalia msg plugins disable notfinaldev/agentik-noctalia >/dev/null 2>&1 || true
    noctalia msg plugins enable notfinaldev/agentik-noctalia >/dev/null 2>&1 || true
fi
