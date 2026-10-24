# Modbus TCP bridge

`canworks-bridge` runs the CAN networks of a config without an OpenPLC runtime and serves their values as Modbus TCP registers. Any PLC with Modbus client channels, an HMI, a SCADA system or a script then reads CANopen, J1939 and raw CAN values as input registers and writes outputs as holding registers.

The bridge is canworks' engine: it boots and supervises CANopen nodes, claims a J1939 address, sends and receives raw messages, runs simulated devices and serves the diagnostics channel and trace. Its process image goes to Modbus clients, the config's [connections](#connections): an OpenPLC Runtime on the same device ([OpenPLC](#openplc)), another PLC, a Node-RED flow, an HMI, SCADA system or script. It runs on Linux with SocketCAN, as a systemd service or in a container.

- [Install](#install)
- [A bridge config](#a-bridge-config)
- [The register rule](#the-register-rule)
- [Outputs, the watchdog and client loss](#outputs-the-watchdog-and-client-loss)
- [Status, control, live lists and SDO registers](#status-control-live-lists-and-sdo-registers)
- [Connections](#connections)
- [OpenPLC](#openplc)
- [Deploying and checking a config](#deploying-and-checking-a-config)
- [When the bridge fails](#when-the-bridge-fails)
- [Clients](#clients)
- [Security](#security)
- [Limits](#limits)

## Install

### From the configurator

The configurator's **Devices** workspace (or **Install on device…** on the **Modbus bridge** page) installs the newest bridge on a Linux device over SSH and starts this project's saved config as the instance named after the project folder, with the steps and the log on the page ([devices.md](devices.md)). **Start this project's bridge** there puts a changed config on a device that has the bridge.

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

The bridge's version is in `/opt/canworks/VERSION` (the bridge's prefix; `--uninstall` removes it). Over SSH, `--config` names a folder on the PC: it is copied to a temporary folder on the device first and removed after the install. Without an SSH key that is three connections, so the device's password may be asked three times. `--version 0.84.0` (`-Version`) installs a given release (0.84.0 or newer, the first with the one-line form); the other options below pass through, for example `--uninstall --purge`. To pin the script itself, put `download/deploy-v<version>` in place of `latest/download` (releases from 0.92.0 on carry the scripts; for older ones use `https://raw.githubusercontent.com/tonihoohoo/canworks/deploy-v0.84.0/scripts/install-bridge.sh`); to read it first, download it and run it with `sudo bash install-bridge.sh`. The device builds Lely and the bridge, which takes several minutes on a small Linux device; the [container image](#container-image) is the quick route where Docker runs.

### From a checkout

On the Linux device, from a checkout of this repository (this installs the checkout, not a release):

```sh
sudo scripts/install-bridge.sh
```

This builds Lely CANopen and dcfgen into `/opt/canworks`, builds `canworks-bridge` into `/opt/canworks/bin`, installs the systemd template unit `canworks-bridge@.service` and creates `/etc/canworks-bridge/`. With CANopen it also installs the [CANopen simulator](simulator.md) `canworks-canopen-sim` into `/opt/canworks/bin`. Both routes take the same options: `--without-canopen` builds J1939 only (no Lely or dcfgen), `--without-j1939` CANopen only; with J1939 the script loads the kernel module `can-j1939` and lists it in `/etc/modules-load.d/canworks-j1939.conf`. The build needs this source, Lely CANopen and the system's libraries only. `--uninstall` stops every bridge and removes the unit and the binaries, and the remote link when it was installed for a bridge; the configs and the OpenPLC Runtime stay, and `--purge` also removes the configs. An update restarts every `canworks-bridge@` instance that was running; stopped ones stay stopped.

The script installs canworks only. For an OpenPLC PLC on the same device, install the OpenPLC Runtime first with [upstream's installer](https://github.com/Autonomy-Logic/openplc-runtime); the bridge runs next to it and changes nothing in it.

Each service instance runs one config:

```sh
sudo mkdir /etc/canworks-bridge/line1
sudo cp canworks.json *.eds /etc/canworks-bridge/line1/
sudo /opt/canworks/bin/canworks-bridge --config /etc/canworks-bridge/line1/canworks.json --check-only
sudo systemctl enable --now canworks-bridge@line1
journalctl -u canworks-bridge@line1
```

Several instances run side by side, each with its own CAN interfaces and Modbus port, for example `canworks-bridge@press` on `can0` and port 502 and `canworks-bridge@feeder` on `can1` and port 1502. One CAN interface belongs to one process: a second bridge that names an interface already in use logs `CAN interface can0 is owned by another canworks process (process ID 812); not touching it` and leaves that network off. The lock is an abstract Unix socket per interface, so it also holds between a bridge on the host and one in a container on the host network.

`--with-link NAME` advertises the bridge `NAME` on the local network and installs the [remote link](remote-access.md) for its diagnostics channel, so the PC tools reach it from other networks; the link reads `/etc/canworks-bridge/NAME/canworks.json` and forwards the diagnostics port only (Modbus TCP is not carried).

### Container image

Each release also publishes `ghcr.io/tonihoohoo/canworks-bridge:<version>` for amd64 and arm64. Run it with the host's network, so it sees the CAN interfaces and serves the Modbus port, and mount the config folder:

```sh
docker run -d --restart unless-stopped --network host --cap-add NET_ADMIN \
    -v /srv/bridge/line1:/etc/canworks-bridge ghcr.io/tonihoohoo/canworks-bridge:latest
```

`NET_ADMIN` lets the bridge set the interface's bit rate; leave it out when the interface is already up at the right rate.

## A bridge config

A bridge config is a version 2 config ([config.md](config.md)) with a top-level `bridge` object. Everything else is a normal config: networks, nodes, J1939, raw messages, simulation and diagnostics. [`examples/modbus-bridge`](../examples/modbus-bridge/canworks.json) is a complete example with two simulated CANopen nodes; it runs without CAN hardware:

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
| `max_clients_per_address` | 4 | Connections at once from one address (1-64); more are closed at once with a log line, except a writer's: it takes the slot of its own address's longest-idle connection. |
| `writers` | required | Addresses or prefixes allowed to write. A write from another client gets exception 0x01 and changes nothing, and does not feed the watchdog. `[]` makes the bridge read-only; `["0.0.0.0/0", "::/0"]` lets every address write. |
| `readers` | every client | Addresses or prefixes allowed to connect at all. An entry of `readers` or `writers` that is not an address or prefix stops the bridge from starting. |
| `watchdog_ms` | 1000 | Outputs off when no write came from a writer for this long; 0 turns the watchdog off. Up to 60000. |
| `on_client_loss` | `stop` | What outputs off means: `stop`, `zero`, `hold`, `preop` or `safe` ([below](#outputs-the-watchdog-and-client-loss)). |
| `safe_values` | none | With `"safe"`: the value each output location takes while outputs are off, `{ "%QW10": 500, "%QX3.0": true }`; every other output is 0 ([below](#safe-values)). |
| `status_location` | none | Start of the 8-byte status block (`%IB...`). |
| `control_location` | none | Start of the 6-byte control block (`%QB...`). |
| `live_lists` | none | 16-byte live lists of CANopen master networks (`%IB...`). |
| `sdo_bridge_location` | none | The SDO registers: a 14-byte `request` block (`%QB...`) and a 14-byte `response` block (`%IB...`). |
| `sdo_bridge_write` | false | Allow SDO writes through the SDO registers. |
| `connections` | none | The programs and tools that use the registers ([Connections](#connections)). The bridge does not read them; the PC tools check them. |
| `plc_link` | false | The PLC link for any client: the map hash at input registers 0-1 and the header at holding registers 0-2 ([OpenPLC](#openplc)); needed by an OpenPLC connection and the [PLCopen XML export](plcopen.md). `false` with an OpenPLC connection is refused. |

The bridge refuses a config without a `bridge` object, naming the configurator's **Use with canworks-bridge** for a config made for the removed canworks plugin, and a CODESYS config. The removed `openplc` field is refused with one message: OpenPLC is a connection.

### Byte addresses

In a bridge config every location is a byte address: `%IB8` is input byte 8, `%IW8` input bytes 8 and 9, `%ID8` bytes 8 to 11, `%IL8` bytes 8 to 15 and `%IX8.3` bit 3 of byte 8; the same for `%Q`. So in a bridge config:

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

The bridge supports functions 1, 2, 3, 4 (read coils, discrete inputs, holding and input registers), 5, 6, 15, 16 (write), 23 (read and write), 8 (loopback) and 43 with MEI type 14 ([device identification](#device-identification)). Addresses outside the image get exception 0x02, more than 125 registers read, 123 registers written or 2000 bits get 0x03. A connection that sent no complete request for 60 s is closed, and so is one that holds an incomplete request for 5 s. Every connection uses TCP keepalive (5 s idle, 2 s interval, 3 probes), so one whose peer lost power or its network is closed within about 11 s. Each connection may have at most 8 KB of replies it has not read: while it is over that, the bridge reads no more requests from it, and after 10 s over it the connection is closed (`closing ADDRESS: replies not read`). Requests a client sends ahead wait in its own connection: the bridge reads more only once less than one request is waiting.

<a id="device-identification"></a>**Device identification.** Function 43 with MEI type 14 (Read Device Identification) answers every client, also one that may not write, for every config, with or without the PLC link. It is how a client checks that it was made for the map the bridge serves (the Node-RED package does it at connect):

| Object | Value |
| --- | --- |
| 0x00 VendorName | `canworks` |
| 0x01 ProductCode | `canworks-bridge` |
| 0x02 MajorMinorRevision | the bridge version, as `canworks-bridge --version` prints it |
| 0x80 (private) | the map hash as 8 upper-case hex digits (`1234ABCD`), the `map hash 0x1234abcd` of the log and `canworks-diag status` |

The request is `2B 0E <read code> <object id>`. Read code 1 (basic) and 2 (regular, which has no objects of its own) give objects 0x00-0x02, 3 (extended) objects 0x00-0x02 and 0x80, each from the object asked for (an object that is not in that list starts the list at 0x00); 4 gives the one object asked for, and an object other than these four gets exception 0x02. The answer is `2B 0E <read code> 83 00 00 <number of objects>`, then per object its id, its length in bytes and its ASCII text: conformity level 0x83 (extended, stream and individual access), no more to follow, every answer in one response. For example `2B 0E 04 80` gets `2B 0E 04 83 00 00 01 80 08 31 32 33 34 41 42 43 44`. Read code 0 or above 4, or a request that is not 4 bytes long, gets exception 0x03; function 43 with any other MEI type gets exception 0x01, which is also what a bridge from before this function answers.

Every read is answered from one snapshot of the inputs, and every write is applied as one snapshot of the outputs, so a value over several registers never mixes two bus updates when the client reads or writes it in one request.

`canworks-deploy --config canworks.json --export-modbus-map map.csv` (or `.json`, or `.st` for an ST variable list) writes the register map; the HTML documentation ([network-docs.md](network-docs.md)) has it too, with the suggested client channels: the fewest read and write requests that cover every used register.

## Outputs, the watchdog and client loss

There is no scan. The bridge takes the bus inputs every millisecond, and every accepted write goes to the networks at once: synchronous RPDOs carry it from the next SYNC, event-driven RPDOs from the next SYNC on a network with a SYNC period and at once on one without, and raw and J1939 messages sent on change go out right away. Inputs that react to a rising edge (an SDO variable's trigger, a node's NMT command byte, a raw message's trigger bit) see the edge between two writes, so a client that rewrites the same registers every cycle triggers once.

Every accepted write from a writer feeds the watchdog. When none came for `watchdog_ms`, outputs go off:

- `"stop"` (default): no RPDOs and no raw or J1939 transmit messages. SYNC keeps running, so nodes that send their inputs on SYNC keep sending them (a reading HMI still sees live values), and a node whose RPDO event timer (0x1400 sub-index 5) is set notices the outputs stop and goes to its own safe state.
  The output image is cleared to 0 without sending it, so the write that ends outputs off starts from zeros: one coil written after a loss sends that coil and 0 for every other output, never the values from before the loss. A controller that reconnects should write all its outputs at once.
- `"zero"`: every output location is set to 0 and sent once, then outputs stop as with `"stop"`. The difference to `"stop"` is only that the zeros reach the devices; after both, outputs restart from zeros.
- `"hold"`: outputs keep being sent with their last values.
- `"preop"`: outputs stop as with `"stop"`, and every configured node of every CANopen master network is sent NMT enter pre-operational, one command per node (not node 0, so devices canworks does not manage are left alone), and each applies its own communication-loss behaviour. Outputs on again sends NMT start the same way. The log names the client loss as the cause.
- `"safe"`: every output is set to its safe value from `safe_values` (0 where none is given) and kept sent, like `"hold"` with chosen values, so RPDO event timers stay fed and the devices hold a known state.

| Action | What is sent while outputs are off | Next write starts from |
|---|---|---|
| `stop` | nothing | zeros |
| `zero` | zeros once, then nothing | zeros |
| `hold` | the last values, on every SYNC or change | the last values |
| `preop` | nothing; each node is put pre-operational | zeros |
| `safe` | the safe values, on every SYNC or change | the safe values |

Inputs, heartbeats, node supervision, the diagnostics channel and J1939 address claim keep running. The next write from a writer ends outputs off. The log names each change (`outputs off by the watchdog (no write from a writer client)`, `outputs on again: a client wrote`). Before the first client writes, the watchdog runs from the bridge's start, so outputs stay off until a writer is there. With `"safe"`, outputs off sends the safe values, so they are on the bus from the bridge's start until the first write.

### Safe values

`safe_values` maps output locations to values: a number for an integer or REAL entry, `true` or `false` (or 1, 0) for a bit, and a decimal string for a 64-bit integer beyond 2^53. Each key must be an output bound to an RPDO entry, a J1939 or raw transmit signal (or a raw message's data), a slave's output object or a J1939 DTC's active bit, and the value must fit that binding's type: the bridge refuses the config otherwise, with the location, what it is bound to and the range (for example `bridge.safe_values: %QB0 (... RPDO 1 object 0x6200:1): 300 is out of range 0-255`). A bit inside a bound word (a bit channel) takes its own value, applied after the whole values. NMT command bytes, SDO variables and their triggers, raw trigger and enable bits and the bridge's own blocks cannot take safe values. `safe_values` with another action is a warning, as they are not used.

The values are written to the output image in the bus's byte order and the map's word order (`word_order`), as a client writing them would. The map exports (CSV, JSON, ST comments, HTML) show each output's safe value while the action is `"safe"`. The map hash does not include them: changing a safe value does not stop a PLC that uses the PLC link.

On a clean stop (`systemctl stop`, SIGTERM) the bridge first writes the safe values and waits one SYNC period (20 to 200 ms) so synchronous RPDOs and messages sent on change carry them, then stops the nodes as `on_plc_stop` says. A crash or a power loss sends nothing: the devices' own communication-loss settings cover that. Check each safe value against the device's manual: it is what the machine does when the PLC is gone.

## Status, control, live lists and SDO registers

Each block is optional and lives where its location says.

**Status block** (8 input bytes):

| Byte | Meaning |
| --- | --- |
| 0 | 1 running, 2 outputs off by the watchdog, 3 outputs off by the idle command, 4 outputs off: the PLC program was built for another map, 5 outputs off: the PLC stopped (both `openplc` only) |
| 1 | connected clients |
| 2-3 | a counter that grows every 100 ms (the bridge is alive) |
| 4-5 | the last control counter handled |
| 6 | the result of that command: 0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused (the network's bus is down, or 16 of its NMT commands still wait), 6 not run because the bridge restarted (OpenPLC configs, [below](#after-a-bridge-restart)) |
| 7 | flags: bit 0 set for the whole run when the previous run of this config did not stop cleanly ([below](#when-the-bridge-fails)); the other bits 0 |

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

A request starts when its counter changes and goes through the same queue and timeout as the PLC's SDO function blocks. A write needs `"sdo_bridge_write": true`; without it the request ends aborted with 0x08000020 and nothing is sent. Requests are logged at debug level, and aborts and timeouts at info level, so a program that reads every scan does not fill the journal.

#### After a bridge restart

A PLC writes its whole output image every poll, so after a bridge restart the PLC's last control block and SDO request are still there. With the PLC link (`plc_link`, which an OpenPLC connection turns on) the bridge takes the first control block and SDO request it gets after a start as the last ones handled and does not run them: the status block echoes that counter with result 6, and the SDO response shows it aborted with 0x08000021. The canworks blocks report both as ERROR_ID 8; start the block again. Clients without the PLC link usually write a block only when they send a command, so their first command runs; such a client that rewrites its outputs cyclically can write counter 0 back after its command ended.

## Function block mailboxes

`bridge.mailboxes` gives the [function blocks](plc-library.md#the-mailboxes) (long SDO transfers, CAN frames, J1939 messages and trouble codes, EMCY) their registers. Any Modbus client can use them; the library's blocks do it for a PLC program. A config without `mailboxes` has none, and that is the default: every client polls them on every cycle, so they are on only when a program uses them ([plc-library.md](plc-library.md#with-or-without-the-mailboxes)). With mailboxes, the status answer has `bridge.mailboxes` with `operations` and `receivers_opened` since the start, and `info_reads` (reads of the network info blocks and the cyclic job table, which blocks like `CAN_BUS_INFO` use without a request), which `canworks-diag status` prints.

```json
"mailboxes": { "requests": 1, "receive": true, "cyclic_jobs": 4, "network_info": true,
               "input_location": "%IB66", "output_location": "%QB32" }
```

| Field | Default | Meaning |
| --- | --- | --- |
| `requests` | 1 | Request mailboxes, 0 to 4: operations that run at the same time. Opening a receiver or a cyclic job takes one, so 0 is refused while `receive` is on or `cyclic_jobs` is above 0. |
| `receive` | true | The receive mailbox for CAN, J1939 and EMCY receivers. |
| `receive_blocks` | 1 | Receive mailbox blocks of 120 registers, 1 or 2. Two carry more than twice the records per batch, for one more Modbus request per mailbox poll ([throughput](#receive-throughput)). |
| `cyclic_jobs` | 4 | Cyclic frame jobs, 0 to 16. |
| `network_info` | true | A network info block for each of the first 8 networks. |
| `input_location`, `output_location` | required | Where the input and output areas start, at an even byte. Pack for Modbus and the configurator's Suggest set them. |

The input area holds, in this order: one response block per request mailbox (72 registers each), the receive mailbox (120 registers per receive block), the network info blocks (18 registers each) and the cyclic job table (a tick and 4 registers per job). The output area holds one request block per request mailbox (72 registers each), the receive acknowledgement (3 registers) and one keepalive register per cyclic job. The default mailboxes with one network take 227 input and 79 holding registers. Each block is a located value of the map hash, and neither OpenPLC's register groups nor the suggested client channels ever cut one over two requests. The bridge logs the ranges at start.

**Request mailboxes.** A request block holds a counter (word 0), the operation and network index (word 1: operation in the high byte), six arguments (words 2-7) and 128 data bytes (words 8-71, byte 2k in the high byte of word 8 + k). An operation starts once each time the counter changes to a value other than the response's echo; the response echoes the counter with state busy, then done or error with an ERROR_ID (word 1: state in the high byte), the results in words 2-7 and the first 128 bytes of the answer. Rewriting the same request starts nothing. Operations:

| Op | Name | What it does |
| --- | --- | --- |
| 1 | STAGE | Puts the request's data bytes into the mailbox's 1785-byte staging buffer at an offset, for a long SDO write or J1939 send. |
| 2 | FETCH | Gives 128 bytes of the last answer from an offset. |
| 3, 4 | SDO_READ, SDO_WRITE | An SDO transfer of up to 1785 bytes on a CANopen master network's node, through the same queue as the SDO registers; writes need `sdo_bridge_write`. |
| 5 | CAN_SEND | One frame, done when the adapter confirms it, with the network's protocol identifier guard. |
| 6, 7 | CYCLIC_SET, CYCLIC_STOP | Starts or changes, and stops, a frame the bridge sends from its own timer every 1 ms to 60 s. |
| 8, 9, 10 | RX_OPEN, RX_CLOSE, RX_FETCH | Opens and closes a CAN, J1939 or EMCY receiver; RX_FETCH gives a received J1939 message longer than 8 bytes. |
| 11, 12 | J1939_SEND, J1939_REQUEST | A J1939 message from the network's address (the transport protocol above 8 bytes), or a request and its answer. |
| 13, 14 | DM_READ, DM_CLEAR | An ECU's trouble codes (its latest DM1 without bus traffic, or DM2 by request) and DM3/DM11. |
| 15 | FIND_ECU | The address of an ECU by NAME and mask. |

The ERROR_IDs are those of the matching block family ([plc-library.md](plc-library.md#sdo-blocks), [raw-can.md](raw-can.md#error-ids), [j1939.md](j1939.md#error-ids)). Each mailbox runs one operation at a time; different mailboxes run in parallel.

**Receive mailbox.** For each open receiver the bridge keeps a queue (CAN up to 256 frames, J1939 up to 32 messages, EMCY its place in the network's history of 64) and shows the records in batches: word 0 the batch sequence, words 1-2 the receivers present in it, word 3 the record words used, word 4 a millisecond tick, words 5-20 each receiver number's generation, words 21-24 the batch time (the UTC receive time in microseconds of the batch's first, oldest record), then the records, in arrival order across all receive blocks. Each record has its receiver, kind and flags, the records still queued and the dropped count; a CAN record (10 words) adds the identifier, format, DLC and 8 data bytes, a J1939 record (12 words) the PGN, addresses, priority, length and the first 8 bytes, and an EMCY record (12 words) its own UTC receive time, node, error register, error code and 5 bytes. CAN and J1939 records share the batch time. The next batch comes once the acknowledgement names the current sequence with no receiver still pending. A batch that is not acknowledged within 1 s (5 s while a long J1939 message is being fetched) closes the receivers still pending and moves on, logged once, so a reader that stopped does not hold up the others. At most 32 receivers are open at once.

<a id="receive-throughput"></a>**Receive throughput.** A batch holds 95 record words with one receive block and 215 with two: 9 or 21 CAN frames, 7 or 17 J1939 messages or EMCYs. A client that reads all its registers and then writes the acknowledgement, as OpenPLC's Modbus master does, sees the next batch one poll after the acknowledgement, so it gets one batch every two polls:

    frames/s = records per batch × polls per second / 2

At OpenPLC's default 10 ms poll that is about 450 CAN frames/s with one receive block and 1050 with two (measured with the runtime's own master: 444 and 1036; on a Raspberry Pi 5 bench one block took about 458 frames/s and two took 1000 frames/s without loss); a 5 ms poll doubles it. The bridge's own part is under 1 ms. OpenPLC polls the mailboxes every mailbox poll of its connection, 50 ms by default, which gives about 90 and 210 ([plc-library.md](plc-library.md#the-mailboxes)). The configurator's Function blocks section shows the rate for the config's mailbox poll.

**Network info** (18 registers per network, every 100 ms): CAN state and bus load, error counters, bus-offs, frames received and sent, error frames, and for a J1939 network its claim state, address, NAME and ECU count.

**Cyclic jobs.** The table shows each job's state, ERROR_ID, generation and frame count. A job whose keepalive register has not changed for 1 s is stopped, so a client that went away does not leave a frame running.

**When the link stops.** When the PLC link header says stopped or another map, the watchdog fires, or the control block sets idle, the bridge cancels every running operation, stops every cyclic job, closes every receiver and empties the receive mailbox; a CANopen session restart (its interface went down and up) does the same for that network only. One log line says how many it ended and why (`idle`, `the watchdog`, ...). Cancelled (ERROR_ID 8) means the result is discarded: an SDO transfer or a frame still waiting in its queue (behind another transfer to the same node, say) is dropped and never sent, but one already on the bus finishes and may have reached the device.

**After a bridge restart.** A PLC rewrites its last request with every poll, so the first request words a mailbox gets from a client after the bridge starts only set its counter: they end with ERROR_ID 8 and are not run, and the client's next counter runs. Until a client has written a mailbox's request words, the mailbox answers nothing.

## Connections

`bridge.connections` lists the programs and tools that use the registers, so they travel with the project. The bridge does not read the list; the PC tools check it, and the configurator's **Modbus bridge** page shows it first, with **Add connection** and each connection's files.

```json
"connections": [
  { "kind": "openplc", "name": "OpenPLC", "address": "127.0.0.1", "writes": true },
  { "kind": "hmi", "name": "Line HMI", "address": "192.168.10.20", "writes": false, "format": "csv",
    "map_hash": "0x1a2b3c4d" }
]
```

Every connection has `kind`, a unique `name` (1-64 characters), `address` (the client's IP address), `writes` and, once downloaded, `map_hash`. `openplc` and `plc` also take `inputs_on_loss`: `hold` (the default) keeps the typed inputs at their last values while `canworks.ok` is FALSE, `zero` sets them to 0; status, state and timeout values read 0 either way ([plc-library.md](plc-library.md#when-the-bridge-is-lost)). The kinds and their own fields:

| Kind | Fields | What it gets |
| --- | --- | --- |
| `openplc` | `poll_ms` (5-1000, default 10), `mailbox_poll_ms`, `remote_device` (default `canworks`), `iec_base` | The editor files, kept in sync by Save in an editor project ([OpenPLC](#openplc)). At most one; its address is `127.0.0.1`. |
| `plc` | `format` (`plcopen` or `st`), `library`, `bridge_host`, `blocks` | The PLCopen XML folder as a zip ([plcopen.md](plcopen.md)), or the PLC link as ST ([plc-library.md](plc-library.md#on-another-modbus-plc)). |
| `nodered` | `period_ms` (10-60000), `bridge_host`, `blocks` | The Node-RED flow ([node-red.md](node-red.md)). |
| `hmi` | `format` (`csv`, `json` or `st`) | The register map or the ST variable list. |

A connection's **Download** gives the same file as the command line (`--export-modbus-map`, `--export-nodered`, `--export-plcopen`) and stores the map hash in `map_hash`; when the map changes, or a setting that goes into the file (`inputs_on_loss`) changes, which the configurator marks with `"stale": true`, the row says **Out of date** and Problems warns until the next download. An Other PLC connection whose Download would be refused (no PLC link) says **Cannot download** with the reason, and Problems warns before anyone presses Download; `canworks-deploy --check` prints the same warnings.

`blocks` says which canworks mailbox blocks the client's program uses: `none` (the default), `sdo_send` (one request mailbox: long SDOs, `CAN_SEND`, the J1939 requests), `receive` (also the receive mailbox) or `all` (also 4 cyclic jobs and network info). Picking one in the configurator turns on those parts of [`bridge.mailboxes`](#function-block-mailboxes) and places them, in the same undo step. One program owns the mailboxes, since their request words, tickets and receivers assume one client: the check refuses a second connection with `blocks`, any next to an `openplc` connection (its program's blocks decide), and `blocks` on a `nodered` connection with the PLC link (the flow is read-only then). A connection whose `blocks` needs a part that is off is an error in Problems with **Turn on what the program uses**; mailboxes that neither a connection nor the OpenPLC program needs are a warning with **Turn off the mailboxes**.

The writers follow the connections: while there are connections, `writers` is the sorted addresses of those with `writes` true, and the check warns when they differ. A connection on the network while `listen` is a loopback address is an error naming it. With the PLC link, only the PLC writes outputs and mailboxes: a Node-RED or HMI connection that writes gets a warning.

## OpenPLC

A bridge config with an OpenPLC connection runs the networks next to an unmodified OpenPLC Runtime v4 on the same device, and the runtime's own Modbus master reads and writes the registers. Nothing of canworks runs inside the runtime, so an OpenPLC update changes nothing for canworks as long as the Modbus master and the editor's remote device format stay.

```json
"bridge": {
  "connections": [ { "kind": "openplc", "name": "OpenPLC", "address": "127.0.0.1", "writes": true, "poll_ms": 10 } ],
  "plc_link": true,
  "listen": "127.0.0.1:1502",
  "writers": [ "127.0.0.1" ],
  "word_order": "low_first",
  "watchdog_ms": 50,
  "control_location": "%QB34",
  "sdo_bridge_location": { "request": "%QB40", "response": "%IB60" },
  "sdo_bridge_write": true
}
```

| Connection field | Default | Meaning |
| --- | --- | --- |
| `poll_ms` | 10 | How often OpenPLC reads and writes every register group, 5 to 1000 ms. |
| `mailbox_poll_ms` | the first multiple of `poll_ms` from 50 | How often OpenPLC reads and writes the mailboxes, which get register groups of their own: a multiple of `poll_ms`, at most 250 ms. Slower costs the PLC less CPU, and mailbox blocks answer and receive more slowly ([plc-library.md](plc-library.md#the-mailboxes)). |
| `remote_device` | `canworks` | The remote device's name in the editor project (`devices/remote/<name>.json`). |
| `iec_base` | the first free from 100 | The first `%IW` and `%QW` word the groups get in the editor project. |

Adding the connection in the configurator turns on the PLC link and low word first, sets `listen` to `127.0.0.1:1502` (unless another connection is on the network), the watchdog to 5 × `poll_ms` (at least 50 ms) when unset, turns on the control block and the SDO registers, adds a live list per CANopen master network and repacks. It leaves the mailboxes off: the configurator offers them once the program declares a mailbox block ([plc-library.md](plc-library.md#with-or-without-the-mailboxes)). With an OpenPLC connection `plc_link` false and `word_order` `high_first` are refused. The PLC link fixes the first bytes:

| Bytes | Registers | Meaning |
| --- | --- | --- |
| input 0-3 | input registers 0-1 | the bridge's map hash, high word first |
| input 4-11 | input registers 2-5 | the status block (`status_location` is `%IB4` or left out) |
| output 0-5 | holding registers 0-2 | the PLC link header: running (1 while the program runs), the program's map hash high and low word |

Pack for Modbus places the values after them (input byte 12, output byte 6); a location in those bytes is refused.

**Map hash.** A CRC-32 over the config's located values (direction, first byte, size, bit) and the word order, computed the same way by the PC tools and the bridge; names and types are not part of it, so renaming a value changes nothing, and moving one changes the hash. The bridge logs it at start, `canworks-deploy --export-modbus-map` prints it, and the generated programs carry it.

**The PLC link header.** The header write sets the link state: running 1 with the bridge's hash is ok; running 0 is stopped (status byte 0 = 5); any other hash is a mismatch (status byte 0 = 4, logged once with both hashes). Output writes are answered normally but applied only while the state is ok. Stopped and mismatch put the outputs off with the `on_client_loss` action at once, before that write's values apply: when OpenPLC stops, it writes one last round of zeros, and with `"hold"` the nodes keep the values from before it. The watchdog still covers a lost connection.

**What the configurator writes.** Saving a config with an OpenPLC connection in an editor project, with no errors, writes, next to `canworks/canworks.json`:

- `devices/remote/canworks.json`: the remote device, on 127.0.0.1 and the port, with one read group (FC 4) or write group (FC 16) per run of contiguous registers (at most 125 or 123 registers each), the header write group first; every register gets its `%IW`/`%QW` word from `iec_base` on and an alias;
- `pous/programs/canworks_in.st` and `canworks_out.st`, run first and last in the project's task: they convert between the words and the typed members of the variable list, put the header with the generated hash last, and set `canworks.ok` while the bridge's hash matches and its status counter moves;
- the `canworks` variable list in `project.json`: one typed member per located value (`canworks.dio_door_open`), `ok` and `link` (`ARRAY[0..1279] OF WORD`), which the [function blocks](plc-library.md) take; with `mailboxes`, `canworks_in` also copies the mailbox words into `link` and calls `CW_LINK_SERVICE`, and `canworks_out` copies the requests back.

The user's own POUs are never touched. A file canworks owns that was changed in the editor is written again only after a question naming it, and an OpenPLC Editor with the project open must reopen it before Build. The connection's **Settings** show the remote device, the poll with the number of Modbus requests per poll (a warning above 40), the map hash and the first editor location.

**Timing.** OpenPLC's Modbus master reads every group, then writes every group, once per poll, on one connection. A value arrives up to one poll after the bridge has it, and an output up to one poll after the scan wrote it. Each group is one request, read under one lock in the bridge, so the values of one PDO always come together; two groups may come from different moments.

## Deploying and checking a config

The PC tools check a bridge config like any other: `canworks-deploy --config canworks.json --check` checks it, the configurator's Check does too, and its **Project target** switch turns a CODESYS project into a bridge project ([configurator.md](configurator.md#project-target)). Without an OpenPLC connection the configurator hides the OpenPLC Editor project actions; the bridge's output watchdog is `bridge.watchdog_ms`.

To replace the config of a running bridge from the PC, its running config needs the diagnostics channel with changes and uploads allowed:

```json
"diagnostics": { "token_verifier": "SCRAM-SHA-256$...", "allow_changes": true, "allow_config_upload": true }
```

Then:

```sh
canworks-deploy --bridge 192.168.10.5 --config canworks.json --token-file token.txt
```

The tool checks the config, sends it with its EDS files and simulation file over the encrypted channel, and the bridge checks it again, keeps the previous files, restarts on the new ones and reports `ok: canworks-bridge runs the new config`. When the new config does not start (its Modbus port is taken, an interface is missing), the bridge goes back to the previous files and the tool says so. A config the bridge refuses changes nothing. Each file is replaced atomically (written next to the old one, written to disk, renamed over it), so a power loss during an upload leaves every file either old or new; a file that cannot be written puts back the ones already replaced. An upload that would not fit on the device's disk is refused before anything stops.

`canworks-diag --runtime HOST status` shows a bridge line with the output state, the watchdog, the connected clients, the last upload and how the previous run ended; the configurator's Online view works against a bridge as against a runtime.

## When the bridge fails

| What happens | What the bridge does | What the PLC sees | What the nodes see |
|---|---|---|---|
| Clean stop (`systemctl stop`, an update) | every CANopen master network sends its nodes `master.on_plc_stop` (pre-operational by default), then closes; the bridge exits 0 whatever the number of networks | no answers; `canworks.ok` FALSE after the stale time | the NMT command, then no SYNC or heartbeat |
| Crash, kill, out of memory | nothing: the process is gone. systemd starts it again 1 s later | as above; after the restart the status counter starts from 0 and byte 7 bit 0 is set | SYNC and the master heartbeat stop; RPDO values stay unless the node watches the master's heartbeat (`heartbeat_consumer`) or has an RPDO deadline (`event_timer_ms`) |
| Hang (a thread makes no progress for 10 s) | logs which thread and aborts; systemd or the container restarts it. systemd's watchdog (20 s) is the backstop | connections are accepted but not answered; `canworks.ok` FALSE | as for a crash |
| Power loss | as for a crash; the next start logs that the previous run did not stop cleanly | as for a crash | as for a crash |
| Full or read-only disk | with its generated files cached it starts as usual; otherwise it refuses to start with `no space left in … (N KiB free)` and systemd retries once a second | no answers | nothing from the bridge |
| Config upload that cannot be put in place, or does not start | puts the previous files back and runs them; when they do not start either, it exits and systemd retries | a short gap | the restart's boot |

The systemd unit is `Type=notify`: `systemctl start` returns once the Modbus port answers. It restarts the bridge after every exit it did not ask for (`Restart=always`, `RestartSec=1`) and never gives up (`StartLimitIntervalSec=0`), so a port held by another program or a full disk delays the bridge instead of leaving the unit failed. The bridge feeds systemd's watchdog (`WatchdogSec=20s`) only while its loop, its Modbus server and every network's bus thread make progress.

### What the nodes do

A node keeps whatever its RPDOs last set until something tells it otherwise. After a clean stop that is the NMT command from `master.on_plc_stop`. After a crash, a kill or a power loss nothing is sent, so a node with outputs needs one of these to react:

| Setting | What the node does when the bridge is gone | After the restart |
|---|---|---|
| none (the EDS defaults) | keeps its last outputs and stays operational | boots again (without `config_check` the whole configuration is downloaded again) |
| `"heartbeat_consumer": true` (needs `master.heartbeat_ms`) | misses the master's heartbeat after `master.heartbeat_ms` × `master.heartbeat_multiplier` and reacts as its error behavior (0x1029 sub 1) says: pre-operational by default, stopped or no change on some devices | boots again and is operational |
| an RPDO `event_timer_ms` | misses the RPDO after that time and reacts as its device profile says (usually an EMCY, and on many I/O modules the outputs go to their error values) | the RPDO comes again |
| `"config_check": true` | as above | skips the download when the node still has this configuration, so the restart is quicker |

Check what a device does in its manual or its EDS 0x1029 (`error_behavior` sets it) before you rely on it: "no change" there means it keeps its outputs even with the heartbeat watch. A node with outputs that has neither setting gets one warning at load (`node 6 (valves) keeps its last outputs when the bridge stops without a clean stop ...`), from the bridge and from `canworks-deploy --check`; the configurator shows it in Problems with a **Watch the master heartbeat** button. The configurator sets `heartbeat_consumer` (and a 100 ms master heartbeat) on a node when it gets its first output entry, and `config_check` on every new node whose EDS can keep the stamp; a file you load is not changed.

The status block's byte 7 bit 1 is set while a network's bus is not usable (its interface down or missing, or bus-off), and `canworks-diag status` names those networks (`bus_not_ok`). A SocketCAN adapter that the bridge sets up should have `restart_ms` so the kernel restarts it after a bus-off; the configurator gives new adapters 100 ms and offers **Restart after bus-off (100 ms)** in Problems for one without it.

After a start that follows an unclean stop the log has `the previous run of this config did not stop cleanly`, the status block's byte 7 has bit 0 set until the bridge stops, and `canworks-diag status` says `last stop unclean`. The bridge keeps a small marker file (`.canworks/running` next to the config) for this; it is written once per start.

## Clients

**A PLC with Modbus TCP client channels:** create one read channel per suggested range (function 4, the start and count from the map) and one write channel (function 16), at a cycle well below `watchdog_ms`. Map the registers to variables with the types from the map: 16-bit values as INT or WORD, 32-bit values as two registers in the bridge's word order. The ST variable list (`--export-modbus-map map.st`) is a starting point for the declarations. For a config with the PLC link (`plc_link`, or `openplc`), the `.st` export is instead the whole PLC link for that PLC: the `canworks` list with the channel variables, the channels to create, and `canworks_in`/`canworks_out`, so the [function blocks](plc-library.md#on-another-modbus-plc) work there as on OpenPLC. A PLC that imports PLCopen XML gets all of it in one file with `--export-plcopen` ([plcopen.md](plcopen.md)).

**Node-RED:** the canworks node package `node-red-canworks` (`canworks-deploy --export-nodered-package`, or **Package** on a Node-RED connection in the configurator) reads and writes every value by name over one connection, keeps the watchdog fed and runs the function blocks' jobs (SDO, NMT, EMCY, CAN, J1939) as nodes; `canworks-deploy --export-nodered flow.json` (or the **Download** of a Node-RED connection) writes the flow that sets it up for a config ([node-red.md](node-red.md)).

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

With a top-level `cia309` object the bridge also serves the CiA 309-3 ASCII gateway ([cia309-gateway.md](cia309-gateway.md)), as described there: a plain port on its loopback address (default `127.0.0.1:7533`) and sessions through its diagnostics channel (`canworks-diag --runtime HOST gateway`). A CiA 309-3 client reads and, with `cia309.allow_changes`, writes the same nodes the Modbus clients see. Its requests neither feed the output watchdog nor end outputs off: with only a gateway client connected the watchdog runs out as with no client, and the gateway client keeps being served. NMT commands from the gateway follow the gateway's guards and the same hold rules as those of the control block. The bridge's status part lists the gateway sessions (`cia309_sessions`: address, plain or tunnelled, commands served).

## Security

Modbus TCP has no authentication or encryption. Put the bridge on a machine network, not on an office network or the internet, and use `readers` and `writers` so only the PLC or HMI that should write can. Changing the config over the network goes through the encrypted, token-protected diagnostics channel and must be allowed in the running config. The bridge runs as root for the CAN link setup and port 502; the systemd unit limits it to 256 MB of memory (`MemoryMax`) and 64 tasks (`TasksMax`).

## Limits

- Linux with SocketCAN only.
- At most 8192 input and 8192 output bytes; a location past them is refused.
- At most 16 connections (`max_clients`, up to 64), 4 per address, and 8 KB of unread replies per connection.
- A thread that makes no progress for 10 s aborts the bridge (it restarts).
- No Modbus RTU (serial); no Modbus TLS.
- One bridge per CAN interface.
- Function block mailboxes: at most 4 request mailboxes, 2 receive blocks, 32 receivers, 16 cyclic jobs and network info for 8 networks. A program receives about 450 CAN frames/s with one receive block or 1050 with two at a 10 ms mailbox poll, 90 or 210 at OpenPLC's default 50 ms ([throughput](#receive-throughput)), and sends about 50 frames/s per request mailbox with `CAN_SEND` at a 10 ms mailbox poll (10 at 50 ms).
