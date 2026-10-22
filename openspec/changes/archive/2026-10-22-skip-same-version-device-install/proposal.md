## Why

Running the device install again with the version that is already there still does everything: the plugin is rebuilt from scratch (the slow part on a Raspberry Pi), the tools are reinstalled, and on the managed Docker runtime the runtime container is recreated, so the PLC stops and loses its program. On a native install the re-run rewrites the `plugins.conf` line as disabled. Nothing changed, but the user has to upload the program again. The PC installer already skips a same-version install; the device install should do the same.

## What Changes

- `install-stock.sh` records what it installed (canworks version, protocols, editor hook, the runtime it was built for) in `<prefix>/lib/install-stamp` at the end of a successful install.
- A re-run whose version, protocols and runtime match that record, with the plugin library and its runtime entries still in place, skips the build, the tools install, `plugins.conf` and the runtime container. It says so in one line, and the PLC keeps running with its program.
- The cheap host steps still run on a skip: the J1939 kernel module, discovery and the remote link. So adding `--with-link` to a same-version run still sets the link up without touching the PLC.
- New option `--force` (passed through by `install-runtime.sh` and `install-runtime.ps1`) installs everything again as today.
- A checkout whose version is `unknown` or ends in `-dirty` is never skipped.
- Docs: `docs/install-stock.md` and the README describe the skip and `--force`.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `canopen-stock-install`: a same-version re-run changes nothing on the device; `--force` reinstalls.
- `canopen-docker-install`: a re-run rebuilds and recreates the runtime container only when the version, protocols or runtime image changed.

## Impact

- `scripts/install-stock.sh` (stamp, skip check, `--force`), `scripts/install-runtime.sh` and `install-runtime.ps1` (help text for `--force`; it already passes options through).
- Devices page install job: a skipped run ends with fewer step lines; the job view must still show it as done.
- Tests: `test/pc-tools/test_install_scripts.py` (option pass-through), `test/stock/run.sh` and `test/docker/test_install_docker.py` (second run skips, `--force` rebuilds).
- Not in scope: `install-bridge.sh` (the bridge has its own update path) and the PC installers (they already skip).
