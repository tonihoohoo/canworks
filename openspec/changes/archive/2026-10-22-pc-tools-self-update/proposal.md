## Why

The PC tools update only when the user runs the one-line installer again in a terminal. Nothing in the tools says that a newer release exists, and releases come often. Users stay on old versions without knowing, and updating means finding the install line again (on Windows, from a PowerShell outside any app sandbox).

## What Changes

- **Update check in the configurator.** At most once a day, in the background, the configurator asks GitHub which release is newest (the `releases/latest` redirect the installers already use: no API, no token). A newer version shows as a small badge next to the version, with a "What's new" link to the release and an **Update** button. No dialog, and the badge can be dismissed for that version. On by default, with a "Check for updates" switch and "Check now" in Settings, and `CANWORKS_NO_UPDATE_CHECK=1` to turn it off (CI sets it).
- **Update button.** The configurator starts a small updater outside the tools' own environment and stops. The updater waits for it to end, checks on Windows that nothing else still uses the tools' files, runs the same `uv tool install` as the one-line installer, refreshes the app shortcut and starts the new configurator on the same port. The open tab reloads by itself into the new version. A failed update installs the old version again and says why.
- **Update when I quit.** While there are unsaved changes, an online connection, a trace or a device job, Update is refused with the reason, and the user can choose "Update when I quit" instead: the same steps run after Quit or after the last tab closes.
- **`canworks-config --update`.** The same updater from a terminal (headless Linux, scripts), printing its progress.
- **Only where it can work.** The button is offered only for a uv tool install (uv's receipt file in the tools' environment) with uv found and outside another app's sandbox folder on Windows. Otherwise the badge shows the one-line install command to copy.
- **No downloaded script runs.** The updater calls uv directly; it never downloads and runs `install-pc.sh` or `install-pc.ps1` (the pattern the Windows installer change removed). A CI test keeps the updater's uv arguments the same as the installers'.
- **Docs.** README PC tools section and `docs/install-pc.md` (update from the configurator, the check and how to turn it off). The company-proxy note names `UV_SYSTEM_CERTS=1`, which current uv uses in place of the deprecated `UV_NATIVE_TLS`.
- PC tools minor version bump.

## Capabilities

### New Capabilities
- `pc-tools-self-update`: the update check, the Update button, update when quitting, `canworks-config --update`, and the updater's behaviour on Windows, macOS and Linux.

### Modified Capabilities
- `canopen-pc-install`: "Update and uninstall" also allows updating from the configurator and names the company-proxy setting.

## Impact

- New `tools/deploy/canworks/configurator/update.py` (check, cache, guard, hand-off, install detection) and `tools/deploy/canworks/updater.py` (standard library only, runs outside the tools' environment).
- `configurator/server.py` (routes `/api/update/*`, the resume code at start, the check thread, update-on-stop), `configurator/start.py` (`--update`, `--resume`), `static/` (badge, message bars, Settings switch).
- `scripts/install-pc.sh` / `.ps1` comments (proxy variable), README.md, docs/install-pc.md.
- Tests: unit tests for check, detection, guard and argument parity; an end-to-end update in the PC tools workflow on Windows, macOS and Linux (dispatched on the branch, since that workflow does not run on pull requests).
- Desktop checks: Windows from the Start menu shortcut, the macOS app, a Linux desktop.
