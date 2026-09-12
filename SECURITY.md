# Security policy

## Supported versions

Security fixes are provided for the latest stable release. Prereleases receive fixes only when the issue also affects the next stable release.

## Reporting a vulnerability

Do not open a public issue for a vulnerability involving journal disclosure, command construction, process cancellation, path traversal, or credential exposure. Use GitHub Security Advisories for the repository and include:

- affected Agentik and Noctalia versions;
- harness and operating system;
- minimal reproduction;
- files or credentials exposed;
- whether untrusted local input is required.

Expect acknowledgement within five business days. No bounty is promised.

## Security boundaries

Monitoring reads local process metadata, OMP journals, and optional Hermes local state. Chat deliberately launches the selected harness with that harness's configured tools, model provider, credentials, rules, and filesystem permissions. Agentik does not sandbox a harness and must not be treated as a permission boundary.

State and run logs are written below `${AGENTIK_STATE_DIR:-${XDG_STATE_HOME:-~/.local/state}/agentik/chat}` with owner-only modes. Release installers validate the checksum manifest, reject path traversal, links, devices, oversized members, and unexpected archive roots before extraction. Beta archives carry GitHub build-provenance attestations.
