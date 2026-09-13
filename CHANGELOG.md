# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## Unreleased

### Added

- Detached, cancellable coding-agent runs with immutable run IDs and explicit lifecycle states.
- Live semantic events for assistant output, tools, todos, choices, completion, and failures.
- Shared monitor-driven chat polling for the panel and desktop widget.
- First-run runtime health status, feed history expansion, reduced-motion mode, and increased-contrast mode.
- Release archives with checksums plus atomic install and update scripts.
- Explicit running, waiting, blocked, completed, failed, and cancelled lifecycle descriptions for OMP and Hermes sessions.
- A reviewable upstream submission builder that includes runtime files only.
- A submission thumbnail and complete runtime, dependency, command, settings, and filesystem-access documentation.

### Changed

- The permanent plugin ID is `notfinaldev/agentik`; Noctalia plugin API 24 enables shell-free argv command execution.
- The attributed orb pack is generated into the user's cache on first run instead of shipping thousands of generated files.
- Idle monitoring backs off from one second to five seconds and unchanged journals avoid cache rewrites.

### Fixed

- Runs longer than the UI async timeout remain supervised and visible.
- Cancel waits for process-group termination and protects against PID reuse.
- Stale workers cannot overwrite a newer run.
- Dead workers recover to an explicit orphaned state instead of leaving permanent busy state.
- Clipboard, project-directory, collector, and chat commands no longer interpolate values into shell command strings.
