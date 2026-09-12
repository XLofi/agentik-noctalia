#!/usr/bin/env bash
# Agentik release helper: verify, bump, tag, and publish a release.
# Usage: ./scripts/release.sh <version> [--prerelease] [-m "release notes"]
# Example: ./scripts/release.sh 0.2.0 --prerelease -m "Agentik 0.2 testing release."
# Requires: gh (authenticated), noctalia, python3, clean working tree.
set -euo pipefail

VERSION="${1:?usage: release.sh <version> [--prerelease] [-m notes]}"
NOTES=""
PRERELEASE=false
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--notes) NOTES="$2"; shift 2 ;;
        --prerelease) PRERELEASE=true; shift ;;
        *) echo "error: unknown argument '$1'" >&2; exit 1 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "error: working tree is dirty; commit or stash changes first" >&2
    exit 1
fi
if [[ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]]; then
    echo "error: releases are cut from main" >&2
    exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "error: version '$VERSION' must use MAJOR.MINOR.PATCH for Noctalia compatibility" >&2
    exit 1
fi

echo "==> bumping version to $VERSION"
sed -i -E "s/^(version = \").*(\")$/\1$VERSION\2/" plugin.toml
grep -q "version = \"$VERSION\"" plugin.toml || { echo "error: version bump failed" >&2; exit 1; }

echo "==> verifying"
python3 -m unittest discover -s tests -v
python3 -m py_compile build_orbs.py chat_bridge.py omp_sessions.py scripts/build_submission.py scripts/check_manifest.py scripts/check_repository.py scripts/check_release_archive.py scripts/luau_tests.py
noctalia plugins lint .
python3 scripts/check_manifest.py
python3 scripts/check_repository.py
python3 scripts/luau_tests.py

echo "==> smoke: panel load"
LOG="$HOME/.cache/noctalia/noctalia.log"
if [[ -f "$LOG" ]] && noctalia msg panel-open "notfinaldev/agentik-noctalia:session-panel" >/dev/null 2>&1; then
    before=$(wc -l < "$LOG")
    sleep 1
    noctalia msg panel-close "notfinaldev/agentik-noctalia:session-panel" >/dev/null 2>&1 || true
    if tail -n +$((before + 1)) "$LOG" | grep -q 'luau_load failed'; then
        echo "error: a panel script failed to load; see noctalia.log" >&2
        exit 1
    fi
else
    echo "warning: panel smoke check skipped (no compositor session)" >&2
fi

echo "==> committing and pushing v$VERSION"
git add plugin.toml README.md ROADMAP.md CHANGELOG.md
git commit -m "Release v$VERSION"
git push origin main

echo "==> waiting for CI on release commit"
RUN_ID=""
for _ in {1..30}; do
    RUN_ID="$(gh run list --workflow CI --commit "$(git rev-parse HEAD)" --json databaseId --jq '.[0].databaseId')"
    [[ -n "$RUN_ID" ]] && break
    sleep 2
done
[[ -n "$RUN_ID" ]] || { echo "error: CI run was not created" >&2; exit 1; }
gh run watch "$RUN_ID" --exit-status

git tag "v$VERSION"
git push origin "v$VERSION"


ARCHIVE="$(mktemp --suffix=.tar.gz)"
CHECKSUM="$(mktemp --suffix=.sha256)"
git archive --format=tar.gz --prefix=agentik-noctalia/ -o "$ARCHIVE" "v$VERSION"
python3 scripts/check_release_archive.py "$ARCHIVE"
sha256sum "$ARCHIVE" | sed 's#  .*#  agentik-noctalia.tar.gz#' > "$CHECKSUM"
TITLE="Agentik v$VERSION"
if [[ -z "$NOTES" ]]; then
    NOTES="Agentik $VERSION. See CHANGELOG.md for user-visible changes and compatibility notes."
fi
RELEASE_ARGS=(--title "$TITLE" --target main --notes "$NOTES")
if [[ "$PRERELEASE" == true ]]; then RELEASE_ARGS+=(--prerelease); fi
gh release create "v$VERSION" "${RELEASE_ARGS[@]}" \
    "$ARCHIVE#agentik-noctalia.tar.gz" "$CHECKSUM#agentik-noctalia.tar.gz.sha256"
rm -f "$ARCHIVE" "$CHECKSUM"
echo "==> released v$VERSION"
