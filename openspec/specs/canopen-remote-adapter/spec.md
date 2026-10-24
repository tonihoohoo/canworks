# canopen-remote-adapter Specification

## Purpose
The adapter server: a Linux machine serves its CAN adapter to PCs over the network with the diagnostics protocol (TLS and a token login), with its own limits and permission for changes, optionally as a service, and the PC side that commissions through it like a local adapter.

## Requirements

### Requirement: Adapter server
`canworks-diag adapter-serve --adapter TYPE:CHANNEL --bitrate KBIT [--port P] [--bind ADDR] [--allow-changes]` SHALL serve the CAN adapter with the diagnostics protocol on port P (default 7536) of ADDR (default all addresses): TLS with a certificate made at start, and the SCRAM-SHA-256 login bound to it, as the bridge's diagnostics channel. After login it SHALL answer the operations of a local adapter (status, SDO, NMT, scan, LSS, trace, raw frames, PDO test, SYNC) with the same results and refusals. The bit rate SHALL be the one given; the server SHALL never guess it.

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

### Requirement: Messages name the adapter machine
Errors that an adapter server reports about its own adapter or interface SHALL reach the PC worded for the adapter machine and naming its host, never as if the PC were missing something. `canworks-diag trace` through an adapter server SHALL report the server's kernel drops as dropped by the adapter machine's kernel.

#### Scenario: Interface missing on the server
- **WHEN** the server was started with `--adapter socketcan:slcan0`, `slcan0` does not exist on its machine, and a PC connects with `--adapter remote:linuxbox`
- **THEN** the PC's error says there is no CAN interface slcan0 on the adapter machine linuxbox, and does not say "on this PC"

#### Scenario: Trace summary through a server
- **WHEN** the user runs `canworks-diag --adapter remote:linuxbox trace` and the server's kernel dropped frames
- **THEN** the summary line says the frames were dropped by the adapter machine's kernel, and does not mention a PLC

### Requirement: Server stop in the log
`canworks-diag adapter-serve` SHALL log one line when it stops, saying whether SIGTERM or Ctrl-C stopped it and how many PCs were connected, before it exits.

#### Scenario: Service stopped
- **WHEN** the adapter server runs as a service and the service is stopped
- **THEN** the service's log ends with a line saying the server stopped on SIGTERM and how many PCs were connected

### Requirement: Root installs of the server
`canworks-diag adapter-serve --install-service --service-user USER` SHALL install the service to run as USER when root runs it without `SUDO_USER`, with the token's verifier in USER's settings folder; USER root SHALL be refused. `--token-verifier-file FILE` SHALL store the verifier in FILE (made with the token elsewhere) instead of making or reading a token, and SHALL be refused when FILE does not hold a valid verifier. Without a token option an install SHALL keep the stored verifier.

#### Scenario: Installed by a root job
- **WHEN** root runs `canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500 --install-service --service-user pi --token-verifier-file v`
- **THEN** the unit runs as `pi`, `~pi/.config/canworks/adapter-serve.json` holds the verifier from `v`, no token is printed, and a PC logs in with the token the verifier was made from

### Requirement: Service reinstall
An `--install-service` SHALL restart a service that runs, so other options take effect at once, and `--without-discovery` SHALL leave the Avahi file out, removing one an earlier install wrote.

#### Scenario: Read-only and unadvertised
- **WHEN** the server was installed with `--allow-changes` and is installed again without it and with `--without-discovery`
- **THEN** the service restarts read-only with the same token, and its Avahi file is gone

### Requirement: Adapter server install script
Each release SHALL ship `scripts/install-adapter.sh` (`--version`, `--file`, `--adapter`, `--bitrate`, `--user`, `--port`, `--allow-changes`, `--without-discovery`, `--verifier-file`). It SHALL first check for `python3` 3.11 or newer and the `openssl` command and stop with one sentence naming what is missing. It SHALL install the release's adapter server file as `/opt/canworks-adapter/canworks-adapter.pyz` unless that version is there, from `--file PATH` when given and otherwise downloaded from the release, SHALL remove an `/opt/canworks-adapter/venv` left by an older install, and SHALL NOT run pip, make a venv or install packages. It SHALL add the user to `dialout` for a serial adapter and install the server with `--install-service --service-user`. It SHALL print `::canworks-step` lines and never a token.

#### Scenario: Device with the bridge
- **WHEN** the script runs for release X on a device whose `/opt/canworks-adapter/canworks-adapter.pyz` is the file of X
- **THEN** it downloads nothing and only installs and starts the service

#### Scenario: Uploaded file on a device without internet
- **WHEN** the script runs with `--version X --file /tmp/up/canworks-adapter-X.pyz` on a device that cannot reach github.com
- **THEN** the file is installed and the service started, and nothing is downloaded

#### Scenario: No openssl
- **WHEN** the script runs on a device without the `openssl` command
- **THEN** it stops before installing anything, saying that the adapter server needs the `openssl` command

### Requirement: Adapter server uninstall
`install-adapter.sh --uninstall --adapter TYPE:CHANNEL` SHALL remove that server and its Avahi file and nothing else; `--uninstall` alone SHALL remove every adapter server, and the last one removed SHALL take the installed file (and an old venv) with it. CI SHALL run `shellcheck` on the script and test install and uninstall with a stub download and systemctl.

#### Scenario: Uninstall one server
- **WHEN** servers run on can0 and can1 and the script runs with `--uninstall --adapter socketcan:can1`
- **THEN** `canworks-adapter-can1.service` is gone, the can0 server keeps running, and `/opt/canworks-adapter/canworks-adapter.pyz` is still there

### Requirement: Adapter server file
Each `deploy-v` release SHALL attach `canworks-adapter-<version>.pyz` and `install-adapter.sh` as assets. The file SHALL run `canworks-diag` (`python3 FILE COMMAND …`, `adapter-serve` included) on Python 3.11 or newer with only the standard library, and `--version` SHALL print the release version.

#### Scenario: Bare Python
- **WHEN** the file is copied to a Linux machine with Python 3.11, no pip packages and no network, and the user runs `python3 canworks-adapter-X.pyz adapter-serve --adapter socketcan:can0 --bitrate 500 --allow-changes`
- **THEN** the server starts and prints its token, and a PC with the tools scans, reads and writes SDOs through it as with a server from the installed PC tools

### Requirement: Adapter server file contents
The file SHALL carry canworks without the configurator, the editor library, the Node-RED package and the CODESYS code, and python-can and pyserial with their pure-Python dependencies at the release's locked versions, and no other package. It SHALL be at most 2 MB.

#### Scenario: Release asset
- **WHEN** release X is created
- **THEN** `canworks-adapter-X.pyz` is at most 2 MB and holds no `canworks/configurator/`, no `cantools`, no `paramiko` and no compiled extension

### Requirement: Adapter server file on an old Python
On a Python older than 3.11 the file SHALL exit with status 1 and one sentence saying that it needs Python 3.11 or newer.

#### Scenario: Old Python
- **WHEN** the user runs the file with Python 3.9
- **THEN** it exits with status 1 saying that it needs Python 3.11 or newer, and starts nothing

### Requirement: Service from the file
`adapter-serve --install-service` run from the file SHALL write the unit's `ExecStart` as the Python that runs it and the file's absolute path, followed by the server options.

#### Scenario: Installed from the file
- **WHEN** root runs `python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve --adapter socketcan:can0 --bitrate 500 --install-service --service-user pi`
- **THEN** the unit's `ExecStart` starts `/usr/bin/python3 /opt/canworks-adapter/canworks-adapter.pyz adapter-serve` with those options, and the service runs after a reboot
