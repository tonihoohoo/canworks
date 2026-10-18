# Proposal: bridge-one-line-install

## Why

The PC tools and the runtime plugin install and update with one copy-pasted line, on the device or from a PC over SSH (`pc-tools-speedups`, 2026-10-18). The Modbus bridge still needs a `git clone` on the device, then `sudo scripts/install-bridge.sh`, then copying a config into `/etc/canworks-bridge/NAME/` and enabling its service by hand. Toni asked (2026-10-18) for the same kind of installer for the bridge, also usable over SSH.

Two more rough edges show up on the same path:

- A re-run of `install-bridge.sh` replaces the binary but leaves running `canworks-bridge@NAME` instances on the old one until someone restarts them, so "run the line again to update" would not actually update a running bridge.
- On a device whose OpenPLC runtime runs in Docker, `install-bridge.sh` stops and tells the user to re-run with `--prefix /opt/canworks-bridge`. A one-liner should not fail on its first try on the most common bench setup.

## What Changes

- **One line on the device**: `scripts/install-bridge.sh` also runs straight from GitHub (`curl -LsSf <raw URL> | sudo bash`, options after `-s --`). Run outside a checkout it downloads the source of the newest `deploy-v` release (or `--version X`), found from the `releases/latest` redirect without the GitHub API, runs that release's `install-bridge.sh` with the other options, and removes the download. It never installs code from `main`. Running the line again updates. From a checkout the script works as today.
- **One line from a PC over SSH**: `install-bridge.sh --ssh USER@HOST [--port N] [--identity FILE]` on macOS and Linux, and a new `scripts/install-bridge.ps1 -Ssh USER@HOST` on Windows (built-in OpenSSH), both runnable as one documented line. The PC resolves the release once and runs the device side over `ssh -t` pinned to that `--version`, so `sudo` can ask for its password and both sides agree on the release. Nothing but `ssh` is needed on the PC.
- **Optional config in the same line**: `--instance NAME --config DIR` (PowerShell `-Instance`, `-Config`) installs the config folder `DIR` (its `canworks.json` and the EDS/DBC files next to it) as `/etc/canworks-bridge/NAME/`, checks it with `--check-only`, and enables and starts `canworks-bridge@NAME`. Over SSH the folder is copied to the device first (`scp`), so a bridge can be set up from a PC without logging in. A failed check leaves the service off and prints the check's messages.
- **Update restarts running bridges**: after installing a new binary, `install-bridge.sh` restarts every active `canworks-bridge@` instance and lists them.
- **Docker runtime devices just work**: when the default prefix `/opt/canworks` belongs to the runtime's Docker container, the script installs into `/opt/canworks-bridge` and says so, instead of stopping. An explicit `--prefix` keeps today's check.
- **Release version in the binary**: a release install builds with the release's version, so `canworks-bridge --version` prints it instead of `unknown`. `install-runtime.sh` does the same for the plugin (the follow-up from the `pc-tools-speedups` Pi test, where `canworks-sim --version` printed `unknown`).
- Docs: `docs/modbus-bridge.md` install section leads with the one line (device, macOS/Linux over SSH, Windows over SSH, with a config); the checkout route and the container image stay. README install section and the release notes template get the bridge line next to the runtime line.

No config, schema, page, register map or bridge behaviour change.

## Capabilities

### Modified Capabilities
- `modbus-bridge`: one-line install and update of the bridge from the newest release, on the device or from a PC over SSH, with an optional config instance; updates restart running instances; a Docker runtime's prefix is avoided by itself.
- `canopen-stock-install`: a release install reports the release version.

## Impact

- Scripts: `scripts/install-bridge.sh` (release mode, `--ssh`, `--instance`/`--config`, restart, prefix choice, wrapped in `main` so it is safe to pipe), new `scripts/install-bridge.ps1`, `scripts/install-runtime.sh` (passes the version to the build).
- Tests: `test/pc-tools/test_install_scripts.py` gains dry-run cases for both bridge scripts (release lookup, pass-through, the `ssh`/`scp` command lines, `--instance`/`--config` checks); `shellcheck` covers `install-bridge.sh`; the restart and prefix logic are tested with the script's existing `CANWORKS_SYSTEMCTL`/`CANWORKS_UNIT_DIR` overrides.
- CI: no new job. The tests join the existing tools shard (well under a second). `bridge-image.yml` runs on this PR since it is path-filtered on `install-bridge.sh`; it must still build the image from a checkout.
- Docs: `docs/modbus-bridge.md`, `README.md`, `tools/deploy/release-notes.md` (and `test/pc-tools/test_release_notes.py` if it checks install lines).
- Version: minor bump of the tools package (new install route).
- Hardware task: from the Windows PC over SSH onto the Pi (Docker runtime there, so the prefix path is exercised): install with `--instance` and a config on the Pi's CAN interface (the bridge starts, finds the interface owned by the runtime's plugin and leaves that network off, and its Modbus port answers), update by re-running and see the instance restarted, then `--uninstall --purge`; clean PLC start afterwards.
