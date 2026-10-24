# modbus-bridge Specification

## Purpose
canworks-bridge: running the CAN networks without OpenPLC and serving their values to any Modbus TCP client, with the watchdog, status, control, live list and SDO registers.

## Requirements

### Requirement: Bridge process
`canworks-bridge --config FILE` SHALL run the networks of a bridge config (a version 2 config with a `bridge` object) on Linux without an OpenPLC runtime. It SHALL run every network kind the build includes (CANopen master, slave and gateway, J1939, plain CAN, raw messages, simulated networks), the diagnostics channel, trace and the CiA 309-3 gateway (canopen-cia309-gateway) exactly as the bridge does. The only difference is that the process image is served to Modbus TCP clients instead of a PLC program. It SHALL log one line naming its config, its protocols, its listen address and the number of input and output bytes, and SHALL exit with a non-zero status and the check's messages when the config is not valid.

#### Scenario: CANopen network behind Modbus
- **WHEN** the bridge runs a config with a CANopen master network on `can0` with node 5 and a `bridge` object
- **THEN** node 5 is booted and exchanges PDOs as under the bridge, and a Modbus client reads its TPDO values from input registers

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
- `"safe"`: every output location is set to its safe value (requirement "Safe values"), and the outputs keep being sent with those values

Inputs, SYNC, node supervision, the diagnostics channel and J1939 address claim SHALL keep running. The next accepted write SHALL end outputs off. Entering and leaving SHALL be logged with the reason.

#### Scenario: Client unplugged
- **WHEN** the client that writes outputs every 50 ms stops and `watchdog_ms` is 1000 with the default action
- **THEN** about 1 s later RPDOs stop, SYNC and input registers keep updating, the status block reads 2, and the log names the watchdog

#### Scenario: Reader does not feed the watchdog
- **WHEN** only a client that reads input registers is connected
- **THEN** the watchdog runs out and outputs stay off

#### Scenario: Client unplugged with safe values
- **WHEN** `on_client_loss` is `"safe"`, `safe_values` has `"%QW10": 500` for node 6's RPDO entry, and the writer stops for `watchdog_ms`
- **THEN** node 6's RPDO keeps being sent on every SYNC with 500 in that entry and 0 in its entries without a safe value, the status block reads 2, and the log names the watchdog and the safe values

### Requirement: Status block
With `status_location` (8 input bytes), the bridge SHALL publish:
- byte 0: state (1 running, 2 outputs off by watchdog, 3 outputs off by idle command)
- byte 1: number of connected clients
- bytes 2-3: a counter incremented every 100 ms
- bytes 4-5: the last control counter handled
- byte 6: the last control result
- byte 7: flags; bit 0 set for the whole run when the previous run of this config did not stop cleanly (Requirement: Unclean stop reported); bit 1 set while any CAN network of the bridge has its interface down or missing or its controller bus-off (error-warning and error-passive do not set it); the other bits 0

The bridge's diagnostics status SHALL name the networks whose bus is not ok (`bus_not_ok`).

#### Scenario: Bridge alive
- **WHEN** a client reads the status block twice 500 ms apart
- **THEN** the counter has grown by about 5

#### Scenario: Start after a clean stop
- **WHEN** the bridge was stopped with `systemctl stop` and started again
- **THEN** byte 7 reads 0

#### Scenario: Start after a crash
- **WHEN** the bridge was killed with SIGKILL and systemd started it again
- **THEN** byte 7 bit 0 is set until the bridge stops, and the counter in bytes 2-3 started again from 0

#### Scenario: Interface down
- **WHEN** the bridge runs one network on `can0` and `can0` is taken down
- **THEN** within 200 ms byte 7 bit 1 is set, and it clears within 200 ms after `can0` is up again

#### Scenario: Simulated network
- **WHEN** every network is simulated
- **THEN** bit 1 stays clear

### Requirement: Control block
With `control_location` (6 output bytes: counter word, command, network index, node, reserved), the bridge SHALL run a command once each time the counter changes, and SHALL echo the counter with a result in the status block (0 ok, 1 unknown command, 2 bad network, 3 bad node, 4 not a CANopen master network, 5 refused because the network is down or too many NMT commands wait, 6 not run because the bridge restarted). For a config with an OpenPLC connection (a PLC that rewrites its whole output image every poll), the first control block a client writes after the bridge starts SHALL be taken as the last one handled and SHALL NOT run; when its counter is not 0 the status block SHALL echo it with result 6. Commands:
- 1 run (end outputs off from idle)
- 2 idle (outputs off with the `on_client_loss` action)
- 3 NMT start, 4 NMT stop, 5 NMT pre-operational, 6 reset node, 7 reset communication, for the node on that CANopen master network (node 0 = all nodes)

#### Scenario: Stop one node
- **WHEN** a client writes command 4, network 0, node 7 and changes the counter from 41 to 42
- **THEN** NMT stop goes to node 7 once, and the status block shows counter 42 with result 0

#### Scenario: Other clients' first command runs
- **WHEN** a Modbus client of a config without `plc_link` writes the control block for the first time, command 4 with counter 1
- **THEN** the command runs

#### Scenario: Counter unchanged
- **WHEN** the client rewrites the same control block every 10 ms
- **THEN** the command runs only once

#### Scenario: Bridge restart
- **WHEN** the bridge of a config with `plc_link` restarts while the PLC keeps writing its last control block, command 3 with counter 42
- **THEN** no NMT start is sent, the status block shows counter 42 with result 6, and the client's next counter 43 runs its command

### Requirement: Live list
Each `live_lists` entry SHALL name a CANopen master network and a 16-byte input location. Bit n of that block (byte n/8, bit n mod 8) SHALL be set while node n of that network is OPERATIONAL.

#### Scenario: Node lost
- **WHEN** node 7 stops sending heartbeats
- **THEN** bit 7 of the live list clears when the master declares it lost

### Requirement: SDO bridge registers
With `sdo_bridge_location` (`request`: 14 output bytes, `response`: 14 input bytes), a client SHALL read or write one object of up to 4 bytes on a node of a CANopen master network. The request is counter, command (1 read, 2 write), network index, node, sub-index, index, length, reserved and value. The response is counter echo, status (0 idle, 1 busy, 2 done, 3 aborted), reserved, abort code and value. A request SHALL start when the counter changes, and SHALL go through the same queue and timeout as the SDO function blocks and the gateway's SDO bridge. A write SHALL need `sdo_bridge_write: true`; without it the request SHALL end aborted with abort code 0x08000020 and nothing is sent. For a config with `bridge.openplc`, the first SDO request a client writes after the bridge starts SHALL be taken as the last one handled and SHALL NOT be sent; when its counter is not 0 the response SHALL show it aborted with abort code 0x08000021. A bridged request SHALL be logged at debug level, and an abort or timeout at info level.

#### Scenario: Read the vendor ID
- **WHEN** a client writes command 1, network 0, node 5, index 0x1018, sub-index 1, length 4 and a new counter
- **THEN** the response shows that counter with status 1, then status 2 with node 5's vendor ID in the value

#### Scenario: No replayed write after a restart
- **WHEN** the bridge of an OpenPLC config restarts while the PLC's last request, an SDO write with counter 9, is still in its output image
- **THEN** nothing is sent to the node and the response shows counter 9 with status 3 and abort code 0x08000021

### Requirement: Clients and access
The bridge SHALL listen on `listen` and accept at most `max_clients` connections (default 16) and at most `max_clients_per_address` connections from one address (default 4), closing further ones at accept with a log line. When all slots are taken and a client whose address is in `writers` connects, the bridge SHALL close the oldest connection from an address not in `writers` to make room. When the writer's own address already has `max_clients_per_address` connections, the bridge SHALL close that address's connection whose last complete request is oldest to make room, with a log line naming both. A client whose address is not in `readers` (when set) SHALL be disconnected at accept. `writers` SHALL be required: a bridge config without it SHALL be refused, and `["0.0.0.0/0", "::/0"]` SHALL be the way to let every address write. A write from a client not in `writers` SHALL get exception 0x01 and change nothing. An entry of `readers` or `writers` that cannot be parsed SHALL stop the bridge from starting. The bridge SHALL answer requests for `unit_id` (default 1), 0 and 255, and SHALL answer other unit IDs with exception 0x0B. It SHALL support functions 1, 2, 3, 4, 5, 6, 15, 16, 23 and 8 (loopback), answer other functions with exception 0x01, and answer addresses outside the image or counts over 125 registers read, 123 registers written or 2000 bits with exception 0x02 or 0x03. A connection that has sent no complete request for 60 s SHALL be closed, and a connection holding an incomplete request for 5 s SHALL be closed. Every accepted connection SHALL use TCP keepalive with 5 s idle, 2 s interval and 3 probes, so a connection whose peer lost power or its network is closed within about 11 s. The bridge SHALL hold at most 8 KB of unsent replies per connection, SHALL NOT read further requests from a connection while it is over that, and SHALL close a connection that stays over it for 10 s.

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

#### Scenario: Writer reconnects next to its own dead connections
- **WHEN** `writers` is `["127.0.0.1"]`, four connections from 127.0.0.1 are open and send nothing, and a fifth connection from 127.0.0.1 connects and writes
- **THEN** the idle connection with the oldest request is closed with a log line, and the write is answered

#### Scenario: Peer lost power
- **WHEN** a connected client's machine loses power without closing its connection
- **THEN** the bridge closes that connection within about 11 s, not 60 s

### Requirement: One owner per interface
A process (bridge or OpenPLC bridge) SHALL take an exclusive lock for each real CAN interface it uses before bringing it up. When the lock is held by another process, the network SHALL fail to start with an error naming the interface and the owner's process ID, and the other networks SHALL run.

#### Scenario: Second bridge on can0
- **WHEN** two bridge instances are configured with networks on `can0`
- **THEN** the second logs that `can0` is owned by the first one's process ID and does not touch the interface

### Requirement: Several instances
`scripts/install-bridge.sh` SHALL build and install the bridge with the same protocol options as the bridge install (`--without-canopen`, `--without-j1939`), and SHALL install a systemd template unit `canworks-bridge@NAME` that runs the config in `/etc/canworks-bridge/NAME/` with `CAP_NET_BIND_SERVICE` and restarts on failure. A release SHALL publish a multi-arch container image of the bridge.

#### Scenario: Two machine sections
- **WHEN** `canworks-bridge@press` uses `can0` on port 502 and `canworks-bridge@feeder` uses `can1` on port 1502
- **THEN** both run, each serving only its own networks

### Requirement: Stop clears the output image
With `on_client_loss: "stop"`, entering outputs off SHALL set every output location of the image to 0 without sending it, so the write that ends outputs off starts from zeros and not from the values written before the loss.

#### Scenario: One coil after a loss
- **WHEN** outputs were off after a loss with `"stop"`, and a writer then writes one coil
- **THEN** that coil's output is sent with its new value and every other output is sent as 0

### Requirement: Bridge service limits
The systemd unit that `install-bridge.sh` writes SHALL:
- limit the bridge's memory and number of tasks, so a fault in the bridge cannot use up the device's memory;
- be `Type=notify` with a 20 s systemd watchdog, the bridge reporting ready once its Modbus port is bound and feeding the watchdog only while its threads make progress (Requirement: Stall watchdog);
- restart the bridge after every exit it did not ask for, 1 s later, with no start limit, so a run of failed starts (a taken port, a full disk, a refused config) never leaves the unit failed for good.

The bridge SHALL send these notifications only when `NOTIFY_SOCKET` is set, and SHALL need no systemd library.

#### Scenario: Installed unit
- **WHEN** `install-bridge.sh` installs instance `line1`
- **THEN** `systemctl show canworks-bridge@line1` reports a memory limit, a task limit, `Type=notify`, a 20 s watchdog, `Restart=always`, a 1 s restart delay and no start limit

#### Scenario: Port taken for a while
- **WHEN** another process holds the bridge's Modbus port for 30 s and then frees it
- **THEN** the bridge fails to start about once a second while the port is taken, logs the reason each time, and runs once the port is free, without anyone restarting the unit

#### Scenario: Ready only when serving
- **WHEN** `systemctl start canworks-bridge@line1` returns successfully
- **THEN** the Modbus port answers

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

### Requirement: Bridge installed version and steps
`install-bridge.sh` SHALL write the bridge's version to `<prefix>/VERSION` on every install and update and remove it on `--uninstall`, and SHALL print `::canworks-step N/M text` lines when each step starts (download, build tools, Lely, bridge, instance check and start, restart of running instances), with its other output unchanged.

#### Scenario: Bridge next to a Docker runtime
- **WHEN** release 0.98.0 of the bridge is installed into `/opt/canworks-bridge`
- **THEN** `/opt/canworks-bridge/VERSION` holds `0.98.0` and the output has step lines from `1/M` to `M/M`

### Requirement: Bridge install keeps another config's remote link
`install-bridge.sh --with-link NAME` SHALL NOT repoint a remote link that serves another config (one not under `/etc/canworks-bridge/`, such as the PLC's). It SHALL skip the link step and say so.

#### Scenario: PLC device with a remote link
- **WHEN** the bridge is installed with `--with-link line3` on a device whose remote link serves `/opt/canworks/lib/canworks.json`
- **THEN** the link keeps serving that config and the output says the link step was skipped

### Requirement: Bridge installs locked dependency versions
`install-bridge.sh` SHALL take `--constraints FILE` and install the tools into the bridge's venv with it. A release install through `install-bridge.sh` SHALL fetch and use that release's `canworks-<version>-constraints.txt`. The bridge image SHALL be built with the constraints exported from `uv.lock` of the commit it is built from.

#### Scenario: Bridge image
- **WHEN** the bridge image is built on `main`
- **THEN** its venv holds the dependency versions of that commit's `uv.lock`

### Requirement: Map hash
The bridge SHALL compute a 32-bit map hash of its config as `modbus-bridge-map` defines it, log it at start, and, in a config with `plc_link` true, serve it at input registers 0 (high word) and 1 (low word).

#### Scenario: Hash served
- **WHEN** a bridge config with `plc_link` true and map hash 0x1234ABCD runs and a client reads input registers 0 and 1
- **THEN** it reads 0x1234 and 0xABCD

### Requirement: PLC link header
In a config with the PLC link (`bridge.plc_link`, set by an OpenPLC connection), holding registers 0-2 SHALL be the PLC link header (running, map hash high word, map hash low word) and not part of the output image. A write covering register 0 SHALL set the link state: ok when running is 1 and the hash equals the bridge's, stopped when running is 0, mismatch otherwise. Stopped SHALL set status byte 0 to 5. Writes to other output registers SHALL be answered normally and applied only while the state is ok. Entering stopped SHALL enter outputs off at once with the `on_client_loss` action, using the output values from before that write. Entering mismatch SHALL enter outputs off, set status byte 0 to 4, and log once naming both hashes. A write with state ok SHALL end outputs off as an accepted write does. Until the first header write the state SHALL be stopped.

#### Scenario: PLC stops
- **WHEN** outputs run with `on_client_loss: "hold"`, then the runtime's stop round writes the header with running 0 followed by all-zero output registers
- **THEN** the outputs keep being sent with the values from before the stop round, and the zeros are not applied

#### Scenario: Program built for another map
- **WHEN** the program writes the header with running 1 and hash 0x11111111 while the bridge's hash is 0x22222222
- **THEN** output writes change nothing, status byte 0 reads 4, and the log names both hashes once

#### Scenario: PLC starts again
- **WHEN** after a stop the header is written with running 1 and the matching hash, followed by the outputs
- **THEN** outputs off ends and the new values are sent

### Requirement: Nodes to pre-operational on client loss
`on_client_loss` SHALL also take `"preop"`: outputs stop as with `"stop"`, and NMT enter pre-operational SHALL be sent to each configured node of every CANopen master network (not node 0, so devices canworks does not manage are left alone). Leaving outputs off SHALL send NMT start to each of those nodes. The log lines SHALL name the client loss as the cause.

#### Scenario: Watchdog with preop
- **WHEN** `on_client_loss` is `"preop"` and the writer stops writing for `watchdog_ms`
- **THEN** RPDOs stop, the master sends NMT enter pre-operational to each configured node, the log says it was the client loss, and the next accepted write sends NMT start to each configured node

### Requirement: Bridge builds without runtime sources
The engine, the bridge, the standalone simulator and their tests SHALL build from this repository, Lely CANopen and the system's libraries only. No build, install script, image or CI job SHALL download, check out or include any OpenPLC runtime source or header, and no canworks source SHALL include a runtime header.

#### Scenario: Offline build
- **WHEN** `install-bridge.sh` runs from a checkout on a Linux device whose only network access is to the Lely and Python package sources
- **THEN** the bridge builds and installs, and no OpenPLC runtime archive is fetched

#### Scenario: Runtime header added
- **WHEN** a change adds `#include "plugin_types.h"` to an engine source
- **THEN** a CI check fails naming the file

### Requirement: Link and discovery with the bridge install
`install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled and started, watching the instance's config), and `/etc/canworks-link/` with no paired PCs. No other step on the device SHALL be needed. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-bridge.sh --with-link --instance line1 --config DIR` runs on a device with no internet route
- **THEN** the service starts, makes no outside connection, appears in discovery with its link ID, and the first PC that logs in with the right token on the LAN gets paired

### Requirement: dcf-tools pinned for the bridge
`build-lely.sh` SHALL install dcf-tools with the exact versions in `scripts/dcf-tools-constraints.txt`. That file SHALL name the Lely commit it was made for, and a test SHALL fail when the Lely commit changes without it.

#### Scenario: Lely commit bumped alone
- **WHEN** a change updates `_lely_dcf/VERSION` and not `scripts/dcf-tools-constraints.txt`
- **THEN** the test fails, naming both files

### Requirement: PLC link on any bridge config
A bridge config SHALL accept `plc_link: true`, the only switch for the PLC link: holding registers 0-2 are the PLC link header (Requirement: PLC link header), input registers 0-1 the map hash and input byte 4 the status block, and a value located in those bytes SHALL be refused. Without `plc_link` a bridge config SHALL have no header and no hash in its image.

#### Scenario: CODESYS client with the header
- **WHEN** a config has `plc_link: true` and a client writes the header with running 1 and the matching hash, then the outputs
- **THEN** the outputs are applied, and a header with another hash leaves outputs off and logs the mismatch once

#### Scenario: Old config
- **WHEN** a bridge config without `plc_link` has a value at holding register 0
- **THEN** it is accepted and applied as a plain output register

### Requirement: Connections ignored by the bridge
canworks-bridge SHALL accept `bridge.connections` as a list of objects and SHALL NOT read its entries, so a configurator-only field never stops a bridge. Anything else than a list SHALL be refused.

#### Scenario: Unknown kind
- **WHEN** a bridge config has `"connections": [{"kind": "future"}]`
- **THEN** the bridge starts and serves the registers as without it

### Requirement: Removed openplc field
canworks-bridge and the PC check SHALL refuse `bridge.openplc` with one message: the field was removed, OpenPLC is a connection on the Modbus bridge page, and the config must be opened in the configurator to add it.

#### Scenario: Old OpenPLC config
- **WHEN** `canworks-bridge --check-only` runs on a config with `"bridge": {"openplc": {}}`
- **THEN** it exits non-zero with that message, naming `bridge.openplc`

### Requirement: Stall watchdog
The bridge SHALL watch its own threads: the 1 ms loop, the Modbus server thread and every network's bus thread. When one of them has made no progress for 10 s, the bridge SHALL log an error naming that thread and that it aborts so the service restarts, and SHALL abort. While a config upload is being applied, the threads that are stopped SHALL NOT count as stalled. This SHALL work the same under systemd and in a container, where the container's restart policy restarts the bridge.

#### Scenario: Hung bridge
- **WHEN** the bridge's loop thread is blocked for 10 s
- **THEN** the log names the loop thread, the process aborts, and systemd starts the bridge again

#### Scenario: Hung bridge in a container
- **WHEN** the same happens in the `canworks-bridge` container started with `--restart unless-stopped`
- **THEN** the container restarts and the bridge serves Modbus again

#### Scenario: Short pause
- **WHEN** the bridge is paused for 2 s (SIGSTOP, then SIGCONT)
- **THEN** it does not abort, the output watchdog handles the gap as today, and the nodes are operational again

#### Scenario: Slow upload apply
- **WHEN** an uploaded config takes 8 s to start because dcfgen runs for every node
- **THEN** the bridge does not abort and systemd's watchdog does not fire

### Requirement: Unclean stop reported
At every successful start, the bridge SHALL record in the config folder's `.canworks/` that it runs, and SHALL remove that record when it stops on SIGTERM or SIGINT. When it finds the record at start, the previous run ended without a stop (a crash, a kill, a hang abort or a power loss): it SHALL log a warning saying so, set bit 0 of status block byte 7 for this run, and report `last_stop` `"unclean"` in its diagnostics status; otherwise `last_stop` SHALL be `"clean"`, or `"unknown"` on the first start of a config. The record SHALL be written once per start and never per cycle.

#### Scenario: Power loss
- **WHEN** the device loses power while the bridge runs and boots again
- **THEN** the bridge logs that its previous run did not stop cleanly, `canworks-diag status` shows `last_stop: unclean`, and status byte 7 bit 0 is set

#### Scenario: Update restart
- **WHEN** `install-bridge.sh` updates the bridge and restarts the running instance
- **THEN** `last_stop` is `clean` and byte 7 is 0

### Requirement: Full or read-only config folder
When the bridge must write its generated files and the config folder is read-only, or has less than 1 MiB free, or a write there fails for lack of space, the bridge SHALL refuse to start with a message naming the folder, the free space and that it writes its generated files there. It SHALL NOT report a missing deploy tool for a lint or dcfgen run that failed for that reason. With a valid cache of generated files the bridge SHALL start as before, whatever the free space.

#### Scenario: Full disk, new config
- **WHEN** the device's disk is full and the bridge starts a config whose generated files are not cached
- **THEN** it exits with a message saying there is no space left in the config folder and how much is free, and no message about the deploy tool

#### Scenario: Full disk, cached config
- **WHEN** the device's disk is full and the bridge starts a config it ran before, unchanged
- **THEN** it starts and serves Modbus

### Requirement: Generated files survive a power loss
The bridge SHALL write the generated DCF and concise DCF files to disk (fsync) before it records that they match the config, so that after a power loss it never reuses a partly written file as current.

#### Scenario: Power loss while generating
- **WHEN** the device loses power while the bridge generates the files of a changed config
- **THEN** at the next start the bridge generates them again instead of loading a partly written DCF

### Requirement: Bridge image timing
The bridge SHALL have no PLC scan. Its loop SHALL publish the input image (with the bridge's own blocks: status, live lists, SDO response) every 1 ms, and each accepted Modbus write SHALL publish the output snapshot to the networks at once. Where a spec of a network kind says "by the next scan" or "at the next scan start" for an input, it SHALL mean within one 1 ms publication. Where it says "the last finished scan" or "the end of each scan" for an output, it SHALL mean the output snapshot of the last accepted write. "The PLC keeps scanning" SHALL mean that the bridge keeps serving Modbus clients. "The PLC scan" that a background service must not delay SHALL mean the bridge's loop and its Modbus server.

#### Scenario: Input published
- **WHEN** a TPDO with a new value arrives
- **THEN** a Modbus read 1 ms later returns the new value

#### Scenario: Output from a write
- **WHEN** a client writes a holding register mapped to an RPDO entry and no SYNC is configured
- **THEN** the master sends the RPDO with the new value within 1 ms of the write, with no wait for a cycle

### Requirement: Installs canworks only
`install-bridge.sh` and `install-bridge.ps1` SHALL install, update and remove canworks parts only and SHALL NOT install, switch or remove the OpenPLC runtime, Docker or any other program. They SHALL have no `--with-openplc`, `--pinned-runtime`, `-WithOpenplc` or `-PinnedRuntime` option. `docs/modbus-bridge.md` SHALL point to upstream's installer for the runtime.

#### Scenario: Old option
- **WHEN** `install-bridge.sh --with-openplc --instance line1 --config DIR` runs
- **THEN** it ends non-zero naming the unknown option, and nothing is installed

#### Scenario: Device with a runtime
- **WHEN** `install-bridge.sh --instance line1 --config DIR` runs on a device with the managed Docker OpenPLC runtime
- **THEN** the bridge runs `line1`, and the runtime's containers and version are unchanged

### Requirement: Clean stop with several networks
A bridge with any number of CANopen, J1939 and CAN networks SHALL stop on SIGTERM with exit code 0 after every network has run its `on_plc_stop` action, and SHALL remove its run marker. An accepted config upload SHALL be applied on the restart that follows it. A network whose interface drops while the bridge runs SHALL NOT end the process.

#### Scenario: Stop with three CANopen networks
- **WHEN** a bridge runs a config with three CANopen master networks and receives SIGTERM
- **THEN** each network sends its `on_plc_stop` NMT command, the bridge exits 0, and the next start reports the last stop as clean

#### Scenario: Upload with two networks
- **WHEN** a client uploads a new config to a bridge running two CANopen networks
- **THEN** the bridge restarts on the new config, reports the upload, and leaves no staged upload behind

#### Scenario: One interface drops
- **WHEN** the interface of the first of two networks goes down and a client then writes an output of the second
- **THEN** the bridge keeps running, the first network reports its bus lost, and the write is applied

### Requirement: Device identification with the map hash
In addition to the functions the bridge supports, it SHALL answer Modbus function 43 with MEI type 14 (Read Device Identification) for every config: object 0 "canworks", object 1 "canworks-bridge", object 2 the bridge version, and the private object 0x80 the config's map hash as 8 upper-case hex digits. Other MEI types SHALL get exception 0x01.

#### Scenario: Read the map hash
- **WHEN** a client sends function 43/14 with read code 1 to a bridge whose map hash is 0x1234ABCD, with or without `plc_link`
- **THEN** the answer holds "canworks", "canworks-bridge", the version, and object 0x80 "1234ABCD"

### Requirement: Safe values
`bridge.safe_values` SHALL map output locations to values. A location SHALL be refused at load unless it is an output location covered by a data binding (an RPDO entry, a J1939 or raw transmit signal). Locations of the bridge's own blocks, the PLC link header, NMT command bytes, and the trigger and enable bits of SDO variables and raw messages SHALL be refused, naming the binding. A value SHALL be refused unless it fits the binding: an integer in the binding's range, a finite number for REAL32 and REAL64, `true`, `false`, 0 or 1 for a bit, and a decimal string for a 64-bit integer beyond 2^53. A bit location inside a bound byte or word SHALL set only that bit, after the whole values. Output locations without a safe value SHALL be 0 in the safe image. `safe_values` with an `on_client_loss` other than `"safe"` SHALL load with a warning that they are not used.

With `"safe"`, entering outputs off for any reason (the watchdog, the control block's idle command, the PLC link header stopped or mismatched) SHALL write the safe image over the output image and keep the outputs sent. Periodic J1939 and raw messages SHALL keep their period and on-change messages SHALL be sent once with the safe values. The write that ends outputs off SHALL start from the safe image. Mailbox operations, cyclic frame jobs and SDO variables SHALL end as in the other actions.

#### Scenario: Value out of range
- **WHEN** `safe_values` has `"%QB8": 300` and `%QB8` is an UNSIGNED8 RPDO entry
- **THEN** the config is refused with an error naming `%QB8`, the entry and the range 0-255

#### Scenario: Safe value on a command byte
- **WHEN** `safe_values` names the location of node 6's NMT command byte
- **THEN** the config is refused with an error saying safe values cannot be set on an NMT command byte

#### Scenario: Bit of a controlword
- **WHEN** `safe_values` has `"%QW20": 6` and `"%QX21.2": false` on a drive's controlword at `%QW20`, and outputs go off with `"safe"`
- **THEN** the controlword is sent as 6 with bit 2 of byte 21 cleared, which is 2

#### Scenario: PLC stops
- **WHEN** an OpenPLC connection's program stops (PLC link header running 0) and `on_client_loss` is `"safe"`
- **THEN** the outputs go to their safe values at once and keep being sent, and status byte 0 reads 5

#### Scenario: Reconnect after a loss
- **WHEN** outputs were off with `"safe"` and a writer then writes one coil
- **THEN** that coil's output is sent with its new value and every other output keeps its safe value

#### Scenario: Unused safe values
- **WHEN** `safe_values` is set and `on_client_loss` is `"stop"`
- **THEN** the bridge starts with a warning that the safe values are not used with `stop`

### Requirement: Safe values at start and clean stop
With `"safe"`, the bridge SHALL put the safe image in place at start, so the outputs are sent with their safe values from the moment each network runs until the first accepted write ends outputs off. On a clean stop the bridge SHALL write the safe image, wait one SYNC period of the CANopen master networks (the longest, at least 20 ms, at most 200 ms) while RPDOs, periodic J1939 and raw messages and on-change messages carry it, and then send `master.on_plc_stop` as before.

#### Scenario: Start before the PLC
- **WHEN** a bridge with `"safe"` and `"%QW10": 500` starts and no client has written yet
- **THEN** node 6's RPDO is sent with 500 from the first SYNC after the node is operational

#### Scenario: Clean stop
- **WHEN** a writer wrote `%QW10` = 900 and the bridge is stopped with `systemctl stop`
- **THEN** node 6 receives an RPDO with 500 before the NMT command of `master.on_plc_stop`

### Requirement: Client counters
The bridge SHALL count, for every connected Modbus client and from the moment it connected: requests per function code, answers per exception code, writes refused because the client is not in `writers`, and the time, table and register or bit range of its last accepted write. It SHALL keep the number of requests answered in the last 5 s. The counters SHALL be kept whether or not anyone reads them and SHALL NOT delay any answer.

#### Scenario: Counting a polling client
- **WHEN** a writer client sends 100 reads of input registers 0-9 and 100 writes of holding registers 0-3
- **THEN** its counters show 100 requests of function 4, 100 of function 16, no exceptions, and its last write as holding registers 0-3 with its time

#### Scenario: Reader that tries to write
- **WHEN** a client not in `writers` writes holding register 5 three times
- **THEN** its counters show 3 refused writes and 3 answers with exception 0x01

### Requirement: Recently closed clients
When a connection closes, the bridge SHALL keep its address, its counters, how long it was connected and why it closed (closed by the client, idle for 60 s, an incomplete request for 5 s, replies not read, its slot taken by a writer, the per-address limit, not in `readers`, keepalive) for 10 minutes, at most the last 8 connections.

#### Scenario: Client cut for not reading
- **WHEN** a client sends reads without reading its socket until the bridge closes it
- **THEN** the closed list holds that client's address with the reason "replies not read" and its request counts, for 10 minutes

### Requirement: Modbus trace recorder
While at least one diagnostics client traces Modbus, the bridge SHALL record each answered request as one record: the UTC time of the answer in microseconds, the client, the MBAP transaction and unit identifiers, the function, the table, start and count, the values read or written (up to 250 bytes), and the result (ok or the exception code, and whether it was a refused write). It SHALL record nothing while no client traces. Recording SHALL happen after the answer is queued, so it never delays an answer. The bridge SHALL keep at least 4 MiB of records for clients to fetch.

With "changes only" (the default), a request whose client, function, start and count equal an earlier one's, and whose values and result equal that earlier one's, SHALL be counted and not recorded; the next record of that kind from that client SHALL carry the number of requests skipped since its predecessor. Exceptions, refused writes and functions 8 and 43 SHALL always be recorded.

#### Scenario: OpenPLC polling with nothing changing
- **WHEN** a client reads input registers 0-49 every 10 ms for 10 s, the values never change, and a trace with changes only runs
- **THEN** one record of that read is kept, and no further one until a value changes; that next record says how many identical reads it skipped

#### Scenario: Nothing recorded without a trace
- **WHEN** no diagnostics client traces Modbus
- **THEN** the bridge records no Modbus records and answers requests as without the recorder

#### Scenario: Exception always recorded
- **WHEN** a client reads input register 30001 every 10 ms on a 40-byte image during a trace with changes only
- **THEN** every one of those requests is recorded with exception 0x02
