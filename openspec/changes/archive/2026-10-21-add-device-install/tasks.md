## 1. Device scripts

- [x] 1.1 `install-stock.sh`, `install-bridge.sh`: write `<prefix>/VERSION`, remove it on uninstall
- [x] 1.2 Step lines `::canworks-step N/M text` in `install-runtime.sh`, `install-stock.sh`, `install-bridge.sh` (macOS bash 3.2 rules for the PC-side paths)
- [x] 1.3 `install-runtime.sh --with-openplc`: upstream installer when no runtime, wait for its HTTPS port, then the plugin; passes over `--ssh`
- [x] 1.4 `canworks/devices/device-probe.sh` (POSIX sh, read-only, JSON); release asset and package data
- [x] 1.5 Script tests: VERSION files, step lines, `--with-openplc` with a stub upstream installer, probe on fake roots (none, native, Docker layout, bridge with two instances); shellcheck

## 2. PC side (`canworks/devices/`)

- [x] 2.1 `paramiko` dependency (floor without known vulnerabilities), installer checks
- [x] 2.2 `devices.json` store per project folder (no secrets); own `known_hosts`; `canworks_ed25519` key creation and `authorized_keys` setup
- [x] 2.3 SSH layer: agent, default keys, `~/.ssh/config` aliases, password dialog flow, host key trust/changed/forget
- [x] 2.4 Probe runner and `plan(probe, project, latest, pc_version)` (main action, row actions, disabled reasons, newest release lookup with device-side fallback, PC-tools-older note)
- [x] 2.5 Install job: sudo -S once, SFTP of the bridge config folder, `systemd-run` + lock + log, follow from offset, resume from probe, stop, error sentences
- [x] 2.6 First runtime user after `--with-openplc` (runtime API, password not kept)
- [x] 2.7 Uninstall and Remove everything; Remove device
- [x] 2.8 Routes `/api/devices/*` in `server.py`; job in the status bar jobs list

## 3. Page

- [x] 3.1 Workspace switch Configure | Commission | Devices; device list with Add device and discovered devices
- [x] 3.2 Device page: header line, part rows per target (muted parts), main action and folded options, disabled reasons, Check again
- [x] 3.3 Dialogs: host key, password, key login offer, confirmation with sudo password, first runtime user
- [x] 3.4 Job view: steps with times, elapsed and typical time, folded log, Stop, failure view; resume on reopen
- [x] 3.5 Entry points: Online access host state + Open in Devices, bridge page Install on device…, connect panel Install canworks on a device…, status bar Show; CODESYS one-line note
- [x] 3.6 Keyboard and screen reader pass as on the other pages

## 4. Checks

- [x] 4.1 Unit tests: plan from probe fixtures (each table row), store has no secrets
- [x] 4.2 SSH tests against an in-process paramiko server: trust, changed key, password and key login, key setup, sudo on stdin, job start/follow/reconnect/stop, no password in logs
- [x] 4.3 Page tests: rows per target, actions, confirmation texts, job progress and resume, entry points
- [x] 4.4 CI: tests in the existing tools job with path selection; CI time compared with the baseline

## 5. Docs

- [x] 5.1 `docs/devices.md` (new): adding a device, keys and host keys, what the probe reads, actions, jobs, security
- [x] 5.2 README (PC tools and install sections), `docs/configurator.md` (header, entry points), `docs/install-stock.md` (`--with-openplc`, VERSION, step lines), `docs/modbus-bridge.md` (install from the configurator)
- [x] 5.3 PC tools minor version bump

## 6. Hardware (Pi from the Mac and the Windows PC)

- [x] 6.1 Windows: add the Pi (host key dialog, password, key login), probe matches the Pi's state (2026-10-21 on 0.98.1: host key fingerprint matched, nothing sent before Trust and connect; key login already set up, so no password asked; 0.98.0 saw the runtime wrong, fixed in fix-probe-managed-docker; slcan bit rate fixed after)
- [x] 6.2 Windows: update or rebuild the plugin on the managed Docker runtime; close the configurator mid-build and reopen: job resumed, finished; next upload switches canworks on (2026-10-21: install 0.98.1 took 2 min 06 s, picked up after the configurator was stopped mid-build; canworks-deploy upload enabled the plugin, nodes operational; Online access refresh and bridge row version fixed after)
- [x] 6.3 Mac: bridge project, Install and start this project's bridge; bridge answers on its Modbus port with the project's config; Uninstall the bridge (2026-10-21 on 0.98.3 after fix-bridge-beside-plugin: install 1 min 26 s, Modbus FC4 answered with live simulated values, config sha256 matched, uninstall 4 s left the plugin, its can-j1939 boot entry and VERSION; PLC untouched; the Remote link option would have repointed the PLC's link, fixed after)
- [x] 6.4 Fresh OS on a spare SD card (when Toni has one): Install OpenPLC Runtime and canworks, first user, upload works (2026-10-21 on 0.98.3, the Pi wiped to fresh instead: runtime, Docker and canworks removed; Install OpenPLC Runtime and canworks took 6 min 34 s with upstream's installer bringing Docker and runtime v4.3.1; first-user dialog created the user; canworks-deploy upload switched canworks on, nodes operational; the plugin row showed no on/off before the upload)
- [x] 6.5 Clean PLC start afterwards (2026-10-21: PLC running, nodes operational)
