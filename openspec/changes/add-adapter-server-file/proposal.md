## Why

Turning the remote CAN adapter on installs the whole PC tools package on the device: `install-adapter.sh` makes a venv in `/opt/canworks-adapter`, installs `python3-venv` with apt when needed, and pip-installs the wheel with every locked dependency from GitHub. That is about 118 MB of packages (cantools, can-j1939, paramiko, iroh, jsonschema and more) for a server that uses only python-can. The device must also reach github.com and pypi.org, so a device without internet access cannot get the server at all, and the install is slow on a small board.

Toni (2026-10-24, explore "PC tools on a Linux device"): wants to install the adapter server with as few dependencies as possible, for example on an embedded Linux device without a network connection. After the explore: "Propose", option A only, keeping the `openssl` command.

The explore measured on tools 0.131.2 (report `research/minimal-adapter-server-2026-10-24.md` in the project files):
- `canworks` with `--no-deps` plus python-can serves every operation: status, scan, LSS, SDO, NMT, frames, trace, PDO test.
- One zipapp `.pyz` with canworks (no configurator, editor library, Node-RED package or CODESYS code) and python-can with its small pure-Python dependencies is 1.1 MB and runs with `python3 -I`, with no packages installed.
- The server makes its TLS certificate with the `openssl` command at every start. That stays: writing our own certificate signing code is a risk we do not need, and the command is on Raspberry Pi OS, Debian and most Linux systems.

## What Changes

- **A single-file adapter server.** Each release ships `canworks-adapter-<version>.pyz`: `canworks-diag` in one file that runs on Python 3.11 or newer with only the standard library. It carries python-can and pyserial (for slcan adapters) at the release's locked versions and nothing else. Copied to any Linux machine with Python, `python3 canworks-adapter-<version>.pyz adapter-serve --adapter socketcan:can0 --bitrate 500` runs the server, with no pip, venv or network. On an older Python it stops with one sentence naming 3.11.
- **`install-adapter.sh` installs the file, not a venv.** It puts the release's file at `/opt/canworks-adapter/canworks-adapter.pyz` unless that version is there, and installs the service as today. `--file PATH` uses a file that is already on the device. The script no longer uses pip, venv or apt. It checks for `python3` 3.11+ and `openssl` first and stops with one sentence each when they are missing. An old `/opt/canworks-adapter/venv` is removed (clean cut: nothing is in real use).
- **The service runs the file.** `adapter-serve --install-service` started from the file writes `ExecStart` as that Python and the installed file.
- **Devices needs no internet on the device.** The configurator downloads the release's `install-adapter.sh` and `.pyz` on the PC and uploads them with the token's verifier, so the job downloads nothing. When the PC cannot reach GitHub, the job downloads them on the device as today. The adapter actions are no longer blocked by "the device cannot reach github.com" or by the 2 GB free-space check that the bridge build needs.
- **The probe reads Python and openssl.** `device-probe.sh` reports the `python3` version and whether the `openssl` command is there. The Remote CAN adapter row says in one sentence what is missing instead of offering **Turn on…** when either is absent.
- **CI tests the file.** When the server, `diag.py`, the build script or the release workflow change, an existing job builds the file and runs it on a bare Python 3.11 (`-I`, no site packages) with a virtual adapter, and a PC-side client with the full tools scans and sends through it. It also fails when the file would need a module outside its list.
- README, `docs/pc-adapter.md` (copy and run) and `docs/devices.md` say what the device needs now.

## Non-goals

- Devices without Python (a bundled interpreter per architecture), and a native rewrite of the server. Both stay possible later; the explore report describes them.
- Our own certificate code instead of the `openssl` command.
- Devices for systems without systemd or sudo. The file still runs there by hand.
- A smaller file by reorganising imports (the PDO test's EDS code and the raw contract stay in it).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canopen-remote-adapter`: the single-file server, the service run from it, and `install-adapter.sh` installing the file.
- `device-install`: the PC uploads the adapter server, the device needs no internet for it, and the probe reads Python and openssl.
- `canopen-ci`: the file's test on a bare Python.

## Impact

- New `scripts/build-adapter-pyz.py`; `.github/workflows/release-deploy.yml` (build and attach the file and `install-adapter.sh`); `scripts/install-adapter.sh`.
- `tools/deploy/canworks/localbus/serve.py` (`_command` for the file), `diag.py` (Python version check in the file's entry).
- `tools/deploy/canworks/devices/` (`device-probe.sh`, `plan.py`, `jobs.py`, `release.py`), `configurator/server.py` (download and upload).
- Tests: `tests/test_install_adapter*`, device probe and plan tests, the new file test in an existing CI job.
- Bench: the bench device's `/opt/canworks-adapter/venv` is replaced by the file on the next Turn on or Change.
- Version: minor bump.
