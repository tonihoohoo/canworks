# Proposal

## Why

Putting canworks on a device is still a terminal job. The runtime plugin and the Modbus bridge each have a one-line installer (`install-runtime.sh`, `install-bridge.sh`, also `--ssh` from a PC), but the user has to know which line, which options, whether the device already has an OpenPLC runtime (and which kind), whether the plugin is current, and what the install will do to a running PLC. Common situations are invisible until something fails:

- The device has no OpenPLC runtime yet, so the plugin install refuses, and the runtime comes from a different installer.
- The runtime moved to a new version, so the plugin is off ("built for v4.2.4 but the runtime is v4.2.5") until someone re-runs the installer.
- The plugin is older than the newest release, and nothing says so.
- A Docker-mode install recreates the runtime container: the PLC stops and comes back without a program.
- A Raspberry Pi build takes many minutes; a laptop going to sleep over `ssh -t` kills it half way.
- On Windows the PowerShell wrapper is where the Defender and sandbox path problems came from.

The configurator already knows the project's target, the device's host (Online access), the PC tools' version and the devices on the network (discovery). It is the natural place to install and update, with UX as priority 1.

## What Changes

- **Devices workspace** in the configurator (next to Configure and Commission). The list holds the project's devices, remembered per project folder, with **Add device…** and the devices discovery finds. A device page shows one row per part (OpenPLC runtime, canworks plugin, Modbus bridge, remote link, CAN interfaces): what the device has, what this project needs, and one action.
- **SSH from the configurator** (Python, `paramiko`), the same on Windows, macOS and Linux: host key shown and confirmed on first contact and checked after, the user's agent and keys used, a password asked only when no key works, and **Use key login from now on** to add this PC's own canworks key. Passwords (SSH and sudo) are never stored.
- **Probe** (read-only, one command, JSON): system, architecture, disk, memory, internet access to the release host, sudo without password, the OpenPLC runtime (none, native, managed Docker; version; PLC state), the plugin (version, the runtime version it was built for, enabled or waiting for an upload), the bridge (version, instances), the remote link and discovery, CAN interfaces and serial adapters.
- **One main action per device**, worded by state: **Install canworks 0.98.0**, **Update 0.93.4 → 0.98.0**, **Rebuild for runtime v4.2.5**, **Install OpenPLC Runtime and canworks**, or nothing when current. The version installed is the newest release (pinned with `--version` when the job starts). When the PC tools are older than the device's canworks, the page says to update them.
- **OpenPLC runtime install**: a device without a runtime gets upstream's installer (managed Docker), named with its URL in the confirmation, then the plugin. After it, the configurator creates the runtime's first user with a name and password the user types (not stored).
- **Bridge projects**: **Install and start this project's bridge** installs the bridge and copies the saved config as an instance named after the project folder (`--instance/--config`).
- **Install job on the device**: runs detached under `systemd-run`, logs to a file on the device and holds a lock, so a closed laptop, a dropped connection or a closed configurator does not stop it. The page shows the steps, elapsed time, the log (folded) and **Stop**; the status bar lists it like other jobs; reopening the page picks it up again. Only destructive effects are confirmed (the Docker-mode PLC stop and empty program; running bridges restarting).
- **After the job**: probe again and say the next step (OpenPLC: canworks switches on with the next upload; bridge: the bridge runs this config). Online access's runtime host is set to the device.
- **Uninstall** per part, with **Remove everything** as an option.
- **Install scripts**: `<prefix>/VERSION` written by `install-stock.sh` and `install-bridge.sh`; machine-readable step lines (`::canworks-step N/M text`); `install-runtime.sh --with-openplc` installs upstream's runtime when none is found, so the terminal route can do the same; `device-probe.sh`, shipped with the PC tools and in the release, prints the probe JSON.
- **Entry points**: Online access's runtime host shows the device's state with **Open in Devices**; the Modbus bridge page shows where the bridge runs with **Install on device…**; the Commission connect panel, when it finds no runtime, offers **Install canworks on a device…**.
- README, `docs/devices.md` (new), `docs/configurator.md`, `docs/install-stock.md`, `docs/modbus-bridge.md`.
- PC tools minor version bump (0.98.0); new dependency `paramiko`.

## Non-goals

- Uploading the PLC program from the configurator (its own explore: the program comes from the editor's build), and sending a new config to a running bridge from the Devices page.
- The local sim runtime, simulated ECUs, Node-RED, the remote CAN adapter and CODESYS (later slices or dropped).
- Devices without internet access (the install still fetches the release, build packages and images on the device).
- CAN HAT overlays and other boot configuration (shown by the probe, documented, not changed).
- Non-Linux devices; devices without systemd.

## Capabilities

### New Capabilities

- `device-install`: the Devices workspace, SSH connection and host keys, the probe, the actions, the install job, OpenPLC runtime first user, uninstall, security rules.

### Modified Capabilities

- `canopen-stock-install`: ADDED version file, step lines, `--with-openplc`, the probe script.
- `modbus-bridge`: ADDED version file and step lines for the bridge install.
- `canopen-configurator`: ADDED Devices workspace in the header and the entry points (Online access host, bridge page, connect panel).
- `canopen-pc-install`: ADDED `paramiko` as a runtime dependency.
- `canopen-ci`: ADDED device install tests against a local SSH server in the existing tools job.

## Impact

- New: `tools/deploy/canworks/devices/` (ssh, probe, jobs, actions), `configurator/static/devices.js`, `docs/devices.md`, tests.
- Changed: `configurator/server.py` (routes `/api/devices/*`), `index.html`, `app.js`/`connection.js`/`bridge.js` (entry points), `scripts/install-stock.sh`, `install-runtime.sh`, `install-bridge.sh`, `pyproject.toml`, README and docs.
- Hardware: the Pi from both the Mac and the Windows PC (fresh install with no runtime, update, rebuild after a runtime change, bridge with config, lost connection mid-build, uninstall), then a clean PLC start.
