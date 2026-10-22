# modbus-bridge Specification

## Purpose
canworks-bridge: running the CAN networks without OpenPLC and serving their values to any Modbus TCP client, with the watchdog, status, control, live list and SDO registers.

## Requirements

### Requirement: Bridge process
`canworks-bridge --config FILE` SHALL run the networks of a bridge config (a version 2 config with a `bridge` object) on Linux without an OpenPLC runtime. It SHALL run every network kind the build includes (CANopen master, slave and gateway, J1939, plain CAN, raw messages, simulated networks), the diagnostics channel, trace and the CiA 309-3 gateway (canopen-cia309-gateway) exactly as the plugin does. The only difference is that the process image is served to Modbus TCP clients instead of a PLC program. It SHALL log one line naming its config, its protocols, its listen address and the number of input and output bytes, and SHALL exit with a non-zero status and the check's messages when the config is not valid.

#### Scenario: CANopen network behind Modbus
- **WHEN** the bridge runs a config with a CANopen master network on `can0` with node 5 and a `bridge` object
- **THEN** node 5 is booted and exchanges PDOs as under the plugin, and a Modbus client reads its TPDO values from input registers

#### Scenario: Config without bridge object
- **WHEN** `canworks-bridge` is started with a config that has no `bridge` object
- **THEN** it exits with an error saying the config is not a bridge config

#### Scenario: CiA 309-3 next to Modbus
- **WHEN** a bridge config has `bridge` and `cia309` objects
- **THEN** a Modbus client reads registers on the Modbus port while a CiA 309-3 client on `127.0.0.1:7533` reads objects of the same nodes

### Requirement: Byte-addressed locations
In a bridge config every IEC location SHALL be byte-addressed: `%IBn` is input byte n, `%IWn` bytes n..n+1, `%IDn` bytes n..n+3, `%ILn` bytes n..n+7 and `%IXn.b` bit b of byte n, the same for `%Q`. Two locations SHALL clash when their byte ranges overlap, or when a bit location lies in a byte another location of the same direction covers, unless both are bits of different bit numbers. Word, double and long word locations SHALL start at an even byte. The image SHALL hold values most significant byte first. `sync_source: "plc_cycle"` SHALL be rejected, since the bridge has no PLC cycle.

#### Scenario: Overlap in byte mode
- **WHEN** a bridge config has `%ID4` on one PDO entry and `%IW6` on another
- **THEN** the config is rejected with an error naming both entries and the overlapping bytes 6 and 7

#### Scenario: Odd word location
- **WHEN** a bridge config puts a 16-bit entry at `%IW3`
- **THEN** the config is rejected with an error saying word locations must start at an even byte

### Requirement: Register and bit map
The bridge SHALL serve input byte n as input register n/2 (even n the high byte, odd n the low byte), input bit `%IXn.b` as discrete input n·8+b, output byte n as holding register n/2 and output bit `%QXn.b` as coil n·8+b. Holding registers and coils SHALL read back the output image. A 32- or 64-bit value SHALL occupy consecutive registers, highest word first with `word_order: "high_first"` (default) and lowest word first with `"low_first"`. REAL32 and REAL64 objects SHALL be served as their IEEE bit patterns.

#### Scenario: 32-bit input
- **WHEN** a TPDO entry UNSIGNED32 at `%ID4` holds 0x12345678 and a client reads input registers 2 and 3
- **THEN** it gets 0x1234 and 0x5678, and with `word_order: "low_first"` it gets 0x5678 and 0x1234

#### Scenario: Output bit as coil
- **WHEN** a client writes coil 801 to 1 and `%QX100.1` is bound to an RPDO entry
- **THEN** the RPDO carries TRUE for that entry, and holding register 50 reads back with bit 1 of its high byte set

### Requirement: Consistent requests
Every read request SHALL be answered from one input snapshot, and every write request SHALL be applied to the outputs as one snapshot. A value spanning several registers SHALL never mix two snapshots within one request.

#### Scenario: Fast-changing counter
- **WHEN** a node's 32-bit counter changes every millisecond and a client reads its two registers in one request 10,000 times
- **THEN** every pair read is a value the node actually sent

### Requirement: Outputs without a scan
A write request SHALL publish its new output snapshot immediately. Synchronous RPDOs SHALL carry it from the next SYNC, event-driven RPDOs from the next SYNC on a network with a SYNC period and at once on one without, and raw messages sent on change and J1939 messages sent on change SHALL go out without waiting for a cycle. Rising-edge inputs of the config (SDO variable triggers, NMT command bytes, raw trigger bits) SHALL be detected between consecutive published snapshots, so rewriting the same value creates no edge.

#### Scenario: Cyclic rewrite
- **WHEN** a client writes the same holding registers, including an SDO variable's trigger bit at 1, every 10 ms
- **THEN** the SDO variable is transferred once, at the first write that set the bit

#### Scenario: Event-driven output
- **WHEN** a client changes a value mapped into an event-driven RPDO
- **THEN** the RPDO is sent at the next SYNC when the network has a SYNC period, and within 2 ms of the write response when it has none

### Requirement: Output watchdog
The bridge SHALL feed its watchdog with every accepted write request (functions 5, 6, 15, 16, 23) from a writer client. When no such write arrived for `watchdog_ms` (default 1000; 0 turns the watchdog off), the bridge SHALL enter outputs off with the action of `on_client_loss`:
- `"stop"` (default): outputs stop: no RPDOs, no raw or J1939 transmit messages. SYNC keeps running, so nodes that send their inputs on SYNC keep sending them and a node's RPDO event timer sees the outputs stop
- `"zero"`: every output location is set to 0, the outputs are sent once, then they stop
- `"hold"`: outputs keep being sent with their last values

Inputs, SYNC, node supervision, the diagnostics channel and J1939 address claim SHALL keep running. The next accepted write SHALL end outputs off. Entering and leaving SHALL be logged with the reason.

#### Scenario: Client unplugged
- **WHEN** the client that writes outputs every 50 ms stops and `watchdog_ms` is 1000 with the default action
- **THEN** about 1 s later RPDOs stop, SYNC and input registers keep updating, the status block reads 2, and the log names the watchdog

#### Scenario: Reader does not feed the watchdog
- **WHEN** only a client that reads input registers is connected
- **THEN** the watchdog runs out and outputs stay off

### Requirement: Status block
With `status_location` (8 input bytes), the bridge SHALL publish:
- byte 0: state (1 running, 2 outputs off by watchdog, 3 outputs off by idle command)
- byte 1: number of connected clients
- bytes 2-3: a counter incremented every 100 ms
- bytes 4-5: the last control counter handled
- byte 6: the last control result
- byte 7: 0

#### Scenario: Bridge alive
- **WHEN** a client reads the status block twice 500 ms apart
- **THEN** the counter has grown by about 5

### Requirement: Control block
With `control_location` (6 output bytes: counter word, command, network index, node, reserved), the bridge SHALL run a command once each time the counter changes, and SHALL echo the counter with a result in the status block (0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused because the network is down or too many NMT commands wait). Commands:
- 1 run (end outputs off from idle)
- 2 idle (outputs off with the `on_client_loss` action)
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for the node on that CANopen master network (node 0 = all nodes)

#### Scenario: Stop one node
- **WHEN** a client writes command 4, network 0, node 7 and changes the counter from 41 to 42
- **THEN** NMT stop goes to node 7 once, and the status block shows counter 42 with result 0

#### Scenario: Counter unchanged
- **WHEN** the client rewrites the same control block every 10 ms
- **THEN** the command runs only once

### Requirement: Live list
Each `live_lists` entry SHALL name a CANopen master network and a 16-byte input location. Bit n of that block (byte n/8, bit n mod 8) SHALL be set while node n of that network is OPERATIONAL.

#### Scenario: Node lost
- **WHEN** node 7 stops sending heartbeats
- **THEN** bit 7 of the live list clears when the master declares it lost

### Requirement: SDO bridge registers
With `sdo_bridge_location` (`request`: 14 output bytes, `response`: 14 input bytes), a client SHALL read or write one object of up to 4 bytes on a node of a CANopen master network. The request is counter, command (1 read, 2 write), network index, node, sub-index, index, length, reserved and value. The response is counter echo, status (0 idle, 1 busy, 2 done, 3 aborted), reserved, abort code and value. A request SHALL start when the counter changes, and SHALL go through the same queue and timeout as the SDO function blocks and the gateway's SDO bridge. A write SHALL need `sdo_bridge_write: true`; without it the request SHALL end aborted with abort code 0x08000020 and nothing is sent.

#### Scenario: Read the vendor ID
- **WHEN** a client writes command 1, network 0, node 5, index 0x1018, sub-index 1, length 4 and a new counter
- **THEN** the response shows that counter with status 1, then status 2 with node 5's vendor ID in the value

### Requirement: Clients and access
The bridge SHALL listen on `listen` and accept at most `max_clients` connections (default 16) and at most `max_clients_per_address` connections from one address (default 4), closing further ones at accept with a log line; when all slots are taken and a client whose address is in `writers` connects, the bridge SHALL close the oldest connection from an address not in `writers` to make room. A client whose address is not in `readers` (when set) SHALL be disconnected at accept. `writers` SHALL be required: a bridge config without it SHALL be refused, and `["0.0.0.0/0", "::/0"]` SHALL be the way to let every address write. A write from a client not in `writers` SHALL get exception 0x01 and change nothing. An entry of `readers` or `writers` that cannot be parsed SHALL stop the bridge from starting. The bridge SHALL answer requests for `unit_id` (default 1), 0 and 255, and SHALL answer other unit IDs with exception 0x0B. It SHALL support functions 1, 2, 3, 4, 5, 6, 15, 16, 23 and 8 (loopback), answer other functions with exception 0x01, and answer addresses outside the image or counts over 125 registers read, 123 registers written or 2000 bits with exception 0x02 or 0x03. A connection that has sent no complete request for 60 s SHALL be closed, and a connection holding an incomplete request for 5 s SHALL be closed. The bridge SHALL hold at most 8 KB of unsent replies per connection, SHALL NOT read further requests from a connection while it is over that, and SHALL close a connection that stays over it for 10 s.

#### Scenario: Write from a reader
- **WHEN** `writers` is `["10.0.0.20"]` and a client at 10.0.0.30 writes a holding register
- **THEN** it gets exception 0x01 and the output image is unchanged

#### Scenario: Config without writers
- **WHEN** a bridge config has no `writers`
- **THEN** the bridge refuses to start, naming `writers` and how to allow every address

#### Scenario: Read past the image
- **WHEN** the input image is 40 bytes and a client reads input registers 18 to 21
- **THEN** it gets exception 0x02

#### Scenario: Client that never reads its replies
- **WHEN** a client sends read requests without pause and never reads its socket
- **THEN** the bridge's memory stays bounded, other clients keep being served, and the client is disconnected after 10 s

#### Scenario: Slots full when the controller reconnects
- **WHEN** 16 connections from readers fill every slot and the writer at 10.0.0.20 connects
- **THEN** the oldest reader connection is closed and the writer is served

### Requirement: One owner per interface
A process (bridge or OpenPLC plugin) SHALL take an exclusive lock for each real CAN interface it uses before bringing it up. When the lock is held by another process, the network SHALL fail to start with an error naming the interface and the owner's process ID, and the other networks SHALL run.

#### Scenario: Second bridge on can0
- **WHEN** two bridge instances are configured with networks on `can0`
- **THEN** the second logs that `can0` is owned by the first one's process ID and does not touch the interface

### Requirement: Several instances
`scripts/install-bridge.sh` SHALL build and install the bridge with the same protocol options as the plugin install (`--without-canopen`, `--without-j1939`), and SHALL install a systemd template unit `canworks-bridge@NAME` that runs the config in `/etc/canworks-bridge/NAME/` with `CAP_NET_BIND_SERVICE` and restarts on failure. A release SHALL publish a multi-arch container image of the bridge.

#### Scenario: Two machine sections
- **WHEN** `canworks-bridge@press` uses `can0` on port 502 and `canworks-bridge@feeder` uses `can1` on port 1502
- **THEN** both run, each serving only its own networks

### Requirement: Stop clears the output image
With `on_client_loss: "stop"`, entering outputs off SHALL set every output location of the image to 0 without sending it, so the write that ends outputs off starts from zeros and not from the values written before the loss.

#### Scenario: One coil after a loss
- **WHEN** outputs were off after a loss with `"stop"`, and a writer then writes one coil
- **THEN** that coil's output is sent with its new value and every other output is sent as 0

### Requirement: Bridge service limits
The systemd unit that `install-bridge.sh` writes SHALL limit the bridge's memory and number of tasks, so a fault in the bridge cannot use up the device's memory.

#### Scenario: Installed unit
- **WHEN** `install-bridge.sh` installs instance `line1`
- **THEN** `systemctl show canworks-bridge@line1` reports a memory limit and a task limit

### Requirement: CiA 309-3 gateway and the output watchdog
Requests through the CiA 309-3 gateway SHALL NOT feed the bridge's output watchdog and SHALL NOT end outputs off. NMT commands from the gateway SHALL follow the gateway's guards and SHALL be carried out like those of the control block. The bridge's status part SHALL list the gateway sessions.

#### Scenario: Gateway client only
- **WHEN** only a CiA 309-3 client is connected and it reads objects every 100 ms
- **THEN** the watchdog runs out as with no client, outputs go off, and the gateway client keeps being served

### Requirement: NMT commands while a network is down
An NMT command from the bridge's control block SHALL be refused while the target network's bus session is down, and the status block SHALL show control result 5 (refused). At most 16 NMT commands SHALL wait per network.

#### Scenario: Command during an outage
- **WHEN** the CAN interface is down and a Modbus client writes a STOP command for node 5
- **THEN** the command is refused, and nothing is sent to node 5 when the interface comes back

### Requirement: Request buffer limit
The Modbus server SHALL read from a connection only while less than one frame is waiting, so a client that pipelines requests cannot grow memory or slow other clients.

#### Scenario: Pipelined reads
- **WHEN** one client sends read requests faster than replies drain
- **THEN** the bridge's memory stays flat and other clients keep their reply rate

### Requirement: Bridge builds against the pinned runtime
The bridge install and image SHALL build against the runtime release the project pins, with a checked archive hash.

#### Scenario: Hash mismatch
- **WHEN** the downloaded runtime archive's hash differs
- **THEN** the install stops with a message

### Requirement: One-line bridge install and update

`scripts/install-bridge.sh` SHALL also run straight from the repository on GitHub as root (`curl -LsSf <url> | sudo bash`, options after `-s --`), and `docs/modbus-bridge.md` and the README SHALL give that line first among the bridge's install routes. Run outside a checkout, it SHALL download the source of the newest `deploy-v` release (or of `--version <version>`), found from the `releases/latest` redirect without the GitHub API, run that release's `scripts/install-bridge.sh` with every other option given, build the bridge with the release's version, and remove the downloaded source afterwards. It SHALL never install code from `main`. Running the same line again SHALL install the newer release; `--uninstall`, `--purge` and the other options SHALL pass through unchanged. Without root it SHALL exit non-zero before downloading anything and show the line with `sudo`. Run from a checkout without `--ssh` or `--version`, it SHALL install the checkout as before. The documentation SHALL keep the checkout route and the container image, and show the line pinned to a release.

The same install SHALL be possible from a Windows, macOS or Linux PC onto a remote Linux device over SSH: `install-bridge.sh --ssh USER@HOST` (macOS, Linux) and `scripts/install-bridge.ps1 -Ssh USER@HOST` (Windows PowerShell 5.1 with the built-in OpenSSH client), each runnable as one documented line straight from GitHub. The PC side SHALL need no root, no Python and no canworks tools; it SHALL resolve the release once and run the device side over `ssh -t` with that exact `--version`, so a `sudo` password prompt works and both sides agree on the release. Options other than the PC side's own (`--ssh`, `--port`, `--identity`, `--dry-run`) SHALL pass through to the device. The PC side SHALL exit with the device side's exit status, and SHALL say so before connecting when `ssh` is missing.

CI SHALL run `shellcheck` on the script and test, without network access, its release lookup, option pass-through and the `ssh` and `scp` command lines both scripts build.

#### Scenario: Install on a fresh device
- **WHEN** an operator pastes the documented line on a Linux device with CAN interfaces and no canworks checkout
- **THEN** the newest release's bridge is built and installed with its unit `canworks-bridge@.service`, `canworks-bridge --version` prints the release, and no source folder of the release is left behind

#### Scenario: Install from a Windows PC
- **WHEN** a user on Windows runs the documented PowerShell line with `-Ssh admin@plc.local`
- **THEN** an SSH session asks for the `sudo` password when needed, the newest release's bridge is installed on the device, and the PowerShell command ends with the device side's exit status

#### Scenario: Not root
- **WHEN** the device line is run without `sudo`
- **THEN** the script exits non-zero before downloading anything and shows the line with `sudo`

### Requirement: Bridge instance from the install line

`install-bridge.sh` SHALL take `--instance NAME --config DIR` (`-Instance`, `-Config` in `install-bridge.ps1`), where `DIR` holds a `canworks.json` and the files it names. After installing, it SHALL run the bridge's `--check-only` on `DIR/canworks.json`, and when the check passes copy the folder's regular files to `/etc/canworks-bridge/NAME/` and enable and start (or restart) `canworks-bridge@NAME`. When the check fails it SHALL leave the instance folder and its service as they were, print the check's messages and exit non-zero. `NAME` SHALL be a plain name (letters, digits, `-`, `_`), and either option without the other SHALL be refused before anything is installed. With `--ssh`, the PC side SHALL first copy `DIR` to a temporary folder on the device with `scp` (same port and key), pass that folder to the device side, and the device side SHALL remove it afterwards.

#### Scenario: Bridge set up from a Mac
- **WHEN** a Mac user runs `install-bridge.sh --ssh admin@plc.local --instance line1 --config ./line1`
- **THEN** the device has `/etc/canworks-bridge/line1/canworks.json` with the folder's EDS files, `canworks-bridge@line1` is enabled and running, and no temporary upload folder is left on the device

#### Scenario: Config that fails its check
- **WHEN** the config in `DIR` names an EDS file the folder does not have
- **THEN** the install line exits non-zero with the check's message, nothing is copied and `canworks-bridge@NAME` is not started or restarted

### Requirement: Bridge update restarts running instances

When `install-bridge.sh` installs a new bridge binary over an existing one, it SHALL restart every `canworks-bridge@` instance that was active and list them; stopped and disabled instances SHALL stay as they were.

#### Scenario: Update with two bridges
- **WHEN** the install line runs on a device where `canworks-bridge@press` runs and `canworks-bridge@feeder` is stopped
- **THEN** `press` runs the new binary afterwards and `feeder` is still stopped

### Requirement: Bridge prefix next to a Docker runtime

When no `--prefix` is given and the default prefix `/opt/canworks` holds a Python environment the host cannot use (a prefix the OpenPLC runtime's Docker container set up), `install-bridge.sh` SHALL install into `/opt/canworks-bridge` instead and say so; `--uninstall` and later updates without `--prefix` SHALL find that install. An explicit `--prefix /opt/canworks` SHALL keep today's refusal with its message.

#### Scenario: Device with the managed Docker runtime
- **WHEN** the install line runs without `--prefix` on a device whose runtime runs in Docker with the canworks plugin
- **THEN** the bridge is installed under `/opt/canworks-bridge`, the output says so, and the runtime's `/opt/canworks` is unchanged

### Requirement: Bridge installed version and steps
`install-bridge.sh` SHALL write the bridge's version to `<prefix>/VERSION` on every install and update and remove it on `--uninstall`, and SHALL print `::canworks-step N/M text` lines when each step starts (download, build tools, Lely, bridge, instance check and start, restart of running instances), with its other output unchanged.

#### Scenario: Bridge next to a Docker runtime
- **WHEN** release 0.98.0 of the bridge is installed into `/opt/canworks-bridge`
- **THEN** `/opt/canworks-bridge/VERSION` holds `0.98.0` and the output has step lines from `1/M` to `M/M`

### Requirement: Uninstall beside the canworks plugin
`install-bridge.sh --uninstall` SHALL keep `<prefix>/VERSION` when the prefix also holds the canworks plugin library, and SHALL keep the can-j1939 boot entry (`/etc/modules-load.d/canworks-j1939.conf`) while the plugin is installed. `install-stock.sh` SHALL likewise keep that entry, on uninstall and on an install without J1939, while the bridge's unit is installed.

#### Scenario: Bridge removed from a PLC device
- **WHEN** the bridge is uninstalled on a device whose canworks plugin uses J1939
- **THEN** can-j1939 still loads at boot and the plugin's version file stays

### Requirement: Bridge install keeps another config's remote link
`install-bridge.sh --with-link NAME` SHALL NOT repoint a remote link that serves another config (one not under `/etc/canworks-bridge/`, such as the PLC's). It SHALL skip the link step and say so.

#### Scenario: PLC device with a remote link
- **WHEN** the bridge is installed with `--with-link line3` on a device whose remote link serves `/opt/canworks/lib/canworks.json`
- **THEN** the link keeps serving that config and the output says the link step was skipped

### Requirement: Bridge installs locked dependency versions
`install-bridge.sh` SHALL take `--constraints FILE` and install the tools into the bridge's venv with it, falling back as `install-stock.sh` does when none is given. A release install through `install-runtime.sh` or the bridge's one-line install SHALL pass the release's constraints file. The bridge image SHALL be built with the constraints exported from `uv.lock` of the commit it is built from.

#### Scenario: Bridge image
- **WHEN** the bridge image is built on `main`
- **THEN** its venv holds the dependency versions of that commit's `uv.lock`
