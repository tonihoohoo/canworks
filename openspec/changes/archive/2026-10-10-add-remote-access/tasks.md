## 1. Link core

- [x] 1.1 `canworks/link/` module: key handling (device and PC), paired PCs store, stream header, forwarder on 127.0.0.1 with tuned buffers; pin `iroh` to the 1.1 series with platform markers in `pyproject.toml`; verify offline (relays off) with tests: paired PC forwards both targets, unpaired PC limited to `pair`, unknown target closed, limits, 127.0.0.1-only listen, throughput measured (about 1.6 MB/s on loopback on Windows, the iroh Python binding's own limit; enough for diagnostics and uploads).
- [x] 1.2 Token pairing: SCRAM against the deployed config's `token_verifier` with the link channel binding (reuse the diag client's SCRAM code), mutual proof, rate limits, scope check (`lan` address ranges and direct path, `anywhere`, `off`), `manage` stream (list, remove, remove self); verify with tests for right and wrong token, scope refusals, rate limit, removal closing sessions within one second.
- [x] 1.3 Device entry point `canworks-link` (`run`, `id`, `list`, `allow`, `revoke`), config file watch applying `remote_link` within 5 seconds (relays off = no outside traffic), log lines; verify with tests on a temporary config directory; with `internet` false the endpoint has relays and address lookup off (checked on hardware, 6.4).
- [x] 1.4 PC side: remembered runtimes store, automatic path choice (direct first, link after 300 ms or on failure), automatic pairing after a direct login, `canworks-diag link list|forget|open`, "unavailable on this platform" path; verify against the fake diag server and a stub HTTPS server behind a test link.

## 2. Config

- [x] 2.1 `remote_link` in the version 2 and version 1 schemas, the Python config checks (shared fixtures) and the plugin and bridge config parsers (accepted, checked, unused); verify one rejection test per bad field in Python and C++.

## 3. Clients and configurator

- [x] 3.1 `diag.py`: remembered names, `link:NAME`, round-trip measurement and timeout rule, path in `status`; `cli.py`: deploy over the chosen path; verify with tools tests.
- [x] 3.2 Discovery: Avahi service file template and `canworks-diag discover` with python-zeroconf (new dependency); verify the Avahi file in tests and browsing on hardware (6.4).
- [x] 3.3 Configurator: discovered and remembered runtimes in the connect box, automatic pairing, Online access tick box, relay list and paired PCs with Remove (on Show paired PCs), path and round trip colours, confirmations for LSS fast scan and PDO test with SYNC on slow paths; verify with page tests.

## 4. Install

- [x] 4.1 `install-stock.sh` and `install-bridge.sh`: `--with-link`, `--without-discovery`, unit file, venv, config path for the watch, uninstall and purge; verify with the script tests (stub `systemctl`, stub `pip`).

## 5. Docs

- [x] 5.1 `docs/remote-access.md` (first use in three steps; same network, other networks, internet with the link and a self-hosted relay, a site VPN or mesh VPN as alternatives, no internet: Ethernet cable, USB-C gadget, Pi hotspot, local access point; what not to do; link limits), updates to `diagnostics.md`, `config.md`, `deploy.md`, `configurator.md`, `install-stock.md`, `modbus-bridge.md`, README line.

## 6. Hardware (the Pi; open until run)

- [ ] 6.1 Install with `--with-link` on the Pi; connect once from the Mac on the LAN with the token; check the Mac is paired with no other step.
- [ ] 6.2 Tick **Reachable from other networks** and upload; move the Mac to a phone hotspot; pick the runtime in the connect box: connects, path and round trip shown, SDO read works.
- [ ] 6.3 OpenPLC Editor **Build and upload** through `canworks-diag link open` from the phone hotspot; the program runs and CANopen starts.
- [ ] 6.4 Discovery over a direct Ethernet cable and over the Pi's Wi-Fi hotspot with no internet; pairing over each.

Run on 2026-10-10 from a Windows PC on the Pi's LAN (the Mac was not used):
- `install-link.sh` on the Pi (managed Docker install, config `/opt/canworks/lib/canworks.json`): service up, Avahi service published (avahi-daemon log), link ID advertised.
- A PC paired with `canworks-link allow` (the template project's token is not on that PC, so automatic token pairing was not run on hardware; it is covered by the offline tests).
- Over the link on the LAN: the diagnostics channel answered (a wrong token was refused by the plugin itself), the runtime's HTTPS presented the same certificate as directly, round trip 18-38 ms over Wi-Fi.
- With `remote_link.internet` true: the service restarted with the public relays; a PC that knew only the relay connected through it (`relayed` in the log) and moved to a direct path within a second. Address lookup by DNS failed on that PC's network; the relay URL the PC learned at pairing was enough.
- Discovery: `canworks-diag discover` on that Windows PC found nothing, with its network profile set to Public (Windows' firewall drops the mDNS answers); to be repeated from the Mac or with a Private profile.
- The template config was restored byte for byte afterwards and the test PCs removed. The runtime container restarted once during the session (supervisor: unhealthy, restarted, healthy again 6 s later); the cause was not found in the logs.
