## ADDED Requirements

### Requirement: Link service on the device
`canworks-link` SHALL run as the systemd service `canworks-link.service`, installed only with `--with-link`, and SHALL accept peer-to-peer connections (iroh, ALPN `canworks/link/1`). It SHALL make its secret key on first start (`/etc/canworks-link/secret.key`, mode 0600) and keep it across restarts. A connection from a PC that is not paired SHALL only be allowed to open a `pair` stream; any other stream SHALL be closed with `not paired`.

#### Scenario: Paired PC connects
- **WHEN** a paired PC connects
- **THEN** the connection is accepted and the log shows the PC's name and whether the path is direct or relayed

#### Scenario: Unpaired PC asks for diagnostics
- **WHEN** a PC that is not paired opens a `diag` stream
- **THEN** the stream is closed with `not paired`, nothing connects to the diagnostics port, and the log shows `link: refused unpaired <short ID>` at most once a minute per ID

### Requirement: Pairing with the diagnostics token
On a `pair` stream the service SHALL run a SCRAM-SHA-256 exchange against the `token_verifier` of the deployed config, with channel binding SHA-256 of `"canworks-link-pair"`, the device's link ID and the PC's link ID, and SHALL add the PC (link ID and the name it sent) to `/etc/canworks-link/paired.json` only when the proof is correct. Both sides SHALL verify each other's proof. Failed attempts SHALL be limited to one per second per PC and 10 per minute in total, and logged. With no deployed config or no `token_verifier`, pairing SHALL be refused with `no token configured`.

#### Scenario: First connection on the LAN
- **WHEN** a PC on the same LAN logs in to the runtime directly with the right token and the configurator opens a `pair` stream with the same token
- **THEN** the PC is paired, the log shows `link: paired PC <name> (lan)`, and the token never crosses the network

#### Scenario: Wrong token
- **WHEN** a PC tries to pair with a wrong token
- **THEN** pairing fails with `wrong token`, the PC stays unpaired, and an immediate second attempt from the same PC is delayed by one second

### Requirement: Pairing scope
`diagnostics.remote_link.pairing` SHALL decide where token pairing is accepted: `"lan"` (default) only on a direct path from a private or link-local address (10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7, fe80::/10), `"anywhere"` on any path, `"off"` never. `sudo canworks-link allow ID [--name NAME]` SHALL pair a PC on the device regardless of the scope.

#### Scenario: Pairing from the internet refused by default
- **WHEN** `pairing` is `"lan"` and a PC tries to pair over a relayed path with the right token
- **THEN** pairing is refused with `pairing only on the local network`

### Requirement: Fixed forwarding targets
For paired PCs, each stream SHALL start with a target name, and the service SHALL forward only `diag` (127.0.0.1 and the deployed config's diagnostics port, default 7531) and `runtime` (127.0.0.1:8443; not on a bridge). A stream naming any other target SHALL be closed without connecting anywhere. The service SHALL NOT forward to any address other than 127.0.0.1.

#### Scenario: Unknown target
- **WHEN** a paired PC opens a stream for target `ssh`
- **THEN** the stream is closed and nothing connects to port 22

#### Scenario: Diagnostics not listening
- **WHEN** the PLC is stopped and a paired PC opens a `diag` stream
- **THEN** the stream is closed with `diagnostics not listening`, and the `runtime` target still works

### Requirement: Internet access from the config
The service SHALL read `diagnostics.remote_link` from the deployed config and apply changes within 5 seconds of the file changing. With `internet` false or absent it SHALL use no relay and no address lookup service, so it contacts nothing outside the local network. With `internet` true it SHALL use the listed `relays`, or the iroh project's public relays when the list is empty or absent, and publish its address for lookup.

#### Scenario: Off by default
- **WHEN** the deployed config has no `remote_link` and the device has no route to the internet
- **THEN** the service runs, paired PCs on the local network connect directly, and the service makes no connection to any outside address

#### Scenario: Ticked and uploaded
- **WHEN** a config with `remote_link.internet` true is uploaded and the device is behind NAT
- **THEN** within 5 seconds a paired PC on another network can connect, first through a relay and directly when hole punching succeeds, and the log shows each path change

### Requirement: Managing paired PCs
A paired PC SHALL be able to open a `manage` stream that, after the same SCRAM proof as pairing, lists paired PCs (name, paired, last seen) and removes one. Any paired PC SHALL be able to remove itself without the token. On the device, `canworks-link list` and `canworks-link revoke ID|NAME` SHALL do the same. Removing a PC SHALL close its open connections within one second.

#### Scenario: Remove while connected
- **WHEN** a PC is removed while it has an open diagnostics session
- **THEN** the session ends within one second and the PC's next `diag` stream is refused with `not paired`

### Requirement: Limits
The service SHALL accept at most 4 connected PCs and 16 streams per PC, and SHALL close a stream idle for 10 minutes.

#### Scenario: Fifth PC
- **WHEN** four PCs are connected and a fifth paired PC connects
- **THEN** it is closed with `too many peers`

### Requirement: PC identity and remembered runtimes
The PC tools SHALL keep one link secret key per user, made on first use and readable only by that user, and SHALL remember each runtime they connected to (name, addresses, link ID, relays, last path) in the user's configuration directory. `canworks-diag link list` and `link forget NAME` SHALL show and remove remembered runtimes. On a platform without the iroh package, link features SHALL be reported as unavailable on this platform while direct connections keep working.

#### Scenario: Remembered after the first connection
- **WHEN** a PC connects once to a discovered runtime `line3`
- **THEN** `line3` appears in `canworks-diag link list` with its address and link ID

### Requirement: Automatic path choice
Connecting to a remembered runtime SHALL try a direct connection to its known addresses and, after 300 ms or as soon as the direct attempt fails, the link when the PC is paired, and SHALL use whichever completes the TLS and SCRAM login first. An explicit address SHALL use only the direct path and `link:NAME` only the link.

#### Scenario: Away from the LAN
- **WHEN** the user picks `line3` from home and the runtime's LAN address is unreachable
- **THEN** the tools connect through the link without any extra step, and show `internet direct` or `internet relayed`

### Requirement: Local forward for other programs
`canworks-diag link open NAME [--diag-port P] [--runtime-port P]` SHALL listen on 127.0.0.1 only, print `diagnostics 127.0.0.1:P` and `runtime https://127.0.0.1:P`, and forward each local TCP connection over the chosen path until interrupted.

#### Scenario: Editor upload through the link
- **WHEN** `link open line3` runs away from the LAN and the OpenPLC Editor uploads a program to the printed runtime address
- **THEN** the program reaches the runtime over the link and the device's log shows the PC's connection

#### Scenario: Never on other interfaces
- **WHEN** `link open` runs
- **THEN** nothing listens on any address other than 127.0.0.1
