# Remote access

The configurator, `canworks-diag`, `canworks-deploy` and the OpenPLC Editor reach a runtime through two ports: the diagnostics channel (7531) and the runtime's HTTPS port (8443). This page covers reaching them on the same network, from other networks, over the internet with the **remote link**, and with no network at all.

The diagnostics channel is safe on any network: it is encrypted, and its login is bound to the connection, so the token never crosses the network and a machine in the path can neither read nor change anything ([diagnostics.md](diagnostics.md#security)). The ways below only make the runtime reachable; none of them has to be trusted with the data.

- [First use of the remote link](#first-use-of-the-remote-link)
- [Same network](#same-network)
- [Other networks](#other-networks)
- [Over the internet: the remote link](#over-the-internet-the-remote-link)
- [No network: cable, USB-C or Wi-Fi hotspot](#no-network-cable-usb-c-or-wi-fi-hotspot)
- [What the remote link is for, and what not](#what-the-remote-link-is-for-and-what-not)
- [Commands](#commands)
- [Security](#security)

## First use of the remote link

1. **Install** the bridge with the link on the device: `sudo scripts/install-bridge.sh --with-link NAME`.
2. **Connect once on the local network** with the token, as usual: pick the runtime in the configurator's connect box. The configurator pairs this PC with the runtime in the background.
3. **Tick Reachable from other networks** under **Online access** (Bus and master) and upload the program.

From then on, picking the runtime in the connect box works from anywhere: the tools use its local address when it answers and the link otherwise. The online view shows the path (`LAN`, `internet direct` or `internet relayed`) and the round trip.

## Same network

The device advertises itself on the local network (mDNS, `_canworks._tcp`; installed with the bridge unless `--without-discovery`), so the configurator's connect box lists it by name, and `canworks-diag discover` prints it:

```sh
canworks-diag discover
canworks-diag --runtime line3.local status
```

The advertisement does not depend on the PLC running: a stopped PLC is listed, and connecting says diagnostics are not listening. Typing a host name or address always works. Discovery needs Avahi on the device (`apt-get install avahi-daemon`; many device images have it already).

The search is one question sent on every network adapter of the PC, and the devices answer straight back to it (a legacy unicast answer). Nothing on the PC listens for the network, so Windows Defender Firewall does not ask to allow Python for it, and the list works on a network set to **Public** too. A device is listed at the address its answer came from. `canworks-diag discover line3.local` (or its address) asks one device directly; the tools do the same after connecting to a typed address, so the remote link learns the runtime and pairs this PC. Only an answer from the asked address counts.

Pairing and the link itself do open a port of their own, so Windows may ask once to allow Python when this PC first pairs with a runtime, and again after the tools move to a new Python (Windows asks per program, and each Python version is a new one). **Cancel** is fine: the PC always starts the connection, so online access and the link keep working. **Allow** opens that Python to incoming traffic on the chosen network type, which the tools do not need.

A runtime this PC is paired with keeps the link ID it was paired with. When it answers with another one (the device was reinstalled and made a new key, or another device took its address), the tools say "its identity changed" after the command and leave the remembered runtime as it was. If you know the runtime was reinstalled, pair again with the token: `canworks-diag --runtime line3.local --repair status`.

## Other networks

Discovery does not cross routers. From another subnet, VLAN or site:

- **Routed:** connect to the device's address; open 7531 and 8443 from the engineering subnet only.
- **Through a jump host:** forward both ports over SSH, `ssh -L 7531:DEVICE:7531 -L 8443:DEVICE:8443 user@jumphost`, then use `--runtime 127.0.0.1`.
- **A site VPN or mesh VPN** that makes the device's address reachable works as it is: give that address.
- **The remote link** works here too, without any of the above, when internet access is on (next section).

## Over the internet: the remote link

The remote link is a small service on the device (`canworks-link`), built on [iroh](https://iroh.computer), an open-source peer-to-peer library: the PC dials the device by its public key, both ends punch through NAT, and a relay server carries the traffic over HTTPS port 443 when no direct path exists (mobile networks, company networks that block UDP). No account, no router port, no admin rights on the PC.

- **Only paired PCs** get through, and only to the diagnostics port and the runtime's HTTPS port on the device itself. A PC that is not paired can only ask to pair.
- **Pairing uses the diagnostics token.** The first time a PC logs in to the runtime on the local network, the tools prove the token to the link service as well (the same SCRAM login; the token never crosses the network) and the PC is added. By default pairing works only over a direct path from a private or link-local address, so a token alone does not let anyone pair from the internet. Wrong tokens are slowed down and logged: one try per PC a second, 5 failed pairings a minute from one address and 10 in all, where a pairing in progress counts as failed until it succeeds. Listing and removing paired PCs from the configurator checks the token with the same one-try-a-second delay.
- **Internet access is off** until the config turns it on. Off, the service only accepts paired PCs on the local network and contacts no outside server.

The settings are in the config's top-level `diagnostics` object:

```json
"diagnostics": {
  "token_verifier": "SCRAM-SHA-256$4096:...",
  "remote_link": { "internet": true, "relays": ["https://relay.example.com"], "pairing": "lan" }
}
```

| Field | Default | Meaning |
| --- | --- | --- |
| `internet` | `false` | Use relays and publish the device's address so paired PCs reach it from other networks. |
| `relays` | the iroh project's public relays | Relay servers (https URLs, at most 8). |
| `pairing` | `lan` | Where a PC may pair with the token: `lan` (a direct path from a private or link-local address), `anywhere`, or `off` (only `canworks-link allow` on the device). |

The link service applies a changed config a few seconds after an upload (a change of `internet` or `relays` restarts it, so open link sessions reconnect); the bridge only checks these fields.

### Your own relay

The public relays are rate-limited and come with no guarantee: fine for trying it out. For machines in use, run the open-source relay server (`iroh-relay`) on a small Linux server that both sides can reach, with a DNS name and TCP 443 (relaying), TCP 80 (certificate renewal) and UDP 7842 (address discovery) open, and list it in `relays`. The relay only sees encrypted traffic. See the iroh documentation for its configuration.

### Other programs: the OpenPLC Editor and a browser

`canworks-diag link open NAME` keeps local ports open and forwards them to the runtime by the same path choice:

```sh
canworks-diag link open line3
# diagnostics 127.0.0.1:50211
# runtime https://127.0.0.1:50212
```

Each port takes 4 local connections at a time; more wait until one ends. Point the editor's upload at the printed runtime address. The runtime's certificate is the same as on the local network.

CiA 309-3 tools on the PC reach the runtime's gateway over the link too: `canworks-diag --runtime NAME gateway --listen` tunnels through the diagnostics port, the only one the link needs ([cia309-gateway.md](cia309-gateway.md)); the gateway's plain loopback port is never forwarded.

## No network: cable, USB-C or Wi-Fi hotspot

None of these needs the internet; discovery finds the device on each.

- **Ethernet cable:** connect the PC and the device directly. With no DHCP server both fall back to link-local addresses (169.254.x.x) and the connect box lists the device.
- **USB-C cable:** a device with USB gadget mode shows up as a network adapter on the PC (Windows needs an RNDIS driver); when the laptop port powers the device, a powered hub or a separate supply is safer.
- **The device's Wi-Fi hotspot:** `nmcli device wifi hotspot ssid NAME password PASSWORD` (WPA2). Some devices' built-in radios are unstable with a hotspot and a client connection at once: run the hotspot alone, or add a USB Wi-Fi adapter for the second network.
- **A local access point** on the machine, without an internet uplink: the most robust choice for several PCs and devices.

## What the remote link is for, and what not

The link carries diagnostics, commissioning and uploads. Everything that has to be on time runs on the device: SDO transfers, scans, LSS, NMT and trace are executed by the bridge at bus speed, and only the request and the result cross the link. Wi-Fi and relayed paths have delay spikes of hundreds of milliseconds and gaps of seconds, so:

- The tools stretch request timeouts with the measured round trip (at least 4 × round trip + 0.5 s).
- LSS fast scan and a PDO test with a SYNC period ask for confirmation on a relayed path or above 100 ms round trip: they still run on the device, but results and stop commands arrive late.
- Never close a control loop, or carry SYNC or safety traffic, over a remote path.

## Commands

On the PC (`canworks-diag`):

| Command | What it does |
| --- | --- |
| `discover` | Lists the runtimes on the local network. |
| `link id` | This PC's link ID (for `canworks-link allow`). |
| `link list` | Remembered runtimes, whether paired and whether reachable from other networks. |
| `link open NAME` | Local ports to a runtime for other programs, until Ctrl-C. |
| `link unpair NAME` | Removes this PC from the runtime's paired PCs (no token needed) and forgets it. |
| `link forget NAME` | Forgets a runtime on this PC only. |
| `--runtime NAME` | A remembered runtime: directly when it answers, else over the link. `link:NAME` uses only the link. |
| `--repair` | With `--runtime HOST`: a paired runtime that now answers with another link ID (reinstalled, new key) is paired again with its new ID. |

`canworks-deploy --bridge NAME` and `--bridge link:NAME` deploy to a bridge the same way, with the same certificate checks.

On the device (`canworks-link`, settings in `/etc/canworks-link`):

| Command | What it does |
| --- | --- |
| `canworks-link id` | The device's link ID. |
| `canworks-link list` | Paired PCs, with when they were paired and last seen. |
| `sudo canworks-link allow ID [--name NAME]` | Pairs a PC by its link ID, for a PC that cannot pair on the local network. |
| `sudo canworks-link revoke ID\|NAME` | Removes a PC; its open sessions end at once. |

The service logs connections, path changes, pairings and refusals: `journalctl -u canworks-link`. The configurator's Online access section lists paired PCs with **Remove** while connected.

To turn the link or the advertisement on or off later, use the configurator's Devices page ([devices.md](devices.md#remote-link-and-discovery)), or run `install-link.sh` on the device yourself:

```bash
curl -LsSf https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-link.sh | sudo bash -s -- --config /opt/canworks/lib/canworks.json   # link on (newest release)
curl -LsSf .../install-link.sh | sudo bash -s -- --uninstall --keep-discovery     # link off; key, paired PCs and discovery stay
curl -LsSf .../install-link.sh | sudo bash -s -- --discovery-only --config /opt/canworks/lib/canworks.json   # discovery on
curl -LsSf .../install-link.sh | sudo bash -s -- --remove-discovery                # discovery off
```

A bridge's link serves `/etc/canworks-bridge/NAME/canworks.json` with `--runtime-port none`. `--without-discovery` installs the link without the advertisement. The advertisement carries the config's `diagnostics.port` (7531 when it has none); `--diag-port PORT` names another.

## Security

- Never expose 7531 or 8443 to the internet (no port forwarding, no public tunnels): use the remote link or a VPN.
- The remote link needs both a paired key and the token: pairing makes the runtime reachable, the token still gives access. Revoking a PC is immediate.
- `pairing: "lan"` keeps a leaked token from pairing a new PC from the internet; `off` allows only pairing on the device.
- PCs that are not paired get at most 8 connections at a time in all, 2 from one address (a relayed PC counts by its relay) and 2 streams on each; further ones are closed at once. An unpaired connection is closed 30 s after it opened, or as soon as its pairing attempt has failed. Paired PCs connect whatever unpaired PCs hold. The service runs with a memory limit of 128 MB (`MemoryMax=` in its unit).
- The device's key is in `/etc/canworks-link/secret.key` (readable by root only); a PC's in the PC tools' settings folder.
- The remote link is not available on Intel Macs (no iroh package there); direct connections and VPNs work as before.
