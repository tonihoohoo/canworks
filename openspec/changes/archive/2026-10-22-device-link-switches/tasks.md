## 1. Link script

- [x] 1.1 `scripts/install-link.sh` release mode: `--version X`, or outside a checkout, downloads the `deploy-vX` tarball and runs its own `install-link.sh` with the same options (as `install-bridge.sh` does); `--dry-run` prints the download
- [x] 1.2 `--without-discovery` (link only, no Avahi file; an existing one is removed), `--discovery-only` (alias of `--without-link`), `--remove-discovery`, `--uninstall --keep-discovery`
- [x] 1.3 The Avahi file carries the link ID whenever `/etc/canworks-link` has a key and the link service is installed, whichever option wrote it; turning the link off rewrites it without the ID
- [x] 1.4 Script tests (`test/link/install_test.sh`, now run by `test/pc-tools/test_install_scripts.py`; shellcheck covers `install-link.sh`): release mode dry run, each option, link ID kept after `--discovery-only` on a device with the link

## 2. Jobs and plan

- [x] 2.1 `devices/jobs.py`: actions `link_on` (`install-link.sh --version X --config <served> [--runtime-port 8443|none] [--without-discovery]`), `link_off` (`--uninstall [--keep-discovery]`, key and paired PCs kept), `link_start` (`systemctl restart canworks-link`), `discovery_on` (`--discovery-only`), `discovery_off` (`--remove-discovery`)
- [x] 2.2 `devices/plan.py`: Remote link row action (Turn on… / Turn off… / Start) and served config text; new row **Found on the local network** with its action; both only with the plugin or the bridge installed; muted in a CODESYS project
- [x] 2.3 Served config: plugin's when installed, else the open bridge project's instance, else the only instance; several and none chosen → the start request carries the picked instance; refused otherwise
- [x] 2.4 `server.py` / `service.py`: pass the instance for link actions; confirm texts ("Paired PCs stay paired." for off)

## 3. Page

- [x] 3.1 `devices.js`: row buttons for the link and discovery, the discovery row, the instance choice in the confirm dialog when needed, end texts after the jobs
- [x] 3.2 The link row says what it serves ("serves the PLC" / "serves the bridge packer")

## 4. Tests

- [x] 4.1 `tests/test_devices.py`: plan rows and actions for plugin only, bridge only (one and two instances), both, none; command lines of the new actions
- [x] 4.2 `tests/test_configurator_devices_page.py`: fake SSH device, link off then on, discovery off then on, with no config open

## 5. Docs

- [x] 5.1 `docs/devices.md` (rows and actions), `docs/remote-access.md` (turning the link on and off from the Devices page, `install-link.sh` on its own), README, version bump (tools 0.114.0)

## 6. Hardware

- [ ] 6.1 Bench Linux device from the Devices page: link off (paired PC entry kept in `/etc/canworks-link`), link on (same link ID, PC still paired, discovery shows the link ID), discovery off (not found on the LAN) and on; then a clean PLC start
