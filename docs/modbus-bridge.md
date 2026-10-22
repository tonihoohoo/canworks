# Modbus TCP bridge

`canworks-bridge` runs the CAN networks of a config without an OpenPLC runtime and serves their values as Modbus TCP registers. Any PLC with Modbus client channels, an HMI, a SCADA system or a script then reads CANopen, J1939 and raw CAN values as input registers and writes outputs as holding registers.

The bridge is the same engine as the OpenPLC plugin: it boots and supervises CANopen nodes, claims a J1939 address, sends and receives raw messages, runs simulated devices and serves the diagnostics channel and trace exactly as the plugin does. Only the process image goes to Modbus clients instead of a PLC program. It runs on Linux with SocketCAN, as a systemd service or in a container.

- [Install](#install)
- [A bridge config](#a-bridge-config)
- [The register rule](#the-register-rule)
- [Outputs, the watchdog and client loss](#outputs-the-watchdog-and-client-loss)
- [Status, control, live lists and SDO registers](#status-control-live-lists-and-sdo-registers)
- [Deploying and checking a config](#deploying-and-checking-a-config)
- [Clients](#clients)
- [Security](#security)
- [Limits](#limits)

## Install

### From the configurator

In a bridge project, the configurator's **Devices** workspace (or **Install on device…** on the **Modbus bridge** page) installs the newest bridge on a Linux device over SSH and starts this project's saved config as the instance named after the project folder, with the steps and the log on the page ([devices.md](devices.md)). **Start this project's bridge** there puts a changed config on a device that has the bridge.

### With one line

On the Linux device that has the CAN interfaces, as root. It downloads the newest release (not `main`), builds the bridge and installs it, with no git checkout; running it again updates and restarts the bridges that were running:

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | sudo bash
```

The bridge's EDS lint gets the exact dependency versions the release was tested with (the release's `canworks-<version>-constraints.txt`); from a checkout, `--constraints FILE` or an export of `tools/deploy/uv.lock` when `uv` is installed, else pip picks the newest allowed versions and says so.

To also set up and start a bridge:

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | sudo bash -s -- --instance line1 --config ./line1
```

`--instance NAME --config DIR` also sets up one bridge: it checks `DIR/canworks.json` with `canworks-bridge --check-only`, copies the files of `DIR` (the config and the EDS and DBC files next to it; not subfolders) to `/etc/canworks-bridge/NAME/`, and enables and starts `canworks-bridge@NAME`. A config that fails the check is not copied, and the instance stays as it was. Files already in the instance folder that `DIR` does not have stay.

From a PC onto the device over SSH (the PC needs only `ssh` and `scp`; `sudo` on the device may ask for its password). macOS and Linux:

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.sh | bash -s -- --ssh admin@plc.local [--port 22] [--identity ~/.ssh/id_ed25519] [--instance line1 --config ./line1]
```

Windows (PowerShell, with the OpenSSH client built into Windows 10 and 11):

```powershell
$f = "$env:TEMP\install-bridge.ps1"; irm https://github.com/tonihoohoo/canworks/releases/latest/download/install-bridge.ps1 -OutFile $f; powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f -Ssh admin@plc.local -Instance line1 -Config .\line1
```

`-Port`, `-Identity` and `-Options --without-j1939` go after the file name too.

The bridge's version is in `/opt/canworks-bridge/VERSION` (the bridge's prefix; `--uninstall` removes it). Over SSH, `--config` names a folder on the PC: it is copied to a temporary folder on the device first and removed after the install. Without an SSH key that is three connections, so the device's password may be asked three times. `--version 0.84.0` (`-Version`) installs a given release (0.84.0 or newer, the first with the one-line form); the other options below pass through, for example `--uninstall --purge`. To pin the script itself, put `download/deploy-v<version>` in place of `latest/download` (releases from 0.92.0 on carry the scripts; for older ones use `https://raw.githubusercontent.com/tonihoohoo/canworks/deploy-v0.84.0/scripts/install-bridge.sh`); to read it first, download it and run it with `sudo bash install-bridge.sh`. The device builds Lely and the bridge, which takes several minutes on a small Linux device; the [container image](#container-image) is the quick route where Docker runs.

### From a checkout

On the Linux device, from a checkout of this repository (this installs the checkout, not a release):

```sh
sudo scripts/install-bridge.sh
```

This builds Lely CANopen and dcfgen into `/opt/canworks`, builds `canworks-bridge` into `/opt/canworks/bin`, installs the systemd template unit `canworks-bridge@.service` and creates `/etc/canworks-bridge/`. Both routes take the same options: `--without-canopen` builds J1939 only, `--without-j1939` CANopen only, as for the plugin ([install-stock.md](install-stock.md)). The build needs the OpenPLC runtime's plugin headers (not the runtime itself): the script downloads the runtime release the project pins (`docker/local-runtime/runtime-version`) and stops unless the archive's sha256 matches `docker/local-runtime/runtime-sha256`, or `--runtime-dir DIR` uses a checkout you have. Another release or commit takes `--runtime-ref REF --runtime-sha256 HASH`. `--uninstall` stops every bridge and removes the unit and the binary, and the remote link when it was installed for a bridge (a link the runtime's install set up stays); the configs stay unless you add `--purge`. `--with-link NAME` skips the link when the device's remote link already serves another config (the PLC's). Next to the canworks plugin it leaves the plugin's `VERSION` file and the can-j1939 boot entry, which the plugin uses too. An update restarts every `canworks-bridge@` instance that was running; stopped ones stay stopped.

On a device whose OpenPLC runtime runs in Docker (upstream's managed install), `/opt/canworks` belongs to the runtime's container, which made its Python environment. Without `--prefix` the script then installs the bridge into `/opt/canworks-bridge` and says so (also when an older install left a `canworks-bridge` in `/opt/canworks/bin`), and later updates and `--uninstall` find it there; an explicit `--prefix /opt/canworks` is refused. The paths below then start with `/opt/canworks-bridge`.

Each service instance runs one config:

```sh
sudo mkdir /etc/canworks-bridge/line1
sudo cp canworks.json *.eds /etc/canworks-bridge/line1/
sudo /opt/canworks/bin/canworks-bridge --config /etc/canworks-bridge/line1/canworks.json --check-only
sudo systemctl enable --now canworks-bridge@line1
journalctl -u canworks-bridge@line1
```

Several instances run side by side, each with its own CAN interfaces and Modbus port, for example `canworks-bridge@press` on `can0` and port 502 and `canworks-bridge@feeder` on `can1` and port 1502. One CAN interface belongs to one process: a second bridge, or the OpenPLC plugin, that names an interface already in use logs `CAN interface can0 is owned by another canworks process (process ID 812); not touching it` and leaves that network off. The lock is an abstract Unix socket per interface, so it also holds between a bridge on the host and the plugin in the runtime's Docker container, which runs on the host network.

`--with-link NAME` advertises the bridge `NAME` on the local network and installs the [remote link](remote-access.md) for its diagnostics channel, so the PC tools reach it from other networks; the link reads `/etc/canworks-bridge/NAME/canworks.json` and forwards the diagnostics port only (Modbus TCP is not carried).

To hand an interface from a Docker runtime to a bridge, stop the runtime's bootloader before the runtime, or the bootloader starts the runtime again within seconds: `docker stop openplc-bootloader openplc-runtime`, and `docker start openplc-runtime openplc-bootloader` to give it back.

### Container image

Each release also publishes `ghcr.io/tonihoohoo/canworks-bridge:<version>` for amd64 and arm64. Run it with the host's network, so it sees the CAN interfaces and serves the Modbus port, and mount the config folder:

```sh
docker run -d --restart unless-stopped --network host --cap-add NET_ADMIN \
    -v /srv/bridge/line1:/etc/canworks-bridge ghcr.io/tonihoohoo/canworks-bridge:latest
```

`NET_ADMIN` lets the bridge set the interface's bit rate; leave it out when the interface is already up at the right rate.

## A bridge config

A bridge config is a version 2 config ([config.md](config.md)) with a top-level `bridge` object. Everything else is the same as for the plugin: networks, nodes, J1939, raw messages, simulation and diagnostics. [`examples/modbus-bridge`](../examples/modbus-bridge/canworks.json) is a complete example with two simulated CANopen nodes; it runs without CAN hardware:

```sh
canworks-bridge --config examples/modbus-bridge/canworks.json
```

```json
"bridge": {
  "listen": "0.0.0.0:502",
  "unit_id": 1,
  "word_order": "high_first",
  "max_clients": 16,
  "max_clients_per_address": 4,
  "writers": ["192.168.10.20"],
  "readers": ["192.168.10.0/24"],
  "watchdog_ms": 1000,
  "on_client_loss": "stop",
  "status_location": "%IB24",
  "control_location": "%QB6",
  "live_lists": [ { "network": "field", "location": "%IB32" } ],
  "sdo_bridge_location": { "request": "%QB12", "response": "%IB48" },
  "sdo_bridge_write": false
}
```

| Field | Default | Meaning |
| --- | --- | --- |
| `listen` | required | `address:port` with a numeric address: `0.0.0.0:502` (every IPv4 interface), `[::]:502`, `192.168.10.5:1502`. |
| `unit_id` | 1 | The unit identifier the bridge answers; 0 and 255 are always answered, others get exception 0x0B. |
| `word_order` | `high_first` | Order of the registers of a 32- or 64-bit value. |
| `max_clients` | 16 | Connections at once (1-64); more are closed at once with a log line. When every slot is taken and a writer connects, the oldest connection from a client that may not write is closed to make room. |
| `max_clients_per_address` | 4 | Connections at once from one address (1-64); more are closed at once with a log line. |
| `writers` | required | Addresses or prefixes allowed to write. A write from another client gets exception 0x01 and changes nothing, and does not feed the watchdog. `[]` makes the bridge read-only; `["0.0.0.0/0", "::/0"]` lets every address write. |
| `readers` | every client | Addresses or prefixes allowed to connect at all. An entry of `readers` or `writers` that is not an address or prefix stops the bridge from starting. |
| `watchdog_ms` | 1000 | Outputs off when no write came from a writer for this long; 0 turns the watchdog off. Up to 60000. |
| `on_client_loss` | `stop` | What outputs off means: `stop`, `zero` or `hold` ([below](#outputs-the-watchdog-and-client-loss)). |
| `status_location` | none | Start of the 8-byte status block (`%IB...`). |
| `control_location` | none | Start of the 6-byte control block (`%QB...`). |
| `live_lists` | none | 16-byte live lists of CANopen master networks (`%IB...`). |
| `sdo_bridge_location` | none | The SDO registers: a 14-byte `request` block (`%QB...`) and a 14-byte `response` block (`%IB...`). |
| `sdo_bridge_write` | false | Allow SDO writes through the SDO registers. |

`"sync_source": "plc_cycle"` is refused in a bridge config, since there is no PLC cycle: use `sync_period_us`. The OpenPLC plugin refuses a config with a `bridge` object, and the bridge refuses one without.

### Byte addresses

In a bridge config every location is a byte address: `%IB8` is input byte 8, `%IW8` input bytes 8 and 9, `%ID8` bytes 8 to 11, `%IL8` bytes 8 to 15 and `%IX8.3` bit 3 of byte 8; the same for `%Q`. This differs from the plugin, where each size is its own table and `%IW8` and `%ID8` are different variables. So in a bridge config:

- word, double and long word locations start at an even byte: `%IW3` is refused with `%IW3 must start at an even byte: word locations are whole Modbus registers`;
- two locations may not share a byte: `%ID4` and `%IW6` are refused with `... (%ID4) and ... (%IW6) overlap in input bytes 6 and 7`;
- bits of one byte share it when their bit numbers differ (`%IX16.0` and `%IX16.1`);
- a list of consecutive double words, such as a J1939 trouble code list (`dtcs_location` with `dtcs`), steps 4 bytes per entry: `%ID560` with `dtcs` 3 holds the codes at `%ID560`, `%ID564` and `%ID568`.

The configurator's **Pack for Modbus** (on the Modbus bridge page) and `canworks-deploy --export-modbus-map` work with these rules: packing places data from byte 0 in config order, then the status locations, then the bridge's own blocks, word values word-aligned and bits sharing bytes.

## The register rule

| Location | Modbus |
| --- | --- |
| input byte n (`%IBn`, part of `%IWn`, `%IDn`, `%ILn`) | input register n/2, the high byte when n is even, the low byte when n is odd |
| input bit `%IXn.b` | discrete input n×8+b |
| output byte n | holding register n/2 |
| output bit `%QXn.b` | coil n×8+b |

Values are stored most significant byte first. A 32-bit value at `%ID4` is input registers 2 and 3: with `0x12345678`, register 2 reads `0x1234` and register 3 `0x5678`, or the other way round with `"word_order": "low_first"`. REAL32 and REAL64 objects are served as their IEEE bit patterns, so a client reads them as a float over two or four registers. Holding registers and coils read back the output image. A bit is also visible in its register: `%QX100.1` is coil 801 and bit 1 of the high byte of holding register 50.

An entry's [bit channels](config.md#bit-channels) name bits of the entry's own location: they have no location of their own in a bridge config, and the register map lists each as the discrete input or coil that holds it, named `<node>.<name>` (`dio.jog_x_plus`) or `<entry>.bit<n>`. With `0x6041` at `%IW10` (bytes 10 and 11), statusword bit 3 is discrete input 91 (byte 11, the low byte) and bit 9 is discrete input 81. Writing a coil of an output entry changes only that bit.

The bridge supports functions 1, 2, 3, 4 (read coils, discrete inputs, holding and input registers), 5, 6, 15, 16 (write), 23 (read and write) and 8 (loopback). Addresses outside the image get exception 0x02, more than 125 registers read, 123 registers written or 2000 bits get 0x03. A connection that sent no complete request for 60 s is closed, and so is one that holds an incomplete request for 5 s. Each connection may have at most 8 KB of replies it has not read: while it is over that, the bridge reads no more requests from it, and after 10 s over it the connection is closed (`closing ADDRESS: replies not read`). Requests a client sends ahead wait in its own connection: the bridge reads more only once less than one request is waiting.

Every read is answered from one snapshot of the inputs, and every write is applied as one snapshot of the outputs, so a value over several registers never mixes two bus updates when the client reads or writes it in one request.

`canworks-deploy --config canworks.json --export-modbus-map map.csv` (or `.json`, or `.st` for an ST variable list) writes the register map; the HTML documentation ([network-docs.md](network-docs.md)) has it too, with the suggested client channels: the fewest read and write requests that cover every used register.

## Outputs, the watchdog and client loss

There is no scan. The bridge takes the bus inputs every millisecond, and every accepted write goes to the networks at once: synchronous RPDOs carry it from the next SYNC, event-driven RPDOs from the next SYNC on a network with a SYNC period and at once on one without, and raw and J1939 messages sent on change go out right away. Inputs that react to a rising edge (an SDO variable's trigger, a node's NMT command byte, a raw message's trigger bit) see the edge between two writes, so a client that rewrites the same registers every cycle triggers once.

Every accepted write from a writer feeds the watchdog. When none came for `watchdog_ms`, outputs go off:

- `"stop"` (default): no RPDOs and no raw or J1939 transmit messages. SYNC keeps running, so nodes that send their inputs on SYNC keep sending them (a reading HMI still sees live values), and a node whose RPDO event timer (0x1400 sub-index 5) is set notices the outputs stop and goes to its own safe state.
  The output image is cleared to 0 without sending it, so the write that ends outputs off starts from zeros: one coil written after a loss sends that coil and 0 for every other output, never the values from before the loss. A controller that reconnects should write all its outputs at once.
- `"zero"`: every output location is set to 0 and sent once, then outputs stop as with `"stop"`. The difference to `"stop"` is only that the zeros reach the devices; after both, outputs restart from zeros.
- `"hold"`: outputs keep being sent with their last values.

Inputs, heartbeats, node supervision, the diagnostics channel and J1939 address claim keep running. The next write from a writer ends outputs off. The log names each change (`outputs off by the watchdog (no write from a writer client)`, `outputs on again: a client wrote`). Before the first client writes, the watchdog runs from the bridge's start, so outputs stay off until a writer is there.

## Status, control, live lists and SDO registers

Each block is optional and lives where its location says.

**Status block** (8 input bytes):

| Byte | Meaning |
| --- | --- |
| 0 | 1 running, 2 outputs off by the watchdog, 3 outputs off by the idle command |
| 1 | connected clients |
| 2-3 | a counter that grows every 100 ms (the bridge is alive) |
| 4-5 | the last control counter handled |
| 6 | the result of that command: 0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused (the network's bus is down, or 16 of its NMT commands still wait) |
| 7 | 0 |

**Control block** (6 output bytes): counter (word), command, network index, node, reserved. A command runs once each time the counter changes, so a client that writes the block every cycle sends it once. Commands: 1 run (ends outputs off from idle), 2 idle (outputs off with the `on_client_loss` action, until run), 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for that node of that CANopen master network (node 0: all its nodes). The network index counts the config's networks from 0. An NMT command while the network's CAN interface is down is refused with result 5 and is not sent when the bus comes back; write it again then. At most 16 NMT commands wait per network; a further one is refused the same way.

**Live list** (16 input bytes per CANopen master network): bit n (byte n/8, bit n mod 8) is set while node n is OPERATIONAL.

**SDO registers**: a client reads or writes one object of up to 4 bytes on a node of a CANopen master network.

| Request byte | | Response byte | |
| --- | --- | --- | --- |
| 0-1 | counter | 0-1 | counter echo |
| 2 | command: 1 read, 2 write | 2 | status: 0 idle, 1 busy, 2 done, 3 aborted |
| 3 | network index | 3 | 0 |
| 4 | node | 4-7 | abort code |
| 5 | sub-index | 8-11 | value (a read's result) |
| 6-7 | index | 12-13 | 0 |
| 8 | length in bytes (writes) | | |
| 9 | 0 | | |
| 10-13 | value (writes) | | |

A request starts when its counter changes and goes through the same queue and timeout as the PLC's SDO function blocks. A write needs `"sdo_bridge_write": true`; without it the request ends aborted with 0x08000020 and nothing is sent. Every request is logged.

## Deploying and checking a config

The PC tools check a bridge config like any other: `canworks-deploy --config canworks.json --check-only --bridge HOST` checks it, the configurator's Check does too, and its **Project target** switch turns a project into a bridge project ([configurator.md](configurator.md#project-target)). In a bridge project the configurator hides what the bridge does without: SYNC from the PLC cycle, the scan watchdogs (the bridge's own output watchdog is `bridge.watchdog_ms`) and the OpenPLC Editor project actions. A scan watchdog the config still has is a warning with **Remove**.

To replace the config of a running bridge from the PC, its running config needs the diagnostics channel with changes and uploads allowed:

```json
"diagnostics": { "token_verifier": "SCRAM-SHA-256$...", "allow_changes": true, "allow_config_upload": true }
```

Then:

```sh
canworks-deploy --bridge 192.168.10.5 --config canworks.json --token-file token.txt
```

The tool checks the config, sends it with its EDS files and simulation file over the encrypted channel, and the bridge checks it again, keeps the previous files, restarts on the new ones and reports `ok: canworks-bridge runs the new config`. When the new config does not start (its Modbus port is taken, an interface is missing), the bridge goes back to the previous files and the tool says so. A config the bridge refuses changes nothing. The OpenPLC plugin never takes a config this way.

`canworks-diag --runtime HOST status` shows a bridge line with the output state, the watchdog, the connected clients and the last upload; the configurator's Online view works against a bridge as against a runtime.

## Clients

**A PLC with Modbus TCP client channels:** create one read channel per suggested range (function 4, the start and count from the map) and one write channel (function 16), at a cycle well below `watchdog_ms`. Map the registers to variables with the types from the map: 16-bit values as INT or WORD, 32-bit values as two registers in the bridge's word order. The ST variable list (`--export-modbus-map map.st`) is a starting point for the declarations.

**Node-RED:** `canworks-deploy --export-nodered flow.json` (or **Export Node-RED flow** on the configurator's bridge page) writes a flow for `node-red-contrib-modbus` that reads and writes every value by name, keeps the watchdog fed and wraps the control and SDO registers ([node-red.md](node-red.md)).

**Python** with the standard library only:

```python
import socket, struct

def request(sock, pdu, tid=1, unit=1):
    sock.sendall(struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu)
    head = sock.recv(7)
    return sock.recv(struct.unpack(">HHHB", head)[2] - 1)

s = socket.create_connection(("192.168.10.5", 502))
r = request(s, struct.pack(">BHH", 4, 0, 4))                  # input registers 0-3
print(struct.unpack(">4h", r[2:]))                             # four INTEGER16 values
request(s, struct.pack(">BHHB2H", 16, 1, 2, 4, 1000, 2000))    # holding registers 1-2
```

## CiA 309-3 gateway

With a top-level `cia309` object the bridge also serves the CiA 309-3 ASCII gateway ([cia309-gateway.md](cia309-gateway.md)), exactly as the plugin does: a plain port on its loopback address (default `127.0.0.1:7533`) and sessions through its diagnostics channel (`canworks-diag --runtime HOST gateway`). A CiA 309-3 client reads and, with `cia309.allow_changes`, writes the same nodes the Modbus clients see. Its requests neither feed the output watchdog nor end outputs off: with only a gateway client connected the watchdog runs out as with no client, and the gateway client keeps being served. NMT commands from the gateway follow the gateway's guards and the same hold rules as those of the control block. The bridge's status part lists the gateway sessions (`cia309_sessions`: address, plain or tunnelled, commands served).

## Security

Modbus TCP has no authentication or encryption. Put the bridge on a machine network, not on an office network or the internet, and use `readers` and `writers` so only the PLC or HMI that should write can. Changing the config over the network goes through the encrypted, token-protected diagnostics channel and must be allowed in the running config. The bridge runs as root for the CAN link setup and port 502; the systemd unit limits it to 256 MB of memory (`MemoryMax`) and 64 tasks (`TasksMax`).

## Limits

- Linux with SocketCAN only (the same adapters as the plugin).
- At most 8192 input and 8192 output bytes; a location past them is refused.
- At most 16 connections (`max_clients`, up to 64), 4 per address, and 8 KB of unread replies per connection.
- No Modbus RTU (serial); no Modbus TLS.
- One bridge per CAN interface, and not together with the OpenPLC plugin on that interface.
