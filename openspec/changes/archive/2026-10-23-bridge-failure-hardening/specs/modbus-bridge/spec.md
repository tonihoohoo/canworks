## MODIFIED Requirements

### Requirement: Status block
With `status_location` (8 input bytes), the bridge SHALL publish:
- byte 0: state (1 running, 2 outputs off by watchdog, 3 outputs off by idle command)
- byte 1: number of connected clients
- bytes 2-3: a counter incremented every 100 ms
- bytes 4-5: the last control counter handled
- byte 6: the last control result
- byte 7: flags; bit 0 set for the whole run when the previous run of this config did not stop cleanly (Requirement: Unclean stop reported); the other bits 0

#### Scenario: Bridge alive
- **WHEN** a client reads the status block twice 500 ms apart
- **THEN** the counter has grown by about 5

#### Scenario: Start after a clean stop
- **WHEN** the bridge was stopped with `systemctl stop` and started again
- **THEN** byte 7 reads 0

#### Scenario: Start after a crash
- **WHEN** the bridge was killed with SIGKILL and systemd started it again
- **THEN** byte 7 reads 1 until the bridge stops, and the counter in bytes 2-3 started again from 0

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

## ADDED Requirements

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
