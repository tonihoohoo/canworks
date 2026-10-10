## Why

The configurator, `canworks-diag`, `canworks-deploy` and the OpenPLC Editor reach a runtime only when the PC can open its ports directly: the diagnostics port (7531) and the runtime's HTTPS port (8443). That works on one LAN. It does not work when the machine sits behind NAT, on a mobile (LTE) connection, on another site, or when the engineer is at home. Today the only answer is "set up a VPN yourself", and nothing in the docs says how.

The diagnostics channel is already safe on any network: TLS with a SCRAM login bound to the certificate, so a relay or tunnel in the path can neither read nor change anything. What is missing is reachability, discovery on the local network, guidance for the cases with no internet at all, and a setup that feels like nothing: the user should never deal with keys, IDs or tunnels.

## What Changes

- **Remote link**: `canworks-link`, a small service on the runtime's device, built on iroh (open-source QUIC peer-to-peer library: dial by public key, hole punching, relay fallback over HTTPS port 443, MIT/Apache-2.0). It accepts connections only from paired PCs and forwards them to the local diagnostics port and the runtime's HTTPS port, nothing else. No account, no admin rights on the PC, no port opened on the router.
- **Pairing with the token the user already has**: the first time a PC connects to a runtime on the local network with the right diagnostics token, the configurator (or `canworks-diag`) pairs that PC automatically. The link service checks the token itself against the deployed config's `token_verifier` (SCRAM, nothing secret crosses the network). No SSH, no IDs, no commands. By default pairing is accepted only over a direct local path, so a leaked token alone does not let anyone pair from the internet. Paired PCs are listed and removed in the configurator; `canworks-link revoke` does the same on the device.
- **Internet access is a tick box**: **Reachable from other networks** under the configurator's Online access, saved in the config (`diagnostics.remote_link`) and applied by the link service when the program is uploaded. Off by default (Toni, 2026-10-10): nothing contacts servers outside the local network until it is ticked. When ticked, it uses the iroh project's public relays, or the relay URLs the project names (self-hosted relay recipe in the docs).
- **Remembered runtimes, one connect path**: a runtime the PC has connected to once is remembered with its addresses and link ID. Choosing it later connects directly when the runtime is reachable and through the link otherwise; the user never chooses between "LAN" and "link". The same works in `canworks-diag --runtime NAME`, `canworks-deploy --runtime NAME`, and for other programs through `canworks-diag link open NAME`, which keeps local ports open for the OpenPLC Editor's **Build and upload**.
- **Discovery on the local network**: the device advertises `_canworks._tcp` over mDNS/DNS-SD (an Avahi service file installed with the plugin), including its link ID. The configurator lists runtimes found on the LAN, an Ethernet cable, the Pi's USB-C gadget network or its Wi-Fi hotspot, instead of asking for an IP. Typing an address keeps working.
- **Link quality**: the online view shows the path (LAN, internet direct, internet relayed) and the measured round trip; client timeouts scale with it, and LSS fast scan and PDO tests with SYNC ask for confirmation on a relayed or slow path.
- **One install switch**: `--with-link` on `install-stock.sh` and `install-bridge.sh` installs and starts the link; nothing else to run on the device.
- **Docs**: new `docs/remote-access.md`: same network, other networks (routing, SSH jump host, a site VPN or Tailscale), internet (remote link, self-hosted relay), and no internet (Ethernet cable, USB-C gadget, Pi hotspot, a local Wi-Fi access point), plus the rule never to expose 7531 or 8443 to the internet. README gets a line.

## Non-goals

- No change to the diagnostics protocol; the plugin only accepts the new `remote_link` config key. The link forwards bytes to 127.0.0.1, so the TLS + SCRAM login stays end to end.
- No raw CAN over the link (the remote bus sharing idea of 2026-10-07 is a separate change).
- No SSH or other ports through the link.
- No control traffic: the link is for diagnostics, commissioning and upload, not for closing loops.

## Capabilities

### New Capabilities
- `remote-link`: the device service, token pairing, allow-list, relays from the config, forwarding, logging, PC-side link client, remembered runtimes and local forwards.
- `runtime-discovery`: mDNS/DNS-SD advertisement and the PC tools' discovery list.

### Modified Capabilities
- `canopen-config-contract`: `diagnostics.remote_link` (relays, pairing scope) in the schema and config checks.
- `canopen-online-diagnostics`: remembered runtimes and automatic path choice in the client, automatic pairing, round-trip based timeouts and path reporting.
- `canopen-configurator`: discovered and remembered runtimes in the connect box, the Online access tick box and paired PCs list, path and round trip in the online view, confirmations for timing-sensitive operations on slow paths.
- `canopen-deploy`: deploy to a remembered runtime over the link.
- `canopen-stock-install`: `--with-link` and the Avahi service file.

## Impact

- New `tools/deploy/canworks/link/` (client, forwarder, pairing, runtime store) and a device-side entry point `canworks-link` that needs only Python 3 and the `iroh` wheel (Linux aarch64 and x86_64 wheels exist).
- `pyproject.toml`: `iroh` (and `zeroconf`) as dependencies; `iroh` only on platforms with a wheel (Windows x64, macOS arm64, Linux x86_64/aarch64). On others (Intel Mac) the link is unavailable and the tools say so; direct connections work as before.
- Plugin and bridge config parsers accept `diagnostics.remote_link` (checked, otherwise unused); schema `canworks.v2.schema.json` and the version 1 equivalent under `master.diagnostics`.
- `scripts/install-stock.sh`, `scripts/install-bridge.sh`: `--with-link`; systemd unit `canworks-link.service`; `/etc/canworks-link/` (key, paired PCs); Avahi file `/etc/avahi/services/canworks.service`.
- Configurator `server.py`, connect box, Online access section and online page; `diag.py`, `cli.py`.
- CI: link and pairing tests run offline (relays off) inside the existing tools test shards; no new job.
- Docs: `docs/remote-access.md` (new), `docs/diagnostics.md`, `docs/config.md`, `docs/deploy.md`, `docs/configurator.md`, `docs/install-stock.md`, `docs/modbus-bridge.md`, README.
