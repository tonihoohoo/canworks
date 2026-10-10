## ADDED Requirements

### Requirement: Remembered runtimes in the diagnostics client
`canworks-diag --runtime NAME` SHALL accept the name of a remembered runtime and connect by the automatic path choice of the remote link; `--runtime link:NAME` SHALL force the link. A name that is neither remembered nor resolvable SHALL fail with a message suggesting `canworks-diag discover`.

#### Scenario: Status over the link
- **WHEN** `canworks-diag --runtime line3 status` runs away from the LAN and the PC is paired
- **THEN** the status is printed as for a direct connection, followed by the path (`internet direct` or `internet relayed`) and the round trip

### Requirement: Automatic pairing in the diagnostics client
After a successful direct login to a runtime whose link ID is known, `canworks-diag` SHALL pair the PC with the same token in the background when it is not yet paired, and SHALL print one line when pairing succeeded or failed for a reason other than scope.

#### Scenario: First command on the LAN
- **WHEN** `canworks-diag --runtime line3.local status` runs for the first time on the LAN with the right token
- **THEN** the status is printed and a line says this PC is now paired with `line3`

### Requirement: Timeouts follow the round trip
The diagnostics client SHALL measure the round trip on connect and every 10 seconds and use max(the request's timeout, 4 × round trip + 500 ms) for each request.

#### Scenario: Relayed path
- **WHEN** the measured round trip is 400 ms and an SDO read has the default 1000 ms timeout
- **THEN** the client waits up to 2100 ms for the answer
