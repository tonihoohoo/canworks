## ADDED Requirements

### Requirement: Deploy over the remote link
`canworks-deploy --runtime link:NAME` SHALL deploy through the remote link's `runtime` target, with the same login and certificate fingerprint check as a direct deploy.

#### Scenario: Fingerprint unchanged
- **WHEN** a deploy runs over the link with `--fingerprint`
- **THEN** the runtime's certificate is checked against the fingerprint exactly as on a direct connection, and a mismatch stops the deploy before the password is sent

### Requirement: Pairing over SSH
`canworks-deploy link pair --ssh USER@HOST [--name NAME]` SHALL add this PC's link ID to the device's allow-list over SSH (using `sudo canworks-link allow`), read the device's link ID back and save the runtime as NAME (default: the host name).

#### Scenario: Pair and connect
- **WHEN** `link pair --ssh` succeeds
- **THEN** `canworks-diag --runtime link:NAME status` works from this PC without further setup
