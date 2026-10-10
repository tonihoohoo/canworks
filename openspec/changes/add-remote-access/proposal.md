## Why

The configurator, `canworks-diag`, `canworks-deploy` and the OpenPLC Editor reach a runtime only when the PC can open its ports directly: the diagnostics port (7531) and the runtime's HTTPS port (8443). That works on one LAN. It does not work when the machine sits behind NAT, on a mobile (LTE) connection, on another site, or when the engineer is at home. Today the only answer is "set up a VPN yourself", and nothing in the docs says how.

The diagnostics channel is already safe on any network: TLS with a SCRAM login bound to the certificate, so a relay or tunnel in the path can neither read nor change anything. What is missing is reachability, discovery on the local network, and guidance for the cases with no internet at all.

## What Changes

- **Remote link (new, off by default)**: `canworks-link`, a small service on the runtime's device, built on iroh (open-source QUIC peer-to-peer library: dial by public key, hole punching, relay fallback over HTTPS port 443, MIT/Apache-2.0). It accepts connections only from PCs on its allow-list and forwards them to the local diagnostics port and the runtime's HTTPS port, nothing else. No account, no root on the PC, no port opened on the router.
  - Pairing is by public key: the PC shows its link ID, the device adds it with `sudo canworks-link allow ID` (or `canworks-deploy link pair` does it over SSH). Unpaired PCs are refused before any data flows.
  - Relays: the public relays of the iroh project for trying it out; a self-hosted relay (one small server on port 443) for production, set in the device's link config and in the PC's runtime entry.
  - Each connection is logged on the device with the PC's ID and path (direct or relayed).
- **PC side**: a runtime address `link:NAME` in `canworks-diag`, `canworks-deploy` and the configurator's connect box opens the link for the command's duration. `canworks-diag link open NAME` keeps local ports open for other programs, so the OpenPLC Editor's **Build and upload** and a browser reach the runtime through `127.0.0.1`. `canworks-diag link id`, `link add`, `link list`, `link remove` manage the PC's identity and saved runtimes.
- **Discovery on the local network**: the device advertises `_canworks._tcp` over mDNS/DNS-SD (an Avahi service file installed with the plugin). The configurator lists runtimes found on the LAN, an Ethernet cable, the Pi's USB-C gadget network or its Wi-Fi hotspot, instead of asking for an IP. Typing an address keeps working.
- **Link quality**: the online view shows the path (LAN, link direct, link relayed) and the measured round trip; client timeouts scale with it, and LSS fast scan and PDO tests with SYNC warn on a relayed or slow path.
- **Docs**: new `docs/remote-access.md`: same network, other networks (routing, SSH jump host, an existing site VPN), internet (remote link), and no internet (Ethernet cable, USB-C gadget, Pi hotspot, a local Wi-Fi access point), plus the rule never to expose 7531 or 8443 to the internet. README gets a line.

## Non-goals

- No change to the plugin or the diagnostics protocol: the link forwards bytes to 127.0.0.1, so the TLS + SCRAM login stays end to end.
- No raw CAN over the link (the remote bus sharing idea of 2026-10-07 is a separate change).
- No SSH or other ports through the link.
- No control traffic: the link is for diagnostics, commissioning and upload, not for closing loops (see `docs/remote-access.md`).

## Capabilities

### New Capabilities
- `remote-link`: the device service, allow-list pairing, relays, forwarding, logging, PC-side link client and `link:` addresses.
- `runtime-discovery`: mDNS/DNS-SD advertisement and the PC tools' discovery list.

### Modified Capabilities
- `canopen-online-diagnostics`: `link:NAME` runtime addresses, round-trip based timeouts and path reporting in the client.
- `canopen-configurator`: discovered runtimes and link entries in the connect box; path and round trip in the online view; warnings for timing-sensitive operations on slow paths.
- `canopen-deploy`: `--runtime link:NAME`, `link pair` over SSH.
- `canopen-stock-install`: `--with-link` installs the link service and the Avahi service file.

## Impact

- New `tools/deploy/canworks/link/` (client, forwarder, key and runtime store) and a device-side entry point `canworks-link` that needs only Python 3 and the `iroh` wheel (Linux aarch64 and x86_64 wheels exist).
- `pyproject.toml`: `iroh` as a dependency on platforms with a wheel (Windows x64, macOS arm64, Linux x86_64/aarch64); on others (Intel Mac) link commands say the link is not available there.
- `scripts/install-stock.sh`, `scripts/install-bridge.sh`: `--with-link`; systemd unit `canworks-link.service`; `/etc/canworks-link/` (key, allow-list, config); Avahi file `/etc/avahi/services/canworks.service`.
- Configurator `server.py` and online page; `diag.py`, `cli.py`.
- CI: link tests run offline (relays off) inside the existing tools test shards; no new job.
- Docs: `docs/remote-access.md` (new), `docs/diagnostics.md`, `docs/deploy.md`, `docs/configurator.md`, `docs/install-stock.md`, `docs/modbus-bridge.md`, README.
