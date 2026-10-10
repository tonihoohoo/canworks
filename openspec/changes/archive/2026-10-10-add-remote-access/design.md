## Context

- The diagnostics channel (plugin, port 7531, only while the PLC runs) uses TLS 1.2+ with a fresh self-signed certificate per start and a SCRAM-SHA-256-PLUS login bound to it. Any byte pipe between PC and plugin is therefore safe; the pipe only has to exist.
- Deploy and the OpenPLC Editor use the runtime's HTTPS port 8443 (self-signed; `canworks-deploy` pins the fingerprint).
- `bind` is IPv4 only and there is no discovery: users type host names or IPs.
- The deployed config lives at `<runtime>/core/generated/conf/canworks.json` (stock runtime) or `/etc/canworks-bridge/NAME/canworks.json` (bridge) and carries the token's `token_verifier`.
- Users are engineers on Windows and macOS laptops; the device is a Raspberry Pi class Linux box, sometimes behind NAT or on LTE, sometimes with no internet at all.
- Goal set by Toni (2026-10-10): it must be seamless for the user. No keys, IDs, SSH or tunnel commands in normal use.

Spike (2026-10-10, Windows 11, `iroh` 1.1.0 from PyPI, relays and discovery off): a device endpoint with an allow-list and a PC endpoint forwarded a local TCP port to a stand-in diagnostics server. Round trip on the LAN about 2 ms (median), an unpaired PC was refused with a close reason before any stream opened, the path was a direct UDP path, and the plain-Python forwarder moved about 1.5 MB/s (enough for diagnostics and program upload; buffer tuning is a task).

## Goals / Non-Goals

**Goals:** reach a runtime from any network without an account, without admin rights on the PC, without opening router ports; first use is "install, connect once on the LAN with the token, tick internet access"; find runtimes on the local network; keep plain host:port working for sites with their own VPN.

**Non-goals:** diagnostics protocol changes; raw CAN over the link; SSH through the link; any control traffic.

## Decisions

### 1. iroh for the internet path

Alternatives considered (project research notes, 2026-10-10): tailcat (simplest CLI, but explicitly experimental, a Go binary per platform, a bearer address anyone can reuse, needs a relay even on a LAN), Tailscale/Headscale and NetBird (need an account or a self-hosted control plane and admin rights for the client; documented as "bring your own network", the better choice where every PC and device can run them), Cloudflare Tunnel and ngrok (traffic through a third party, ngrok exposes a public port), plain WireGuard (no NAT traversal, needs admin on both ends).

iroh: stable 1.0 API (1.1.0 current), Python wheels for Windows x64, macOS arm64, Linux x86_64 and aarch64, async API, no root, dial by Ed25519 public key, QUIC with hole punching and a relay fallback over HTTPS 443 (gets through UDP-blocking networks), self-hostable relay server, MIT/Apache-2.0.

### 2. Identities and the allow-list

- The device has a secret key (`/etc/canworks-link/secret.key`, 0600, made on first start). Its public key (link ID) is not secret and is advertised over mDNS.
- Each PC has one secret key per user in the user's config directory, made on first use.
- The device keeps paired PCs in `/etc/canworks-link/paired.json` (link ID, name, paired time, last seen). Only paired PCs may open forwarding streams.
- `canworks-link list`, `canworks-link revoke ID|NAME` and `canworks-link allow ID` exist for service work on the device; normal users never need them.

### 3. Pairing with the diagnostics token

- An unpaired PC may open exactly one stream type: `pair`. Everything else is refused with `not paired`.
- On a `pair` stream the link service runs the same SCRAM-SHA-256 exchange the plugin uses, against the `token_verifier` of the deployed config. The channel binding is SHA-256 of `"canworks-link-pair" || device link ID || PC link ID`: iroh's TLS 1.3 already authenticates both keys, so a machine in the middle cannot complete the exchange, and a captured exchange is useless for any other pair of keys. Both sides prove themselves (the server signature proves the device knows the verifier).
- On success the PC is added to `paired.json` with the name it sent (its host name) and the PC tools store the runtime. On failure: `wrong token`, at most one attempt per second per PC and 10 per minute in total, each logged.
- Scope, from `diagnostics.remote_link.pairing`: `"lan"` (default) accepts a `pair` stream only when the connection's path is direct and the PC's address is private or link-local (10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7, fe80::/10); `"anywhere"` also over the internet and relays; `"off"` refuses all token pairing (only `canworks-link allow` on the device).
- The configurator and `canworks-diag` pair automatically: after a successful direct login to a runtime whose link ID they know (from discovery), they open a `pair` stream with the same token, in the background, and tell the user "This PC can now reach line3 from other networks" only when internet access is on.
- Without a deployed config with a `token_verifier` there is nothing to pair against; the configurator says so.

Why the token: the user already has it, it already gates everything the link would expose, and it never crosses the network. Why LAN-only by default: a token copied out of a project file would otherwise be enough to gain a permanent foothold from anywhere; with `"lan"` that also needs physical or network presence once.

### 4. What the device forwards

- One ALPN `canworks/link/1`. Each QUIC bi-stream starts with a one-line header naming the target: `pair`, `diag` (127.0.0.1:7531, or the deployed config's diagnostics port) or `runtime` (127.0.0.1:8443). Unknown targets close the stream. No arbitrary host or port, ever.
- A bridge device forwards `diag` only.
- Limits: 4 connected PCs, 16 streams per PC; streams idle for 10 minutes are closed.
- Log lines: `link: PC <name> connected (direct 192.0.2.10:...)`, `... path now relayed`, `... disconnected`, `link: paired PC <name> (lan)`, `link: refused unpaired <short ID>` and `link: pairing failed for <short ID>` (each at most once a minute per ID).

### 5. Internet access from the config

- New optional object `diagnostics.remote_link` (version 2; `master.diagnostics.remote_link` in version 1): `internet` (default `false`), `relays` (list of relay URLs; empty or absent = the iroh project's public relays), `pairing` (`"lan"`, `"anywhere"`, `"off"`; default `"lan"`).
- The configurator's Online access section gets **Reachable from other networks** (sets `internet`), an optional relay URL list under it, and the list of paired PCs with **Remove** (served by the link service, see 7).
- The link service watches the deployed config file and applies changes within a few seconds: with `internet: false` it uses no relays and no address lookup service, so nothing leaves the local network; with `true` it uses the configured relays and publishes its address for lookup.
- The plugin and the bridge accept the object and check its fields; they do not use it.

### 6. Remembered runtimes and automatic path choice

- The PC tools keep `runtimes.json` in the user's config directory: name, last known addresses, link ID, relay URLs, last path. Entries come from any successful connection (discovered or typed) and from pairing.
- Connecting to a remembered runtime (configurator connect box, `--runtime NAME`) starts a direct TCP connection to the known addresses and, 300 ms later or as soon as the direct attempt fails, the link (if paired). The first one to finish the TLS + SCRAM login is used; the other is dropped. A typed address or `link:NAME` forces one path.
- After connecting, the tools update the remembered addresses, so a runtime that moved on the LAN is still found.

### 7. Local forwards and removal of paired PCs

- `canworks-diag link open NAME [--diag-port P] [--runtime-port P]` keeps a forward open on 127.0.0.1 only and prints `diagnostics 127.0.0.1:P` and `runtime https://127.0.0.1:P` for the OpenPLC Editor, a browser or any other tool.
- `canworks-deploy --runtime NAME` uses the same path choice for the `runtime` target; fingerprint pinning is unchanged.
- A paired PC can open a `manage` stream that, after the same SCRAM proof as pairing, lists paired PCs or removes one. The configurator's **Remove** uses it; a PC can always remove itself without the token.

### 8. Discovery on the local network

- An Avahi service file advertises `_canworks._tcp` on port 7531 with TXT `name`, `id` (link ID when the link is installed), `diag=7531`, `runtime=8443`, `v=1`. It is static, so the device is listed even while the PLC is stopped; the configurator then says diagnostics are not listening.
- PC tools browse with python-zeroconf themselves (Windows' own `.local` lookup is unreliable).
- Works on a LAN, a direct Ethernet cable (link-local addresses), the Pi's USB-C gadget network and its Wi-Fi hotspot. Does not cross routers: a runtime there is reached by typed address, and pairing it needs `canworks-link allow` or `pairing: "anywhere"`.

### 9. Path, round trip and timeouts

- The client measures round trip on connect and every 10 s. Request timeouts become max(configured, 4 × RTT + 500 ms).
- The online view shows `LAN`, `internet direct` or `internet relayed` and the round trip; amber above 100 ms, red above 300 ms.
- LSS fast scan and PDO tests with a SYNC period ask for confirmation on a relayed path or above 100 ms.

## Risks / Trade-offs

- **Token pairing** makes the token the key to remote reachability as well as to access. Mitigated by `pairing: "lan"` default, rate limits, logs and per-PC removal.
- **Public relays**: rate-limited, no service guarantee. Fine to start; the self-hosted relay recipe is in the docs.
- **Corporate IT policy** may forbid peer-to-peer tools. Plain host:port with the site's own VPN stays fully supported.
- **Throughput** of the Python forwarder (~1.5 MB/s in the spike) is enough for diagnostics and uploads of a few MB; buffer tuning is a task.
- **iroh Python binding** is younger than the Rust library; pinned to a minor version with offline tests in CI.
- **Intel Macs** have no wheel: the link is unavailable there; direct and VPN access still work.

## Migration

Nothing changes for existing installs or configs. The link is installed only with `--with-link`; the Avahi file by default (`--without-discovery` skips it). Configs without `remote_link` behave as `internet: false`, `pairing: "lan"`.

## Open Questions

1. ~~Default relays.~~ Decided (Toni, 2026-10-10): internet access off until ticked.
2. ~~Pairing over SSH.~~ Replaced by token pairing (Toni, 2026-10-10: "seamless for the user").
