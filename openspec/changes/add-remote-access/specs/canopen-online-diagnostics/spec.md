## ADDED Requirements

### Requirement: Link addresses in the diagnostics client
`canworks-diag --runtime link:NAME` SHALL open the remote link to the saved runtime NAME, run the usual TLS and SCRAM login over it, and close the link when the command ends. A NAME that is not saved SHALL fail with a message pointing to `canworks-diag link add`.

#### Scenario: Status over the link
- **WHEN** `canworks-diag --runtime link:line3 status` runs and the device is paired
- **THEN** the status is printed as for a direct connection, followed by the path (`link direct` or `link relayed`) and the round trip

#### Scenario: Not paired
- **WHEN** the device refuses the PC with `not paired`
- **THEN** the command fails with a message that prints this PC's link ID and the `canworks-link allow` command to run on the device

### Requirement: Timeouts follow the round trip
The diagnostics client SHALL measure the round trip on connect and every 10 seconds and use max(the request's timeout, 4 × round trip + 500 ms) for each request.

#### Scenario: Relayed path
- **WHEN** the measured round trip is 400 ms and an SDO read has the default 1000 ms timeout
- **THEN** the client waits up to 2100 ms for the answer
