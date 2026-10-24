## 1. Adapter server options

- [x] 1.1 `serve.py`: `--service-user USER` (refuse root; owner and settings folder from it), `--token-verifier-file FILE` (validate, store, print nothing); install without token options keeps the stored verifier; tests
- [x] 1.2 `scripts/install-adapter.sh` (venv + locked PC tools when `canworks-diag` is missing, `dialout` for serial, `--install-service --service-user`, `--uninstall [--adapter]`, step lines, no token output); release asset; shellcheck; tests with stub pip and systemctl

## 2. Probe and plan

- [x] 2.1 `device-probe.sh`: adapter servers from `canworks-adapter-*.service` (state, adapter, bit rate, port, allow-changes, status file when readable); fake-root test case
- [x] 2.2 `plan.py`: **Remote CAN adapter** row (have text, actions Turn on…/Add…/Change…/Connect from this PC/Turn off…/New token…/Copy token), bit rate prefill and lock, shared-interface line, serial refusal, next free port, CODESYS muted; tests
- [x] 2.3 `jobs.py`: `adapter_on`, `adapter_change`, `adapter_off`, `adapter_token` commands; `remove_all` also removes adapter servers; tests

## 3. Configurator

- [x] 3.1 `server.py`/`service.py`: make the token and verifier on the PC, upload the verifier (0600) to an upload folder, keep the token in `online.json` before the job, refuse root SSH login, Copy token answer only on request
- [x] 3.2 `devices.js`: the row, the one-screen dialog, New token… confirm, Copy token, done notice with **Connect from this PC**
- [x] 3.3 `connection.js`: open the connect panel on Adapter on another machine with host:port (via Commission a CANopen device with no config)
- [x] 3.4 Page tests (playwright): turn on with no config, change keeps token, shared can0 line, connect shortcut

## 4. Docs

- [x] 4.1 README (remote adapter line mentions Devices), `docs/pc-adapter.md` (from the configurator), `docs/configurator.md` (the row and dialog)

## 5. Hardware checks (Linux device with can0, bridge running; Mac or Windows PC)

- [x] 5.1 Turn on from Devices with defaults; Connect from this PC; scan lists the nodes, read-only; Unlock… then an SDO read/write on a free object with force
  - Passed 2026-10-24 from the Mac (tools 0.131.1) on a Linux device with the bridge on can0 at 500 kbit/s: the job installed the PC tools and started `canworks-adapter-can0` as the login user with its Avahi file, the bridge kept running; Connect from this PC scanned read-only (another master on the bus) and found the node; after Unlock… an SDO read of 0x1017:00 and a same-value write with force worked and read back unchanged. No store.
- [x] 5.2 Change… to read-only: Unlock… refused naming the device; token still works
  - Passed 2026-10-24: the row and connection bar show read-only, reads work, the same write is refused by the server naming the device. Found: the NMT and error history sections still offer Unlock… on a read-only server, and the refusal shows only in the node's log.
- [x] 5.3 Reboot the device: server back, same token; Turn off frees can0
  - Passed 2026-10-24: after a reboot the server, bridge and PLC came back and the same token connected; Turn off removed the unit, the Avahi file and /opt/canworks-adapter, nothing listened on 7536 and the bridge kept running on can0.
- [x] 5.4 Second PC (Windows): New token…, connect; first PC asked for the token again
  - Passed 2026-10-24 with a second configurator on the Mac with an empty config folder standing in for the second PC: without or with a wrong token it was refused; its row offered New token…, after which the first PC's token was refused and Copy token (a dialog when the clipboard is unavailable) let the first PC connect again. The New token job installed the newest release, as documented.
