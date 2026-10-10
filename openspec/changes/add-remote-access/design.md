## Context

- The diagnostics channel (plugin, port 7531, only while the PLC runs) uses TLS 1.2+ with a fresh self-signed certificate per start and a SCRAM-SHA-256-PLUS login bound to it. Any byte pipe between PC and plugin is therefore safe; the pipe only has to exist.
- Deploy and the OpenPLC Editor use the runtime's HTTPS port 8443 (self-signed; `canworks-deploy` pins the fingerprint).
- `bind` is IPv4 only and there is no discovery: users type host names or IPs.
- Users are engineers on Windows and macOS laptops; the device is a Raspberry Pi class Linux box, sometimes behind NAT or on LTE, sometimes with no internet at all.

Spike (2026-10-10, Windows 11, `iroh` 1.1.0 from PyPI, relays and discovery off): a device endpoint with an allow-list and a PC endpoint forwarded a local TCP port to a stand-in diagnostics server. Round trip on the LAN about 2 ms (median), an unpaired PC was refused with a close reason before any stream opened, the path was a direct UDP path, and the plain-Python forwarder moved about 1.5 MB/s (enough for diagnostics and program upload; buffer tuning is a task).

## Goals / Non-Goals

**Goals:** reach a runtime from any network without an account, without admin rights on the PC, without opening router ports; find runtimes on the local network; keep plain host:port working for sites with their own VPN.

**Non-goals:** plugin or protocol changes; raw CAN over the link; SSH through the link; any control traffic.

## Decisions

### 1. iroh for the internet path

Alternatives considered (research/wireless-can-2026-10-10.md in the project notes): tailcat (simplest CLI, but explicitly experimental, a Go binary per platform, a bearer token anyone can reuse, needs a DERP server even on a LAN), Tailscale/Headscale and NetBird (need an account or a self-hosted control plane and admin rights for the client; still documented as "bring your own network"), Cloudflare Tunnel and ngrok (traffic through a third party, ngrok exposes a public port), plain WireGuard (no NAT traversal, needs admin on both ends).

iroh: stable 1.0 API (1.1.0 current), Python wheels for Windows x64, macOS arm64, Linux x86_64 and aarch64, async API, no root, dial by Ed25519 public key, QUIC with hole punching and a relay fallback over HTTPS 443 (gets through UDP-blocking networks), self-hostable relay server, MIT/Apache-2.0.

### 2. Allow-list pairing by public key, not a shared token

- The device has a secret key (`/etc/canworks-link/secret.key`, 0600, made on first start). Its public key (link ID) is not secret.
- Each PC has its own secret key in the user's config directory (`canworks/link/secret.key`). `canworks-diag link id` prints its link ID.
- The device accepts a connection only when the remote ID is in `/etc/canworks-link/allow.json`; anything else is closed with "not paired" before a stream is accepted. An empty list accepts nobody.
- Adding a PC needs a shell on the device (`sudo canworks-link allow ID [--name NAME]`) or SSH from the PC (`canworks-deploy link pair --ssh user@host`). Both happen on a path the user already trusts. `canworks-link revoke ID` removes it and drops its open connections.
- The SCRAM token is still required on top: pairing makes the runtime reachable, the token gives access.

Why not a ticket/token like tailcat: a copied token works for anyone who has it; a key allow-list ties access to a PC and can be revoked per PC.

### 3. What the device forwards

- One ALPN `canworks/link/1`. Each QUIC bi-stream starts with a one-line header naming the target: `diag` (127.0.0.1:7531, or the configured diagnostics port) or `runtime` (127.0.0.1:8443). Unknown targets close the stream. Ports come from `/etc/canworks-link/link.json` (`targets`); no arbitrary host or port, ever.
- A bridge device (`canworks-bridge`) forwards `diag` only (and `modbus` 127.0.0.1:502 if the config says so).
- Limits: 4 connected PCs, 16 streams per PC; streams idle for 10 minutes are closed.
- Log lines: `link: PC <name or short ID> connected (direct 192.0.2.10:...)`, `... path now relayed`, `... disconnected`, `link: refused unpaired <short ID>` (at most once a minute per ID).

### 4. Relays and finding the device

- `link.json` `relays`: `"default"` (the iroh project's public relays, rate-limited, for trying it out), a list of own relay URLs, or `"off"` (LAN and direct addresses only).
- The PC finds the device by its link ID through iroh's address lookup (the device publishes its current relay and addresses), and also keeps the address it learned at pairing time. On a LAN without internet the PC tools connect directly (discovery below), so the link is not needed there.
- The PC's runtime entry stores the link ID and optionally the relay list, so a site with its own relay does not depend on public services.

### 5. PC side

- `canworks.link` module: identity, saved runtimes (`link add NAME ID [--relay URL]`, `list`, `remove`), and a forwarder that opens local ports on 127.0.0.1 only.
- `--runtime link:NAME` in `canworks-diag` and `canworks-deploy`: the tool opens the link, connects its usual TLS client to the local port and closes the link when the command ends. Deploy's fingerprint pinning is unchanged.
- `canworks-diag link open NAME [--diag-port P] [--runtime-port P]`: keeps the forward open and prints `diagnostics 127.0.0.1:P` and `runtime https://127.0.0.1:P`, for the OpenPLC Editor, a browser or any other tool. Ctrl+C closes it.
- Configurator: connect box offers saved link runtimes; the server process owns the link while the online view is connected.

### 6. Discovery on the local network

- An Avahi service file advertises `_canworks._tcp` on port 7531 with TXT `name`, `id` (link ID if the link is installed), `diag=7531`, `runtime=8443`, `v=1`. It is static, so the device is listed even while the PLC is stopped; the configurator then says diagnostics are not listening.
- PC tools browse with python-zeroconf themselves (Windows' own `.local` lookup is unreliable). Results show in the configurator's connect box and in `canworks-diag discover`.
- Works on a LAN, a direct Ethernet cable (link-local addresses), the Pi's USB-C gadget network and its Wi-Fi hotspot. Does not cross routers (documented; type the address there).

### 7. Path, round trip and timeouts

- The client measures round trip on connect and every 10 s (a `status` request, or the link's own RTT). Request timeouts become max(configured, 4 × RTT + 500 ms).
- The online view shows `LAN`, `link direct` or `link relayed` and the round trip; amber above 100 ms, red above 300 ms.
- LSS fast scan and PDO tests with a SYNC period ask for confirmation on a relayed path or above 100 ms (they run on the runtime, but the operator's view lags and stop commands arrive late).

## Risks / Trade-offs

- **Public relays**: rate-limited, no service guarantee. Documented as for trying out; the self-hosted relay recipe is part of the docs.
- **Corporate IT policy** may forbid peer-to-peer tools. Plain host:port with the site's own VPN stays fully supported.
- **Throughput** of the Python forwarder (~1.5 MB/s in the spike) is enough for diagnostics and uploads of a few MB; tuning buffers is a task, not a design change.
- **iroh Python binding** is younger than the Rust library; pinned to a minor version with a test that runs offline in CI.
- **Device key theft** lets an attacker impersonate the device to paired PCs but not log in (SCRAM still needs the token, and the server proves the verifier).
- **Intel Macs** have no wheel: link commands there say so; direct and VPN access still work.

## Migration

Nothing changes for existing installs. The link and discovery are installed only with `--with-link` (link) and by default for the Avahi file (discovery, can be skipped with `--without-discovery`).

## Open Questions

1. Should `canworks-deploy link pair` also be offered over the runtime's HTTPS login instead of SSH? Default: SSH only (the upstream runtime has no hook for it).
2. Default `relays` for a fresh install: `"default"` (works at once) or `"off"` (nothing leaves the LAN until chosen). Default in this proposal: `"off"`, and `canworks-link enable --relays default|URL` turns it on.
