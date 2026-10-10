## ADDED Requirements

### Requirement: Link service on the device
`canworks-link` SHALL run as the systemd service `canworks-link.service`, installed only with `--with-link`, and SHALL accept peer-to-peer connections (iroh, ALPN `canworks/link/1`) only from PCs whose link ID is in `/etc/canworks-link/allow.json`. It SHALL make its secret key on first start (`/etc/canworks-link/secret.key`, mode 0600) and keep it across restarts. A connection from any other ID SHALL be closed with the reason `not paired` before any stream is accepted.

#### Scenario: Paired PC connects
- **WHEN** a PC whose link ID is on the allow-list connects
- **THEN** the connection is accepted and the log shows the PC's name or short ID and whether the path is direct or relayed

#### Scenario: Unpaired PC
- **WHEN** a PC whose link ID is not on the allow-list connects
- **THEN** the connection is closed with `not paired`, no stream is opened, and the log shows `link: refused unpaired <short ID>` at most once a minute per ID

#### Scenario: Empty allow-list
- **WHEN** the allow-list is empty
- **THEN** every connection is refused

### Requirement: Fixed forwarding targets
Each stream SHALL start with a target name, and the service SHALL forward only to the targets in `/etc/canworks-link/link.json` `targets` (default `diag` → 127.0.0.1:7531 and `runtime` → 127.0.0.1:8443; on a bridge `diag` only). A stream naming any other target SHALL be closed without connecting anywhere. The service SHALL NOT forward to any address other than 127.0.0.1.

#### Scenario: Unknown target
- **WHEN** a paired PC opens a stream for target `ssh`
- **THEN** the stream is closed and nothing connects to port 22

#### Scenario: Diagnostics not listening
- **WHEN** the PLC is stopped and a PC opens a `diag` stream
- **THEN** the stream is closed with `diagnostics not listening`, and the `runtime` target still works

### Requirement: Pairing and revoking
`sudo canworks-link allow ID [--name NAME]` SHALL add a PC's link ID, `canworks-link revoke ID` SHALL remove it and close that PC's open connections at once, and `canworks-link list` SHALL show paired PCs with their names. `canworks-link id` SHALL print the device's link ID. Changes SHALL take effect without restarting the service.

#### Scenario: Revoke while connected
- **WHEN** a paired PC has an open diagnostics session and the device runs `canworks-link revoke` for its ID
- **THEN** the session ends within one second and the PC's next connection is refused with `not paired`

### Requirement: Relays
`link.json` `relays` SHALL accept `"off"` (default; direct addresses only), `"default"` (the iroh project's public relays) or a list of relay URLs, set with `canworks-link enable --relays off|default|URL...`. With relays off the service SHALL not contact any server outside the local network.

#### Scenario: Relays off
- **WHEN** `relays` is `"off"` and the device has no route to the internet
- **THEN** the service runs, and a paired PC on the same network connects over a direct path

#### Scenario: Behind NAT with a relay
- **WHEN** `relays` names a self-hosted relay and the device is behind NAT
- **THEN** a paired PC on another network connects, first through the relay and directly when hole punching succeeds, and the log shows each path change

### Requirement: Limits
The service SHALL accept at most 4 connected PCs and 16 streams per PC, and SHALL close a stream idle for 10 minutes.

#### Scenario: Fifth PC
- **WHEN** four paired PCs are connected and a fifth paired PC connects
- **THEN** it is closed with `too many peers`

### Requirement: PC link identity and saved runtimes
The PC tools SHALL keep one link secret key per user in the user's configuration directory and SHALL print its link ID with `canworks-diag link id`. `canworks-diag link add NAME ID [--relay URL]...`, `link list` and `link remove NAME` SHALL manage saved runtimes. On a platform without the iroh package, every link command SHALL say the remote link is not available on this platform and exit non-zero.

#### Scenario: First use
- **WHEN** `canworks-diag link id` runs on a PC with no link key
- **THEN** a key is made, stored readable only by the user, and its link ID is printed

### Requirement: Local forward for other programs
`canworks-diag link open NAME [--diag-port P] [--runtime-port P]` SHALL open the link and listen on 127.0.0.1 only, print `diagnostics 127.0.0.1:P` and `runtime https://127.0.0.1:P`, and keep forwarding until interrupted. Each local TCP connection SHALL become one stream to the matching target.

#### Scenario: Editor upload through the link
- **WHEN** `link open` runs and the OpenPLC Editor uploads a program to the printed runtime address
- **THEN** the program reaches the device's runtime over the link and the device's log shows the PC's connection

#### Scenario: Never on other interfaces
- **WHEN** `link open` runs
- **THEN** nothing listens on any address other than 127.0.0.1
