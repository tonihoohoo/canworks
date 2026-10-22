## 1. Link script

- [ ] 1.1 `scripts/install-link.sh` release mode: `--version X`, or outside a checkout, downloads the `deploy-vX` tarball and runs its own `install-link.sh` with the same options (as `install-bridge.sh` does); `--dry-run` prints the download
- [ ] 1.2 `--without-discovery` (link only, no Avahi file; an existing one is removed) and `--discovery-only` (alias of `--without-link`)
- [ ] 1.3 The Avahi file carries the link ID whenever `/etc/canworks-link` has a key and the link service is installed, whichever option wrote it; turning the link off rewrites it without the ID
- [ ] 1.4 Script tests: release mode dry run, each option, link ID kept after `--discovery-only` on a device with the link

## 2. Jobs and plan

- [ ] 2.1 `devices/jobs.py`: actions `link_on` (`install-link.sh --version X --config <served> [--runtime-port 8443|none] [--without-discovery]`), `link_off` (`--uninstall` of the service only, key and paired PCs kept, advertisement rewritten), `link_start` (`systemctl restart canworks-link`), `discovery_on`, `discovery_off`
- [ ] 2.2 `devices/plan.py`: Remote link row action (Turn on… / Turn off… / Start) and served config text; new row **Found on the local network** with its action; both only with the plugin or the bridge installed; muted in a CODESYS project
- [ ] 2.3 Served config: plugin's when installed, else the open bridge project's instance, else the only instance; several and none chosen → the start request carries the picked instance; refused otherwise
- [ ] 2.4 `server.py` / `service.py`: pass the instance for link actions; confirm texts ("Paired PCs stay paired." for off)

## 3. Page

- [ ] 3.1 `devices.js`: row buttons for the link and discovery, the discovery row, the instance choice in the confirm dialog when needed, end texts after the jobs
- [ ] 3.2 The link row says what it serves ("serves the PLC" / "serves the bridge packer")

## 4. Tests

- [ ] 4.1 `tests/test_devices.py`: plan rows and actions for plugin only, bridge only (one and two instances), both, none; command lines of the new actions
- [ ] 4.2 `tests/test_configurator_devices_page.py`: fake SSH device, link off then on, discovery off then on, with no config open

## 5. Docs

- [ ] 5.1 `docs/devices.md` (rows and actions), `docs/remote-access.md` (turning the link on and off from the Devices page, `install-link.sh` on its own), README, PC tools release notes, version bump

## 6. Hardware

- [ ] 6.1 Bench Linux device from the Devices page: link off (paired PC entry kept in `/etc/canworks-link`), link on (same link ID, PC still paired, discovery shows the link ID), discovery off (not found on the LAN) and on; then a clean PLC start
