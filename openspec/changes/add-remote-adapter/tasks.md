# Tasks

## 1. Server

- [ ] 1.1 Tests first: SCRAM server half against `diag.Client._login` (right token, wrong token, wrong channel binding), on a `virtual:` adapter.
- [ ] 1.2 `localbus/serve.py`: TLS listener with an `openssl`-made P-256 certificate (temporary 0700 folder removed after load; clear message when `openssl` is missing), SCRAM login, JSON-lines dispatch to one shared `LocalBus`, hello with `remote`.
- [ ] 1.3 Adapter opened at first login with the bit rate check, closed after the last; per-connection jobs, traces and PDO tests stop on close.
- [ ] 1.4 `--allow-changes` gate on `CHANGES` operations with the message naming the option; tests.
- [ ] 1.5 Limits (4 / 8 / 2 per address, 30 s login, 10 min idle, login delay and rate) and logging; tests.
- [ ] 1.6 Token: first-start token printed once, verifier in `adapter-serve.json` (0600), `--new-token`, `--token-file`; tests.

## 2. Service

- [ ] 2.1 `--install-service` / `--remove-service` / `--status`: unit with `User=$SUDO_USER`, `AmbientCapabilities=CAP_NET_ADMIN`, restart on failure; Avahi file with `kind=adapter` when Avahi is there. Tests on generated files with a fake systemctl.

## 3. PC side

- [ ] 3.1 `--adapter remote:HOST[:PORT]` in `canworks-diag` with token options; runtime-not-adapter message; tests against the test server.
- [ ] 3.2 Discovery lists `kind=adapter` answers separately (CLI and configurator).
- [ ] 3.3 Configurator `RemoteAdapterTarget`, tokens per host in `online.json`, recent kind `remote_adapter`, connection bar text with the round trip.
- [ ] 3.4 Connect panel: Adapter on another machine in Commission and with a config, server bit rate shown, mismatch warning; browser tests incl. 1000/1280/1440 px.

## 4. Docs and version

- [ ] 4.1 `docs/pc-adapter.md` "An adapter on another machine" (server, token, service, SSH port forward from another network, security notes), `docs/install-pc.md`, README line, tour line if the tour covers the connect panel.
- [ ] 4.2 Bump the PC tools version (minor), release notes.

## 5. CI time

- [ ] 5.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.

## 6. Hardware (bench)

- [ ] 6.1 Server on the Pi with the slcan adapter (PLC stopped or the runtime not using that interface), configurator on the Windows PC: scan, SDO read/write, LSS inquire, trace, Disconnect frees the adapter.
- [ ] 6.2 Same from the Mac; `--install-service`, reboot, connect again with the same token; `--remove-service` leaves nothing behind. Clean PLC start afterwards.
