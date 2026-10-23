## Why

The adapter server (`canworks-diag adapter-serve`, canopen-remote-adapter) lets a PC commission through the CAN adapter of a Linux device on the network. Turning it on takes several steps. You install the PC tools on the device, run `sudo canworks-diag adapter-serve --install-service` in a terminal, copy the token it prints once, and type it into the PC's connect panel. The configurator's Devices page already reaches the device over SSH and runs install jobs there, but it cannot turn the adapter server on. It cannot show the server either.

Toni (2026-10-23, after the explore): "explore enable remote can adapter from can configurator devices". Answers to the explore's questions:
- Read-only by default, selectable while connecting, and the selection works the same as for a USB adapter. The connect panel's **Allow changes** box, unticked by default, already does this for both kinds of adapter. So the server the Devices page turns on allows changes, and each PC still picks for its own session.
- Installing the PC tools on a device without the bridge is fine.

## What Changes

- **A Remote CAN adapter row on the device page.** It sits under **CAN interfaces** and is shown with and without a config open, also on a device without the bridge. It shows each adapter server on the device:
  - its interface, bit rate and port;
  - whether it runs and whether changes are allowed;
  - how many PCs are connected, for example `can0 · 500 kbit/s · running · 1 PC connected`.

  The row has **Turn on…** (or **Add…** for another interface), **Change…**, **Connect from this PC** and **Turn off…**, each run as an install job.
- **Turn on… dialog.** One screen with these fields:
  - **Interface**: the device's CAN interfaces and serial adapters.
  - **Bit rate**: required and never guessed. It is prefilled from this project's bridge on that interface (and then locked), else the interface's current rate when it is up, else the open config's network.
  - **Allow changes from PCs**: on by default. Turned off, the server refuses changes for every PC.
  - **Advertise on the local network**: on by default.
- **No token to copy.** The configurator makes the token on the PC, keeps it in `online.json` under that server (as **Adapter on another machine** does today), and uploads only its SCRAM verifier. The plain token never reaches the device or its world-readable job log.
  - A PC that has no token for a server it finds running gets **New token…**. It makes a new token, and every other PC must then enter it again.
  - **Copy token** shows the token to give to another PC.
- **Connect from this PC.** After the job, and on the row while the server runs, this opens the connect panel on **Adapter on another machine** with the host filled in and the token kept, so one press of **Connect** runs the bit rate check. With no config open, it opens **Commission a CANopen device** first. Read-only and **Allow changes** work as for a USB adapter.
- **Sharing the interface with the bridge.** A SocketCAN interface that a bridge instance on the device uses can be served. The bit rate is locked to the bridge's, and the dialog says in one line that the bridge is the master there. A PC with the config should connect through the bridge, and a PC's changes then need force, as with any other master. A serial (slcan) adapter cannot be shared: the dialog refuses it while a bridge instance or another server uses that port.
- **`scripts/install-adapter.sh`** is a new release script for these jobs.
  - If `/opt/canworks/venv` has no `canworks-diag`, it makes that venv and installs the PC tools with their locked dependencies. It needs no Lely and no build.
  - It then runs `canworks-diag adapter-serve --install-service` for the SSH user with the uploaded verifier.
  - `--uninstall --interface IF` removes one server.
  - It puts the user in `dialout` for a serial adapter.
- **`adapter-serve` options for these jobs.** `--service-user USER` runs the service as USER when root installs it (today the user must come from `sudo`). `--token-verifier-file FILE` stores a verifier made elsewhere.
- **The probe reads adapter servers.** It reads `/etc/systemd/system/canworks-adapter-*.service`: the unit, whether it is active, and its adapter, bit rate, port and `--allow-changes` from `ExecStart`. It also reads the connected PCs from the service user's status file when the SSH user can read it.
- **Remove everything** also removes the adapter servers.
- README, `docs/pc-adapter.md` and `docs/configurator.md` say how to turn the adapter server on from Devices.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `device-install`: the device probe reads adapter servers. The device page gets the **Remote CAN adapter** row with its switch, token handling, connect shortcut and shared-interface rules. **Remove everything** removes adapter servers too.
- `canopen-remote-adapter`: `--service-user` and `--token-verifier-file` for installs made by root, and `install-adapter.sh`.

## Impact

- `tools/deploy/canworks/devices/` (`device-probe.sh`, `plan.py`, `jobs.py`, `service.py`), `configurator/server.py` (adapter actions, token make and upload), `configurator/static/devices.js` (row, dialog, done notice), `connection.js` (open the panel with a host).
- `tools/deploy/canworks/localbus/serve.py` (two options), `scripts/install-adapter.sh` (new, in the release assets and shellcheck), tests for the probe, plan, jobs, script and page.
- Docs: README, `docs/pc-adapter.md`, `docs/configurator.md`.
- Builds on devices-canworks-only (#283). Not in this change: carrying the adapter server over the remote link (iroh), so that it works from outside the local network.
