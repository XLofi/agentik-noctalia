# Agentik for Noctalia Roadmap

Agentik is one free, MIT-licensed Noctalia plugin maintained in this repository. The canonical repository is `XLofi/agentik-noctalia`; there is no premium companion, entitlement gate, or delegated private runtime.

## Community submission

- Submit `notfinaldev/agentik` to [`noctalia-dev/community-plugins`](https://github.com/noctalia-dev/community-plugins).
- Keep the bundled Python runtime readable and document every process, filesystem, and network boundary.
- Preserve Jakub Antalik's Thinking Orbs copyright and MIT notice in source and distributions.
- Generate the attributed 30 FPS pack in the user's cache; permit users to replace it with an optional attributed 60 FPS pack.
- Keep `plugin_api = 24` while command execution uses argv tables.
- Build the exact upstream directory with `scripts/build_submission.py`.

## Quality

- Cover zero, one, and many sessions across running, waiting, blocked, completed, failed, and cancelled lifecycles.
- Exercise horizontal and vertical bars, the session panel, desktop widget, reduced motion, and increased contrast.
- Keep OMP journals single-writer-safe during chat, cancellation, recovery, forks, and terminal handoff.
- Keep Hermes optional and read its local database in read-only mode.
- Stop unnecessary animation, polling, and journal parsing while surfaces are hidden or data is unchanged.

## Release gates

- `python3 -m unittest discover -s tests -v`
- `python3 scripts/check_manifest.py`
- `python3 scripts/check_repository.py`
- `python3 scripts/luau_tests.py`
- `noctalia plugins lint .`
- Verify a release archive with `scripts/check_release_archive.py`.

## Maintainer direction

- `main` remains protected by CI and maintainer review.
- Contributions are welcome; acceptance, roadmap priority, and release timing remain maintainer decisions.
- Releases come only from the canonical repository.
- Track Noctalia API changes and update translations through Noctalia Translate.
