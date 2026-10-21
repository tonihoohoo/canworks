## 1. Device scripts

- [ ] 1.1 `install-stock.sh`, `install-bridge.sh`: write `<prefix>/VERSION`, remove it on uninstall
- [ ] 1.2 Step lines `::canworks-step N/M text` in `install-runtime.sh`, `install-stock.sh`, `install-bridge.sh` (macOS bash 3.2 rules for the PC-side paths)
- [ ] 1.3 `install-runtime.sh --with-openplc`: upstream installer when no runtime, wait for its HTTPS port, then the plugin; passes over `--ssh`
- [ ] 1.4 `scripts/device-probe.sh` (POSIX sh, read-only, JSON); release asset and package data
- [ ] 1.5 Script tests: VERSION files, step lines, `--with-openplc` with a stub upstream installer, probe on fake roots (none, native, Docker layout, bridge with two instances); shellcheck

## 2. PC side (`canworks/devices/`)

- [ ] 2.1 `paramiko` dependency (floor without known vulnerabilities), installer checks
- [ ] 2.2 `devices.json` store per project folder (no secrets); own `known_hosts`; `canworks_ed25519` key creation and `authorized_keys` setup
- [ ] 2.3 SSH layer: agent, default keys, `~/.ssh/config` aliases, password dialog flow, host key trust/changed/forget
- [ ] 2.4 Probe runner and `plan(probe, project, pc_version)` (main action, row actions, disabled reasons, release of X or newest)
- [ ] 2.5 Install job: sudo -S once, SFTP of the bridge config folder, `systemd-run` + lock + log, follow from offset, resume from probe, stop, error sentences
- [ ] 2.6 First runtime user after `--with-openplc` (runtime API, password not kept)
- [ ] 2.7 Uninstall and Remove everything; Remove device
- [ ] 2.8 Routes `/api/devices/*` in `server.py`; job in the status bar jobs list

## 3. Page

- [ ] 3.1 Workspace switch Configure | Commission | Devices; device list with Add device and discovered devices
- [ ] 3.2 Device page: header line, part rows per target (muted parts), main action and folded options, disabled reasons, Check again
- [ ] 3.3 Dialogs: host key, password, key login offer, confirmation with sudo password, first runtime user
- [ ] 3.4 Job view: steps with times, elapsed and typical time, folded log, Stop, failure view; resume on reopen
- [ ] 3.5 Entry points: Online access host state + Open in Devices, bridge page Install on device…, connect panel Install canworks on a device…, status bar Show; CODESYS one-line note
- [ ] 3.6 Keyboard and screen reader pass as on the other pages

## 4. Checks

- [ ] 4.1 Unit tests: plan from probe fixtures (each table row), store has no secrets
- [ ] 4.2 SSH tests against an in-process paramiko server: trust, changed key, password and key login, key setup, sudo on stdin, job start/follow/reconnect/stop, no password in logs
- [ ] 4.3 Page tests: rows per target, actions, confirmation texts, job progress and resume, entry points
- [ ] 4.4 CI: tests in the existing tools job with path selection; CI time compared with the baseline

## 5. Docs

- [ ] 5.1 `docs/devices.md` (new): adding a device, keys and host keys, what the probe reads, actions, jobs, security
- [ ] 5.2 README (PC tools and install sections), `docs/configurator.md` (header, entry points), `docs/install-stock.md` (`--with-openplc`, VERSION, step lines), `docs/modbus-bridge.md` (install from the configurator)
- [ ] 5.3 PC tools minor version bump

## 6. Hardware (Pi from the Mac and the Windows PC)

- [ ] 6.1 Windows: add the Pi (host key dialog, password, key login), probe matches the Pi's state
- [ ] 6.2 Windows: update or rebuild the plugin on the managed Docker runtime; close the configurator mid-build and reopen: job resumed, finished; next upload switches canworks on
- [ ] 6.3 Mac: bridge project, Install and start this project's bridge; bridge answers on its Modbus port with the project's config; Uninstall the bridge
- [ ] 6.4 Fresh OS on a spare SD card (when Toni has one): Install OpenPLC Runtime and canworks, first user, upload works
- [ ] 6.5 Clean PLC start afterwards
