## Why

Every PC install and every CI job runs on Python 3.12, which only gets security fixes now, while the code the runtime runs (the deploy tool's EDS lint, dcfgen, the editor hook) sits on the runtime image's Debian Python 3.11 and is tested on nothing older than 3.12. The declared floor, 3.10, reaches end of life this month and already breaks `uv run` from a source checkout on Windows: uv resolves for 3.10, and `libusb>=1.0.30` needs 3.11. The newest stable Python is 3.15.0 (2026-10-09); the whole unit suite passes on 3.10, 3.11, 3.12, 3.14 and 3.15 with the same run time, so the move costs no code changes (research notes: newest Python explore, 2026-10-21).

## What Changes

- The one-line PC installers (`install-pc.sh`, `install-pc.ps1`), the release notes and the docs install the tools on **Python 3.14** instead of 3.12. 3.14 rather than 3.15 for now: it is at 3.14.8 and every native dependency has wheels for it (on 3.15 `wrapt` still falls back to pure Python); moving the default to 3.15 later is a one-line change.
- The installers' "already installed" skip also compares the environment's Python: an install of the same version on an older Python is reinstalled, so the next run of the line moves existing PCs to 3.14.
- The installers update uv (`uv self update`) when it is older than the first uv that knows the chosen Python, and say how to update it when uv was not installed by its own installer.
- **BREAKING** (no users yet): the PC tools require Python **3.11** or newer (`requires-python = ">=3.11"`), the Python of the runtime image (Debian bookworm). This fixes `uv run` from a checkout on Windows.
- CI runs each job on the Python its code runs on: jobs testing code that runs on the runtime (plugin, vcan, tools shards, integration) on **3.11**; PC-only jobs (configurator-page, browser, local-runtime, PC tools on Windows and macOS) on **3.14**. Same jobs, no added time.
- Unchanged: the runtime image's Python (upstream's), bridge and link host installs (the host's `python3`), the bridge Docker image (bookworm), the CODESYS import script (CODESYS's IronPython 2.7).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-pc-install`: Python floor 3.11 (Dependency floors); the one-line installer installs with Python 3.14 and keeps uv new enough; the up-to-date skip compares the environment's Python too.
- `canopen-ci`: new requirement that each job runs on the Python its code runs on (3.11 runtime side, 3.14 PC side).

## Impact

- `scripts/install-pc.sh`, `scripts/install-pc.ps1`, `test/pc-tools/test_install_scripts.py`, `test/pc-tools/test_release_notes.py`, `tools/deploy/release-notes.md`.
- `tools/deploy/pyproject.toml` (`requires-python`, version bump: minor).
- `.github/workflows/ci.yml`, `pc-tools.yml`, `browser.yml`, `integration.yml`, `local-runtime.yml`.
- `README.md`, `docs/install-pc.md`, `docs/configurator.md`, `tools/deploy/README.md`.
- Hardware: desktop checks on Windows and macOS (one-line install moves an existing 3.12 install to 3.14, configurator starts); one Pi deploy to confirm the runtime side is unchanged.
