## 1. Adapter server options

- [ ] 1.1 `serve.py`: `--service-user USER` (refuse root; owner and settings folder from it), `--token-verifier-file FILE` (validate, store, print nothing); install without token options keeps the stored verifier; tests
- [ ] 1.2 `scripts/install-adapter.sh` (venv + locked PC tools when `canworks-diag` is missing, `dialout` for serial, `--install-service --service-user`, `--uninstall --interface`, step lines, no token output); release asset; shellcheck; tests with stub pip and systemctl

## 2. Probe and plan

- [ ] 2.1 `device-probe.sh`: adapter servers from `canworks-adapter-*.service` (state, adapter, bit rate, port, allow-changes, status file when readable); fake-root test case
- [ ] 2.2 `plan.py`: **Remote CAN adapter** row (have text, actions Turn on…/Add…/Change…/Connect from this PC/Turn off…/New token…/Copy token), bit rate prefill and lock, shared-interface line, serial refusal, next free port, CODESYS muted; tests
- [ ] 2.3 `jobs.py`: `adapter_on`, `adapter_change`, `adapter_off`, `adapter_token` commands; `remove_all` also removes adapter servers; tests

## 3. Configurator

- [ ] 3.1 `server.py`/`service.py`: make the token and verifier on the PC, upload the verifier (0600) to an upload folder, keep the token in `online.json` before the job, refuse root SSH login, Copy token answer only on request
- [ ] 3.2 `devices.js`: the row, the one-screen dialog, New token… confirm, Copy token, done notice with **Connect from this PC**
- [ ] 3.3 `connection.js`: open the connect panel on Adapter on another machine with host:port (via Commission a CANopen device with no config)
- [ ] 3.4 Page tests (playwright): turn on with no config, change keeps token, shared can0 line, connect shortcut

## 4. Docs

- [ ] 4.1 README (remote adapter line mentions Devices), `docs/pc-adapter.md` (from the configurator), `docs/configurator.md` (the row and dialog)

## 5. Hardware checks (Linux device with can0, bridge running; Mac or Windows PC)

- [ ] 5.1 Turn on from Devices with defaults; Connect from this PC; scan lists the nodes, read-only; Unlock… then an SDO read/write on a free object with force
- [ ] 5.2 Change… to read-only: Unlock… refused naming the device; token still works
- [ ] 5.3 Reboot the device: server back, same token; Turn off frees can0
- [ ] 5.4 Second PC (Windows): New token…, connect; first PC asked for the token again
