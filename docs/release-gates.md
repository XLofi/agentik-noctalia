# Stable release gates

A stable release is cut only from protected `main` after all gates pass on the release commit.

## Required automated gates

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile build_orbs.py chat_bridge.py omp_sessions.py scripts/build_submission.py scripts/check_manifest.py scripts/check_repository.py scripts/check_release_archive.py scripts/luau_tests.py
python3 scripts/check_manifest.py
python3 scripts/check_repository.py
git archive --format=tar.gz --prefix=agentik/ -o /tmp/agentik.tar.gz HEAD
python3 scripts/check_release_archive.py /tmp/agentik.tar.gz
python3 scripts/luau_tests.py
noctalia plugins lint .
```

CI must run the same native Noctalia lint against a pinned Noctalia version. The manifest version must be strict `MAJOR.MINOR.PATCH`; Noctalia plugin versions do not accept prerelease suffixes.

## Required release review

- Changelog covers every user-visible behavior and compatibility change.
- `plugin.toml`, README, and changelog agree on the release version.
- `build_orbs.py` regenerates a complete attributed cache pack and prunes obsolete frames.
- Archive is made from the immutable release commit; archive and checksum are attached to the GitHub release.
- GitHub build provenance signs the archive digest. `gh attestation verify agentik.tar.gz --repo XLofi/agentik-noctalia` succeeds before publication.
- Native compositor smoke: load the panel, open Chat, start a harmless local harness turn, verify streamed status, cancel a slow turn, and verify recovery to idle. Record why this is skipped only when no compositor session is available.
- Security review covers command construction, file permissions, PID/process-group handling, dependency notices, and no secret material in assets, logs, or release archives.

## Channel policy

- `internal`: signed artifacts for maintainers; no public announcement.
- `beta`: opt-in testers; backward compatibility is best effort, migration risks stated.
- `stable`: all gates passed, release notes approved, rollback archive retained.

Rollback means publish a corrected forward release or restore a prior signed archive. Never rewrite a published tag or checksum.
