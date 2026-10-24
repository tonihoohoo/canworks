## 1. Probe

- [x] 1.1 `device-probe.sh`: remove the OpenPLC runtime section (service file, bootloader spec, Docker containers, HTTPS check, `sudo -n` reads) and the `runtime` key; drop `CANWORKS_PROBE_DOCKER`
- [x] 1.2 `device-probe.sh`: list a folder under `/etc/canworks-bridge/` as an instance only when its name matches `^[A-Za-z0-9_-]+$` and it holds `canworks.json`
- [x] 1.3 Probe tests on fake roots: nothing installed (no `docker` or `sudo` run), two instances plus `.bak-…` and `.trimmed` copies, install job log; remove the native and Docker-mode runtime fixtures; shellcheck clean

## 2. Plan, service and server

- [x] 2.1 `plan.py`: remove the runtime row, `roles`/`ROLES`, `install_openplc_bridge`, `switch_runtime`, `runtime_off_pin`, `untested_runtime`, `switch_text`, `DOCKER_STOP`, `OPENPLC_INSTALLER`; treat `openplc_modbus` like `bridge` (Install and start / Update / Start this project's bridge); no config and no bridge gives **Install the bridge X** with the hint line
- [x] 2.2 Move `TESTED_RUNTIME` and `PINNED_BOOTLOADER` to `localruntime.py`; point the pin test and other users there
- [x] 2.3 `service.view`: replace `tags` with `summary` (This project's bridge / `NAME running · N stopped` / `N bridges stopped` / empty); keep `mine` from the own runtime host or instance
- [x] 2.4 `server.py`: `_device_projects` returns only the open project's own host; remove the `/api/devices/runtime_user` route
- [x] 2.5 `jobs.py`: remove the runtime actions, their script options and the "runtime install failed" hint

## 3. Page

- [x] 3.1 `devices.js`: card shows the summary line instead of tags; remove the roles fieldset, the first-user dialog, runtime job texts and labels; after-job text for the bridge only
- [x] 3.2 Devices intro (`devices.js`) and start page entries (`index.html`): "Install the Modbus bridge, its remote link and local network discovery on a Linux device over SSH…", no OpenPLC Runtime, no "canworks" as a part
- [x] 3.3 Page tests: four rows, no role picker, summary line, no runtime confirmation texts

## 4. Install scripts

- [x] 4.1 `install-bridge.sh`: remove `--with-openplc`, `--pinned-runtime`, `have_runtime`, upstream installer run, wait and image switch, their step counting and exit hint; help text
- [x] 4.2 `install-bridge.ps1`: remove `-WithOpenplc` and `-PinnedRuntime`
- [x] 4.3 `test/pc-tools/test_install_scripts.py`: drop the runtime install tests; add an unknown-option test for `--with-openplc` that changes nothing

## 5. Docs and release

- [x] 5.1 `docs/devices.md`: canworks parts only, summary line, no roles, no runtime actions or first user; one line pointing to upstream's installer for the OpenPLC Runtime
- [x] 5.2 `docs/modbus-bridge.md`, `docs/install-pc.md`, `docs/configurator.md`, `docs/development.md`: remove `--with-openplc`/`--pinned-runtime`; one line to upstream's installer
- [x] 5.3 `README.md`: the `--with-openplc` line and the Devices line; `test_readme.py` labels ("Switch runtime to v4.3.1", "Runtime of line3") updated
- [x] 5.4 PC tools minor version bump and release notes

## 6. Hardware (Pi, through Remote Control)

- [x] 6.1 Devices from the Mac with no config: the Pi's card reads "<instance> running" with no backup or Runtime of entries; four rows; up to date
  - Passed 2026-10-24 with PC tools 0.131.1 on the Mac: the device has its one instance and eight hand-made backup folders; the probe and the card list only the instance ("<instance> running"), no `runtime` key, no runtime row. The rows are bridge, remote link, discovery and CAN, plus the remote CAN adapter row added since by `add-devices-adapter-server`. The main action was **Update 0.128.3 → 0.131.1** because the device's bridge is older than the release, not "Up to date"; nothing was clicked.
- [ ] 6.2 Same from Windows
- [x] 6.3 Pi's OpenPLC Runtime and its project unchanged after **Check again** (probe ran no `docker`/`sudo`)
  - Passed 2026-10-24: the runtime and bootloader containers, their images and the bridge instance were the same before and after the probe and the page's check (only the uptime moved). The probe's only `sudo` call is `sudo -n true` to find the sudo mode; it reads nothing of the runtime.
