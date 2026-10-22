# Proposal

## Why

Every install picks the newest dependency versions the package allows on the day it runs. The tools' wheel has only minimum versions (`python-can>=4.3`, `cantools>=39`, `jsonschema>=4.0`, `paramiko>=3.5`, ...); `iroh` is the only one with an upper limit. There is no lock file, so:

- Two PCs that install the same canworks version a month apart can get different libraries, and neither got exactly what CI tested.
- A new major release of a dependency can break new installs of a canworks version that used to work, including the version a user pins with `--version`. Existing installs don't change until they are updated.
- The same applies on the device: `install-stock.sh` and `install-bridge.sh` `pip install` the tools into `/opt/canworks/venv` with the same open ranges, and so does the bridge image. The dcf-tools venv pins only `setuptools<81`.

The OpenPLC runtime is a different case. Upstream's installer and the editor pick its version, and the plugin already builds against the runtime it finds and stays off on a mismatch. CI tests one pinned runtime (`docker/local-runtime/runtime-version`, now v4.2.4), but nothing tells the user that a device runs a newer runtime than that, and nothing tells us when upstream releases one.

## What Changes

- **One lock file.** `tools/deploy/uv.lock` locks every dependency of the tools, for all supported systems and Python 3.11 and newer. A CI check fails when it no longer matches `pyproject.toml`. The wheel keeps its open minimum versions, so `pip install` from a checkout and other projects that use the package still work.
- **Each release ships the locked versions.** The release workflow exports the lock to `canworks-<version>-constraints.txt` (exact versions, no hashes) and attaches it to the release.
- **Every install uses them.** `install-pc.sh`, `install-pc.ps1` and the configurator's updater pass the release's constraints to `uv tool install --constraints`. `install-runtime.sh` passes them to `install-stock.sh` and `install-bridge.sh`, which get a `--constraints FILE` option for `pip install -c`. The bridge and local runtime images build with them. A release without the file (older than this change) installs as today, with one line saying its versions are not locked.
- **dcf-tools venv pinned.** `build-lely.sh` installs dcf-tools with a small checked-in constraints file, kept next to the Lely commit it belongs to.
- **CI tests what ships.** CI jobs that install the tools' dependencies install the locked versions.
- **Updates on purpose.** Dependabot gets a `uv` entry for `tools/deploy`: one grouped pull request a month, plus security updates when an advisory appears. CI tests each one like any other PR. A lock update without a version bump ships with the next release.
- **Tested runtime.** The PC tools know the runtime version CI tests (the same value as `docker/local-runtime/runtime-version`). The Devices page says so in one muted line when a device runs a newer runtime. This is a note, not a block. A monthly workflow opens or updates one issue when upstream releases a runtime newer than the tested one.

## Non-goals

- Locking the OpenPLC runtime or editor version. Upstream owns them, and the editor can move a device to another runtime.
- Hash-checked installs (`--require-hashes`). Exact versions from PyPI are enough for now.
- Bumping the tools' version automatically on lock updates.

## Capabilities

### Modified Capabilities

- `canopen-pc-install`: locked dependency versions in the one-line installers and the release.
- `pc-tools-self-update`: the updater uses the same constraints as the installers.
- `canopen-stock-install`: device installs use the release's constraints; dcf-tools venv pinned.
- `modbus-bridge`: bridge install and image use the constraints.
- `canopen-ci`: lock check, CI installs locked versions, Dependabot covers the lock, runtime watch.
- `device-install`: tested-runtime note on the Devices page.

## Impact

- New `tools/deploy/uv.lock`, `scripts/dcf-tools-constraints.txt`, `.github/workflows/runtime-watch.yml`.
- `scripts/install-pc.sh`, `install-pc.ps1`, `install-runtime.sh`, `install-runtime.ps1`, `install-stock.sh`, `install-bridge.sh`, `build-lely.sh`; `tools/deploy/canworks/updater.py`, `configurator/update.py`.
- `.github/workflows/release-deploy.yml` (constraints asset), `ci.yml`, `pc-tools.yml`, `integration.yml`, `browser.yml`, `bridge-image.yml`, `local-runtime.yml` (locked installs); `.github/dependabot.yml`.
- Devices page and probe result handling (tested runtime note).
- README and `docs/install-pc.md`, `docs/install-stock.md`, `docs/devices.md`.
- Tools minor version bump. No config format change.
