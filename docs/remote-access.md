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

1. **Install** the plugin with the link on the device: `sudo scripts/install-stock.sh --with-link` (a bridge: `sudo scripts/install-bridge.sh --with-link NAME`).
2. **Connect once on the local network** with the token, as usual: pick the runtime in the configurator's connect box. The configurator pairs this PC with the runtime in the background.
3. **Tick Reachable from other networks** under **Online access** (Bus and master) and upload the program.

From then on, picking the runtime in the connect box works from anywhere: the tools use its local address when it answers and the link otherwise. The online view shows the path (`LAN`, `internet direct` or `internet relayed`) and the round trip.

## Same network

The device advertises itself on the local network (mDNS, `_canworks._tcp`; installed with the plugin unless `--without-discovery`), so the configurator's connect box lists it by name, and `canworks-diag discover` prints it:

```sh
canworks-diag discover
canworks-diag --runtime line3.local status
```

The advertisement does not depend on the PLC running: a stopped PLC is listed, and connecting says diagnostics are not listening. Typing a host name or address always works. Discovery needs Avahi on the device (`apt-get install avahi-daemon`; Raspberry Pi OS has it).

## Other networks

Discovery does not cross routers. From another subnet, VLAN or site:

- **Routed:** connect to the device's address; open 7531 and 8443 from the engineering subnet only.
- **Through a jump host:** forward both ports over SSH, `ssh -L 7531:DEVICE:7531 -L 8443:DEVICE:8443 user@jumphost`, then use `--runtime 127.0.0.1`.
- **A site VPN or mesh VPN** that makes the device's address reachable works as it is: give that address.
- **The remote link** works here too, without any of the above, when internet access is on (next section).

## Over the internet: the remote link

The remote link is a small service on the device (`canworks-link`), built on [iroh](https://iroh.computer), an open-source peer-to-peer library: the PC dials the device by its public key, both ends punch through NAT, and a relay server carries the traffic over HTTPS port 443 when no direct path exists (mobile networks, company networks that block UDP). No account, no router port, no admin rights on the PC.

- **Only paired PCs** get through, and only to the diagnostics port and the runtime's HTTPS port on the device itself. A PC that is not paired can only ask to pair.
- **Pairing uses the diagnostics token.** The first time a PC logs in to the runtime on the local network, the tools prove the token to the link service as well (the same SCRAM login; the token never crosses the network) and the PC is added. By default pairing works only over a direct path from a private or link-local address, so a token alone does not let anyone pair from the internet. Wrong tokens are slowed down and logged.
- **Internet access is off** until the config turns it on. Off, the service only accepts paired PCs on the local network and contacts no outside server.

The settings are in the config's diagnostics object (`master.diagnostics` in version 1):

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

The link service applies a changed config a few seconds after an upload; the plugin and the bridge only check these fields.

### Your own relay

The public relays are rate-limited and come with no guarantee: fine for trying it out. For machines in use, run the open-source relay server (`iroh-relay`) on a small Linux server that both sides can reach, with a DNS name and TCP 443 (relaying), TCP 80 (certificate renewal) and UDP 7842 (address discovery) open, and list it in `relays`. The relay only sees encrypted traffic. See the iroh documentation for its configuration.

### Other programs: the OpenPLC Editor and a browser

`canworks-diag link open NAME` keeps local ports open and forwards them to the runtime by the same path choice:

```sh
canworks-diag link open line3
# diagnostics 127.0.0.1:50211
# runtime https://127.0.0.1:50212
```

Point the editor's upload at the printed runtime address. The runtime's certificate is the same as on the local network.

## No network: cable, USB-C or Wi-Fi hotspot

None of these needs the internet; discovery finds the device on each.

- **Ethernet cable:** connect the PC and the device directly. With no DHCP server both fall back to link-local addresses (169.254.x.x) and the connect box lists the device.
- **USB-C cable (Raspberry Pi):** the `rpi-usb-gadget` package makes the device a network adapter on the PC. Windows needs the Raspberry Pi RNDIS driver; the laptop port must power the Pi, so a powered hub or a separate supply is safer.
- **The device's Wi-Fi hotspot:** `nmcli device wifi hotspot ssid NAME password PASSWORD` (WPA2). On a Raspberry Pi with Trixie, run the hotspot alone or add a USB Wi-Fi adapter for a second network: the built-in radio's firmware is unstable with a hotspot and a client connection at once.
- **A local access point** on the machine, without an internet uplink: the most robust choice for several PCs and devices.

## What the remote link is for, and what not

The link carries diagnostics, commissioning and uploads. Everything that has to be on time runs on the device: SDO transfers, scans, LSS, NMT and trace are executed by the plugin at bus speed, and only the request and the result cross the link. Wi-Fi and relayed paths have delay spikes of hundreds of milliseconds and gaps of seconds, so:

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

`canworks-deploy --runtime NAME` and `--runtime link:NAME` deploy the same way, with the same certificate checks.

On the device (`canworks-link`, settings in `/etc/canworks-link`):

| Command | What it does |
| --- | --- |
| `canworks-link id` | The device's link ID. |
| `canworks-link list` | Paired PCs, with when they were paired and last seen. |
| `sudo canworks-link allow ID [--name NAME]` | Pairs a PC by its link ID, for a PC that cannot pair on the local network. |
| `sudo canworks-link revoke ID\|NAME` | Removes a PC; its open sessions end at once. |

The service logs connections, path changes, pairings and refusals: `journalctl -u canworks-link`. The configurator's Online access section lists paired PCs with **Remove** while connected.

## Security

- Never expose 7531 or 8443 to the internet (no port forwarding, no public tunnels): use the remote link or a VPN.
- The remote link needs both a paired key and the token: pairing makes the runtime reachable, the token still gives access. Revoking a PC is immediate.
- `pairing: "lan"` keeps a leaked token from pairing a new PC from the internet; `off` allows only pairing on the device.
- The device's key is in `/etc/canworks-link/secret.key` (readable by root only); a PC's in the PC tools' settings folder.
- The remote link is not available on Intel Macs (no iroh package there); direct connections and VPNs work as before.
