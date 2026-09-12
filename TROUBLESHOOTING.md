# Agentik troubleshooting

## Setup needed appears in Chat

Agentik requires Python 3 and at least one supported harness executable on `PATH`:

```sh
python3 --version
omp --version
hermes --version
```

Only one harness is required. Restart Noctalia after changing `PATH`; GUI services often retain the environment from login.

## No sessions appear

Confirm OMP journals exist under `${OMP_HOME:-~/.omp}/agent/sessions` and that the current user can read them. Projects listed in **Excluded projects** are intentionally hidden. Hermes monitoring requires a live `hermes` process; database metadata is optional.

Run the collector directly to inspect its normalized output:

```sh
python3 ~/.local/share/noctalia/plugins/agentik-noctalia/omp_sessions.py
```

## Chat reports an orphaned run

The detached worker ended without committing a terminal result. Agentik clears the busy state safely and preserves the failure in `~/.local/state/agentik/chat/state.json`. Per-run logs are stored in `~/.local/state/agentik/chat/runs/` with owner-only permissions. Inspect the matching run ID, correct the harness or provider failure, then send again.

## Cancel does not stop external work

Cancel terminates the local worker process group. A remote model request or external tool that already escaped that process group may finish independently. Inspect the harness provider and any launched service separately.

## Chat is read-only

A terminal currently owns the selected resumable journal. Continue in that terminal, wait for its `session_exit`, or select a safe fork. Agentik never starts two writers on one append-only journal.

## Plugin manifest changes do not appear

A config reload does not reparse `plugin.toml`. Disable and enable the plugin, or restart Noctalia:

```sh
noctalia msg plugins disable notfinaldev/agentik-noctalia
noctalia msg plugins enable notfinaldev/agentik-noctalia
```

## Validate an installation

```sh
cd ~/.local/share/noctalia/plugins/agentik-noctalia
noctalia plugins lint .
python3 scripts/check_manifest.py
python3 -m unittest discover -s tests
python3 scripts/luau_tests.py
```
