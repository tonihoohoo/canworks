## Why

The configurator's Devices page still installs, versions and switches the OpenPLC Runtime, a part canworks does not own. It shows an **OpenPLC Runtime** row on every device, even when the runtime isn't installed and nothing needs it. The device list also reads like a log. Each device says **Runtime of X** for every project folder that ever named it as its Online access host. It also says **Bridge of X** for every folder under `/etc/canworks-bridge/` that holds a `canworks.json`, so hand-made backups such as `line1.bak-271` and `line1.trimmed` count as bridges. The installer only accepts instance names made of letters, digits, `-` and `_`, so a name with a dot can never be a real instance. Finally, the page's intro still offers to install "canworks", which meant the removed plugin.

Toni (2026-10-23, after the Devices page explore):
- "1. ok, 2. ok": the probe skips folders that cannot be instances, and the card gets a short summary instead of the tag list;
- "3. and 4. hide and drop support for installing from configurator. i just want to control things that belong canworks": no OpenPLC row, no Node-RED row, and no OpenPLC Runtime install or switch.

## What Changes

- **Devices shows and controls canworks parts only.** The device page has four rows: **Modbus bridge**, **Remote link**, **Found on the local network** and **CAN interfaces**. The **OpenPLC Runtime** row is removed. No row is added for Node-RED or any other client program.
- **No OpenPLC Runtime install from canworks.**
  - These actions are removed: **Install OpenPLC Runtime and the bridge**, **Switch runtime to vP**, the runtime's first-user dialog and the `/api/devices/runtime_user` route.
  - With no config open, the **What should this device run?** picker is removed. A device without the bridge gets **Install the bridge X**.
  - An OpenPLC project gets the same bridge actions as any bridge project: **Install and start this project's bridge**, **Update A → X** and **Start this project's bridge**.
- **`install-bridge.sh` installs canworks only.** `--with-openplc` and `--pinned-runtime` are removed, along with `-WithOpenplc` and `-PinnedRuntime` in `install-bridge.ps1`. So is the "runtime install failed" job hint. Users install the OpenPLC Runtime with upstream's installer, as its own docs describe. This is a clean cut: nothing is in real use.
- **The probe reads canworks only.** `device-probe.sh` no longer looks for the OpenPLC runtime. Gone are the native unit, the bootloader spec, Docker containers, the HTTPS check and the `sudo -n` reads done for them. The `runtime` key leaves the JSON. Bridge instances are only folders under `/etc/canworks-bridge/` whose name the installer would accept (`^[A-Za-z0-9_-]+$`) and that hold a `canworks.json`. Backup folders are ignored.
- **A short device card.** In the device list, each device has one summary line instead of the tag list:
  - **This project's bridge** when the open project's instance is on it;
  - otherwise the running instances by name, plus "N stopped" for the others (for example `line1 running · 1 stopped`);
  - or the page's status ("Nothing installed yet", "Update …").

  **Runtime of …** tags are dropped. The open project's devices are still listed first.
- **Texts.** The Devices intro, the start page's **Install on a device** and **Set up a Linux device**, the docs and the README describe installing the Modbus bridge, its remote link and local network discovery. They don't mention installing the OpenPLC Runtime or "canworks" as a separate part.
- The pinned runtime version (`TESTED_RUNTIME`, `PINNED_BOOTLOADER`) moves from `devices/plan.py` to `localruntime.py`, the only user left. The pin test is unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `device-install`: probe without the runtime; bridge instances by installer name; one main action without runtime install, switch or role picker; confirmations, job hints and after-job text without the runtime; uninstall wording; the device list's summary line instead of Runtime of/Bridge of tags; four rows. Removes the runtime first-user, tested runtime version, runtime install version source and OpenPLC project requirements.
- `modbus-bridge`: removes "OpenPLC runtime installed with the bridge" (`--with-openplc`); the locked dependencies requirement no longer names it.
- `canopen-ci`: the device install test scenario no longer expects **Switch runtime**.

## Impact

- `tools/deploy/canworks/devices/` (`device-probe.sh`, `plan.py`, `service.py`, `jobs.py`), `configurator/server.py` (`_device_projects`, `runtime_user` route), `configurator/static/devices.js` and `index.html`, `localruntime.py`.
- `scripts/install-bridge.sh` and `install-bridge.ps1`, and their tests in `test/pc-tools/test_install_scripts.py`.
- Tests: `test_devices.py`, `test_devices_ssh.py`, `test_configurator_devices_page.py`, and the probe fake roots.
- Docs: `docs/devices.md`, `docs/modbus-bridge.md`, `docs/install-pc.md`, `docs/configurator.md`, `docs/development.md` and `README.md` (the `--with-openplc` line and the Devices line). `test_readme.py` labels such as "Switch runtime to v4.3.1" and "Runtime of line3" change with them.
- Bench: the test device keeps its OpenPLC Runtime as it is. Backup folders under `/etc/canworks-bridge/` no longer show. Deleting them is a separate step that needs Toni's go.
- PC tools minor version bump.
