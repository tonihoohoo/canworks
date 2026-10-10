## 1. Link core

- [ ] 1.1 `canworks/link/` module: key handling (device and PC), allow-list and saved runtimes stores, stream header, forwarder on 127.0.0.1 with tuned buffers; pin `iroh` to the 1.1 series with platform markers in `pyproject.toml`; verify offline (relays off) with tests: paired PC forwards both targets, unpaired refused before a stream, unknown target closed, revoke closes within one second, limits, 127.0.0.1-only listen, throughput of at least 10 MB/s on loopback.
- [ ] 1.2 Device entry point `canworks-link` (`run`, `id`, `allow`, `revoke`, `list`, `enable --relays`), config reload without restart, log lines; verify with tests on a temporary config directory.
- [ ] 1.3 PC commands `canworks-diag link id|add|list|remove|open`; "not available on this platform" path; verify with tests (the platform check mocked).

## 2. Clients over the link

- [ ] 2.1 `--runtime link:NAME` in `diag.py` and `cli.py` (deploy); round-trip measurement and timeout rule; path in `status`; not-paired message with the PC's link ID; verify against the fake diag server and a stub runtime HTTPS server behind a test link.
- [ ] 2.2 `canworks-deploy link pair --ssh`; verify with a stubbed `ssh`.

## 3. Discovery

- [ ] 3.1 Avahi service file template and `canworks-diag discover` with python-zeroconf (new dependency); verify with a zeroconf responder in the test.
- [ ] 3.2 Configurator connect box: discovered and link runtimes; online view path and round trip colours; confirmations for LSS fast scan and PDO test with SYNC on slow paths; verify with page tests.

## 4. Install

- [ ] 4.1 `install-stock.sh` and `install-bridge.sh`: `--with-link`, `--without-discovery`, unit file, venv, uninstall and purge; verify with the script tests (stub `systemctl`, stub `pip`).

## 5. Docs

- [ ] 5.1 `docs/remote-access.md` (same network, other networks, internet with the link and a self-hosted relay, no internet: Ethernet cable, USB-C gadget, Pi hotspot, local access point; what not to do; link limits), updates to `diagnostics.md`, `deploy.md`, `configurator.md`, `install-stock.md`, `modbus-bridge.md`, README line.

## 6. Hardware (Pi via Remote Control; open until the Pi is reachable)

- [ ] 6.1 Install with `--with-link` on the Pi; pair the Mac over SSH; online view and an SDO read over `link:` on the same LAN (direct path).
- [ ] 6.2 Same with the Mac on a phone hotspot (other network) and relays `default`: connects, path shown, round trip measured.
- [ ] 6.3 OpenPLC Editor **Build and upload** through `canworks-diag link open`; the program runs and CANopen starts.
- [ ] 6.4 Discovery over a direct Ethernet cable and over the Pi's Wi-Fi hotspot with no internet.
