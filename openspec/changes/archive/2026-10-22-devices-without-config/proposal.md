# Proposal

## Why

Toni: "should devices view be somewhere else than config? For example front page? One may want to install stuff without configuring can bus".

Today the Devices workspace (`device-install`) exists only inside an open config:

- the workspace switch is hidden on the start page, and the server refuses `/api/devices` without an open config (in Commission a device: "Commission a device has no devices; open a project or config folder");
- `devices.json` keeps a device list **per project folder**, so a device added in one project is missing from the next one, while the trusted host keys and the PC's SSH key are already PC-wide;
- what the page offers comes only from the project's target, so there is no way to say "install the OpenPLC Runtime and canworks here" or "install the bridge here" without first inventing a config.

The install scripts themselves need no config: `install-runtime.sh` installs the runtime and plugin, and `install-bridge.sh` installs the bridge without `--instance/--config`. Only starting a project's bridge needs a saved config.

The current page also names one board brand twice (empty-list hint, the "turn SSH on" tip). Toni: say "Linux device", never a board name.

Explore notes: `research/devices-placement-2026-10-22/` in the project files (sketch, screenshots of main today).

## What Changes

- **Start page**: a link **Install on a device** next to **Commission a device without a config**, and with an empty Recent a fourth starting choice "Set up a Linux device". Both open Devices with no config, the same way the Commission link opens Commission without one: the header shows "Devices · no config" and **Close** returns to the start page.
- **One device list per PC**: `devices.json` holds devices by `host[:port]`, not by project folder. Each device row says what it is to which project, derived from the PC's settings and the last probe (not stored): "Runtime of line3" (a project's Online access runtime host) and "Bridge of packer" (a bridge instance the probe lists, named after a Recent project folder). With a config open, that project's devices are listed first and the others are muted but usable. Clean cut (the project is not in real use): the old per-project lists are not read; bench devices are added again.
- **No config open**: the parts table has no "This project needs" column. A device with nothing of canworks on it shows **What should this device run?** with two choices, **OpenPLC PLC with canworks** and **Modbus bridge**; the main action follows the choice (**Install OpenPLC Runtime and canworks X** or **Install canworks X** when a runtime is there; **Install the bridge X**, no instance). A device that has the plugin or the bridge gets its main action from what is installed (Update, Rebuild, Up to date), with no choice shown. Uninstall, Remove everything, options and jobs work as with a config. After a no-config install there is no project to set a runtime host for, and a bridge install says that a config's own Devices page starts it with that config.
- **With a config open**: the page as today (needs column, one main action from the project's target, Start this project's bridge, runtime host set after an install, entry points from Online access, the connect panel and the Modbus bridge page), over the shared list.
- **Wording**: the Devices page and its docs say "Linux device"; no board brand. The SSH tip becomes "SSH is on in the device."
- README and `docs/devices.md` updated.

Not in this change: Node-RED install and the "This PC" local runtime panel (later slices of the install-targets explore); a Devices link inside Commission a device (the start page is one Close away).

## Capabilities

### Modified Capabilities

- `device-install`: Devices workspace (PC-wide list, project tags, no-config mode), One main action (role choice without a config), After the job (no-config ends).
- `canopen-configurator`: Choose what to edit (start page link and fourth starting choice), Devices in the header and from other pages (Devices without a config from the start page).

## Impact

- `tools/deploy/canworks/devices/store.py` (list by device, not project), `service.py` (keys by device), `plan.py` (target `None` and a chosen role).
- `tools/deploy/canworks/configurator/server.py` `_devices`: works with no session and in no-config mode; bridge start actions still need a saved config.
- `static/devices.js`, `shell.js`, `app.js` start page, `index.html`.
- Tests: `tests/test_devices*.py`, `tests/test_configurator_devices_page.py` (a no-config run), start page tests.
- Docs: `docs/devices.md`, README, PC tools release notes. PC tools minor version bump.
- HW: one install from the start page on the bench Linux device without a config.
