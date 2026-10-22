# Proposal

## Why

Toni, on the Devices page: "what about others? everythin listed here can be installed and remote link enabled/disabled etc?"

Today the device page lists five parts, but only the plugin and the bridge have their own actions:

- **Remote link** and **Found on the local network** (the Avahi advertisement) are only checkboxes under **Options** while the plugin or the bridge installs. Once a device is set up there is no way to turn either on or off from the page; only **Uninstall** of the part that installed them, or **Remove everything**, takes them away.
- The remote link row shows "not installed", "running" or "stopped" with no action, and discovery has no row at all.
- `scripts/install-link.sh`, which does the work, only runs from a checkout (it pip-installs the PC tools package from the same tree), so a device job cannot call it on its own as it calls `install-runtime.sh` and `install-bridge.sh` from the release.
- Open bug: `install-link.sh --without-link` writes the advertisement without the link ID, so turning discovery on again after a link was installed drops the link ID from discovery.

The OpenPLC Runtime row stays as it is (it installs together with canworks, and is never removed from the configurator), and the CAN interfaces row stays read-only (the plugin or the bridge sets the interfaces up from the config).

## What Changes

- **Device page rows**: the **Remote link** row gets **Turn on…** (not installed) or **Turn off…** (installed), and a stopped link gets **Start**. A new row **Found on the local network** shows whether the advertisement is installed, with **Turn on…** / **Turn off…**. Both are run as install jobs (step lines, log, sudo once), with and without a config open. They are offered only when the plugin or the bridge is installed (the link needs a config to serve).
- **Which config the link serves**: the plugin's (`/opt/canworks/lib/canworks.json`, runtime port 8443) when the plugin is installed; otherwise the bridge instance of the open bridge project, or the only bridge instance on the device; with several instances and no config saying which, the dialog asks which one. The row says what it serves ("serves the PLC" / "serves the bridge packer").
- **Turn off** keeps the link's key and paired PCs (`/etc/canworks-link`), so turning it on again keeps the pairings; **Remove everything** still purges them. Turning the link off leaves the advertisement in place (without the link ID) when discovery is on.
- **`install-link.sh` release mode**: with `--version X` or when run outside a checkout, the link install downloads the `deploy-vX` tarball and runs its own copy (as `install-bridge.sh` does), so jobs fetch it from the release. New `--without-discovery` (the link without the advertisement), `--discovery-only` (the advertisement alone; `--without-link` stays as its old name), `--remove-discovery`, and `--keep-discovery` with `--uninstall`. The advertisement carries the link ID whenever the link is installed, whichever option wrote it (fixes the open bug).
- Job actions `link_on`, `link_off`, `link_start`, `discovery_on`, `discovery_off` in `devices/jobs.py`; `devices/plan.py` gives the two rows their action; the probe already reports the link state, the config it serves and the advertisement.
- README and `docs/devices.md`, `docs/remote-access.md` updated.

Not in this change: managing paired PCs from the Devices page (the link's own `canworks-link paired` command and the configurator's remote access page keep that job); internet access for the link (it follows the uploaded config's `diagnostics.remote_link.internet`, as today); CAN interface setup.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `device-install`: new requirement **Remote link and discovery switches** (rows, actions, which config the link serves, off keeps pairings).
- `canopen-stock-install`: new requirement **Link script on its own** (release mode, `--without-discovery`, `--discovery-only`, link ID kept in the advertisement).

## Impact

- `scripts/install-link.sh` (release mode, options, advertisement with the link ID); `test/pc-tools/test_install_scripts.py` and the script tests.
- `tools/deploy/canworks/devices/jobs.py` (new actions and their command lines), `plan.py` (rows' actions, served config), `service.py` (instance choice passed through), `configurator/server.py` `/api/devices/start` (instance for the link), `static/devices.js` (row buttons, discovery row, instance choice).
- Tests: `tests/test_devices*.py`, `tests/test_configurator_devices_page.py` (fake SSH device: turn the link off and on, discovery off and on).
- Docs: `docs/devices.md`, `docs/remote-access.md`, README, PC tools release notes; PC tools minor version bump.
- HW: on the bench Linux device, turn the link off and on from the page and see the paired PC still paired and the link ID back in discovery; discovery off and on; then a clean PLC start.
