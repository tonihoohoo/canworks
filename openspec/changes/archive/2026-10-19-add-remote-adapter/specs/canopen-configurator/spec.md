## MODIFIED Requirements

### Requirement: Connect panel
**Connect…** in the connection bar SHALL open one connect panel, and the panel SHALL be the only place to connect. No page SHALL have a connect form or a button that opens the panel.

The panel SHALL list first up to three recent connections of this PC of the kinds it offers, each connectable with one click. A recent adapter connection SHALL still run the bit rate check and SHALL start with Allow changes off. Recent connections SHALL be kept in the configurator's settings on this PC without tokens. The panel SHALL NOT open by itself on entering Commission.

In Commission a device the panel SHALL offer two targets, **USB adapter** (the default) and **Adapter on another machine**:
- USB adapter: the found adapters with Refresh, or a typed target; the bit rate, picked by the user, with no detection and no default; "Device's node ID, to check the bit rate", for adapters that cannot report a sent frame; **Allow changes**, unticked; **Connect**;
- Adapter on another machine: the adapter servers found on the local network and a host field (`HOST[:PORT]`, port 7536 when not given); the server's adapter and bit rate once known; the token prompt when this PC has no token for that host, the token then kept on this PC per host; **Allow changes**, unticked; **Connect**.

A refused bit rate check SHALL keep the panel open with the reason and the form filled in.

With a config the panel SHALL offer three targets, **Runtime** (the default), **Standalone simulator** and **Adapter on another machine**:
- Runtime: the found and remembered runtimes, the host field and **Local simulator runtime**; the token prompt when this PC has no matching token; **Connect**;
- Standalone simulator: a running `canworks-sim` by address (`HOST[:PORT]`, port 7532 when not given) and its token when it was started with one, both kept on this PC per project folder; **Connect**;
- Adapter on another machine: as in Commission a device, with a warning when the server's bit rate differs from the network's.

When the config's online access is off, the Runtime target SHALL say so and link to Configure → Bus and master; the other targets SHALL still work.

The last target (including Runtime, Standalone simulator or Adapter on another machine) and bit rate SHALL be kept in the configurator's settings on this PC, never in a project.

#### Scenario: Wrong bit rate refused
- **WHEN** the bus runs at 500 kbit/s and the user connects at 1000 kbit/s in the panel
- **THEN** the panel stays open, says the bus does not run at 1000 kbit/s, and the user can pick 500 kbit/s and connect without replugging the adapter

#### Scenario: Runtime needs a token
- **WHEN** the user picks a found runtime and this PC has no token for the config
- **THEN** the panel asks for the token, accepts it only if it matches the config's verifier, and connects

#### Scenario: Disconnect frees the adapter
- **WHEN** the user presses Disconnect in the bar while connected to an adapter
- **THEN** the adapter is closed, the scan, PDO test, SYNC, send jobs and trace recording on it stop, and `canworks-diag --adapter` can open the same adapter

#### Scenario: Reconnect to the last adapter
- **WHEN** the user opens Commission a device on a PC that last connected to gs_usb:0 at 500 kbit/s and presses Connect… in the connection bar
- **THEN** the panel lists "gs_usb:0 at 500 kbit/s" first, and one click connects after the bit rate check with Allow changes off

#### Scenario: Standalone simulator
- **WHEN** the user picks Standalone simulator in the panel, enters 127.0.0.1:7532 and presses Connect
- **THEN** the panel closes, the connection bar shows the simulator's address and Disconnect, and Simulation shows its devices

#### Scenario: Adapter on another machine
- **WHEN** the user opens Commission a device, picks Adapter on another machine, chooses the found server `linuxbox`, enters its token and presses Connect
- **THEN** the connection bar shows the adapter and `linuxbox` with the round trip, and the commission pages work on linuxbox's bus; the next time the token is not asked again

#### Scenario: Bit rate differs from the network
- **WHEN** with a config whose network runs at 250 kbit/s the user picks an adapter server serving 500 kbit/s
- **THEN** the panel warns that the server runs the bus at 500 kbit/s and the network is set to 250 kbit/s before Connect
