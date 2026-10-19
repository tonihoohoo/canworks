## ADDED Requirements

### Requirement: Adapter server
`canworks-diag adapter-serve --adapter TYPE:CHANNEL --bitrate KBIT [--port P] [--bind ADDR] [--allow-changes]` SHALL serve the CAN adapter with the diagnostics protocol on port P (default 7536) of ADDR (default all addresses): TLS with a certificate made at start, and the SCRAM-SHA-256 login bound to it, as the plugin's diagnostics channel. After login it SHALL answer the operations of a local adapter (status, SDO, NMT, scan, LSS, trace, raw frames, PDO test, SYNC) with the same results and refusals. The bit rate SHALL be the one given; the server SHALL never guess it.

#### Scenario: Commission from the PC
- **WHEN** the server runs on a Linux machine with `--adapter socketcan:can0 --bitrate 500 --allow-changes` and a PC connects with the right token and allows changes
- **THEN** the PC can scan, read and write SDOs, and change a node ID with LSS on the machine's bus, with the same results as with a USB adapter on the PC

#### Scenario: Plain connection refused
- **WHEN** a client connects without TLS
- **THEN** the server closes the connection and nothing reaches the bus

### Requirement: Adapter opened at first login
The server SHALL open the adapter and run the bit rate check when the first PC logs in, SHALL report a refused check to that PC with the same message as a local adapter, and SHALL close the adapter when the last PC disconnects.

#### Scenario: Wrong bit rate on the bus
- **WHEN** the server was started with `--bitrate 1000` and the bus runs at 500 kbit/s
- **THEN** the PC's connect fails saying the bus does not run at 1000 kbit/s, and nothing was sent on the bus

#### Scenario: Adapter free when nobody is connected
- **WHEN** the last PC disconnects
- **THEN** `canworks-diag --adapter socketcan:can0` on the machine itself can open the adapter

### Requirement: Server token
On first start without a stored verifier the server SHALL make a token, print it once and store only its verifier, readable only by the user that runs the server. `--new-token` SHALL replace it and `--token-file PATH` SHALL use the token in PATH. The plain token SHALL NOT be written on the server. Failed logins SHALL be delayed one second per address, limited to 10 per minute in total, and logged.

#### Scenario: First start
- **WHEN** the user runs `canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500` for the first time
- **THEN** the token is printed once, and the next start prints no token and accepts the same one

#### Scenario: Wrong token
- **WHEN** a PC logs in with a wrong token
- **THEN** the login fails with `wrong token`, an immediate second try from the same address is delayed by one second, and the attempt is logged

### Requirement: Changes need the server's permission
Without `--allow-changes` the server SHALL refuse SDO writes, NMT, LSS changes, frames, PDO test and SYNC with a message that names the option. With it, each PC's own allow-changes for its session SHALL still be required, as with a local adapter. The server SHALL never store parameters on a device by itself.

#### Scenario: Read-only server
- **WHEN** the server runs without `--allow-changes` and a PC with Allow changes on writes an SDO
- **THEN** the write is refused saying the server on that machine was started without `--allow-changes`, and nothing is sent on the bus

### Requirement: Server limits
The server SHALL accept at most 4 logged-in PCs, at most 8 connections not logged in and 2 per address, SHALL close a connection that has not logged in after 30 s and one idle for 10 minutes. Cyclic jobs, traces and PDO tests SHALL stop when the connection that started them closes.

#### Scenario: Connection lost during a cyclic send
- **WHEN** a PC that started a cyclic frame loses its network connection
- **THEN** the frame stops when the server notices the connection closed

### Requirement: Adapter server as a service
`sudo canworks-diag adapter-serve --install-service [same options]` SHALL install and start a systemd service running the server as the user who ran sudo, with only the capability needed to bring a SocketCAN interface up, restarted on failure, and SHALL advertise it on the local network (`_canworks._tcp`, TXT `kind=adapter`) when Avahi is installed. `--remove-service` SHALL stop and remove the service and the advertisement. `adapter-serve --status` SHALL say whether it runs and which PCs are connected.

#### Scenario: Survives a reboot
- **WHEN** the service was installed and the machine reboots
- **THEN** the server runs again without a terminal, and a PC connects with the same token

### Requirement: Remote adapter on the PC
`canworks-diag --adapter remote:HOST[:PORT]` with a token SHALL use an adapter server like a local adapter. Connecting to something that is not an adapter server SHALL fail with a message saying what it is. `canworks-diag discover` SHALL list adapter servers separately from runtimes.

#### Scenario: Scan from the command line
- **WHEN** the user runs `canworks-diag --adapter remote:linuxbox --token-file t scan`
- **THEN** the nodes on linuxbox's bus are listed as with a local adapter

#### Scenario: Runtime given as an adapter
- **WHEN** the user gives `--adapter remote:HOST` where HOST runs the canworks runtime
- **THEN** the tool says HOST is a runtime and to connect to it without `remote:`
