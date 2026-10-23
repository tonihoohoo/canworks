## 1. Probe

- [ ] 1.1 `device-probe.sh`: remove the OpenPLC runtime section (service file, bootloader spec, Docker containers, HTTPS check, `sudo -n` reads) and the `runtime` key; drop `CANWORKS_PROBE_DOCKER`
- [ ] 1.2 `device-probe.sh`: list a folder under `/etc/canworks-bridge/` as an instance only when its name matches `^[A-Za-z0-9_-]+$` and it holds `canworks.json`
- [ ] 1.3 Probe tests on fake roots: nothing installed (no `docker` or `sudo` run), two instances plus `.bak-…` and `.trimmed` copies, install job log; remove the native and Docker-mode runtime fixtures; shellcheck clean

## 2. Plan, service and server

- [ ] 2.1 `plan.py`: remove the runtime row, `roles`/`ROLES`, `install_openplc_bridge`, `switch_runtime`, `runtime_off_pin`, `untested_runtime`, `switch_text`, `DOCKER_STOP`, `OPENPLC_INSTALLER`; treat `openplc_modbus` like `bridge` (Install and start / Update / Start this project's bridge); no config and no bridge gives **Install the bridge X** with the hint line
- [ ] 2.2 Move `TESTED_RUNTIME` and `PINNED_BOOTLOADER` to `localruntime.py`; point the pin test and other users there
- [ ] 2.3 `service.view`: replace `tags` with `summary` (This project's bridge / `NAME running · N stopped` / `N bridges stopped` / empty); keep `mine` from the own runtime host or instance
- [ ] 2.4 `server.py`: `_device_projects` returns only the open project's own host; remove the `/api/devices/runtime_user` route
- [ ] 2.5 `jobs.py`: remove the runtime actions, their script options and the "runtime install failed" hint

## 3. Page

- [ ] 3.1 `devices.js`: card shows the summary line instead of tags; remove the roles fieldset, the first-user dialog, runtime job texts and labels; after-job text for the bridge only
- [ ] 3.2 Devices intro (`devices.js`) and start page entries (`index.html`): "Install the Modbus bridge, its remote link and local network discovery on a Linux device over SSH…", no OpenPLC Runtime, no "canworks" as a part
- [ ] 3.3 Page tests: four rows, no role picker, summary line, no runtime confirmation texts

## 4. Install scripts

- [ ] 4.1 `install-bridge.sh`: remove `--with-openplc`, `--pinned-runtime`, `have_runtime`, upstream installer run, wait and image switch, their step counting and exit hint; help text
- [ ] 4.2 `install-bridge.ps1`: remove `-WithOpenplc` and `-PinnedRuntime`
- [ ] 4.3 `test/pc-tools/test_install_scripts.py`: drop the runtime install tests; add an unknown-option test for `--with-openplc` that changes nothing

## 5. Docs and release

- [ ] 5.1 `docs/devices.md`: canworks parts only, summary line, no roles, no runtime actions or first user; one line pointing to upstream's installer for the OpenPLC Runtime
- [ ] 5.2 `docs/modbus-bridge.md`, `docs/install-pc.md`, `docs/configurator.md`, `docs/development.md`: remove `--with-openplc`/`--pinned-runtime`; one line to upstream's installer
- [ ] 5.3 `README.md`: the `--with-openplc` line and the Devices line; `test_readme.py` labels ("Switch runtime to v4.3.1", "Runtime of line3") updated
- [ ] 5.4 PC tools minor version bump and release notes

## 6. Hardware (Pi, through Remote Control)

- [ ] 6.1 Devices from the Mac with no config: the Pi's card reads "<instance> running" with no backup or Runtime of entries; four rows; up to date
- [ ] 6.2 Same from Windows
- [ ] 6.3 Pi's OpenPLC Runtime and its project unchanged after **Check again** (probe ran no `docker`/`sudo`)
