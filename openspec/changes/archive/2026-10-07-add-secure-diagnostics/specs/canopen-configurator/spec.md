## MODIFIED Requirements

### Requirement: Online access settings
The master settings SHALL have an "Online access" section that turns `master.diagnostics` on and off and edits its port, bind address and "allow changes" (off by default, with a warning that anyone with the token can then write parameters and stop nodes). Turning it on SHALL generate a random token of at least 128 bits, write only its SCRAM-SHA-256 verifier to `token_verifier`, and keep the token in the configurator's own settings on this PC for this project, never in the project folder. The page SHALL let the user copy the token, enter an existing token (for a project set up on another PC, checked against `token_verifier`), and generate a new one. When a project's config still has the former `token_sha256`, the section SHALL say that the token must be set again for the encrypted channel and, when this PC holds the matching token, offer **Upgrade**, which replaces `token_sha256` with a `token_verifier` for the same token; otherwise **New token** or **Enter token…** replaces it. The runtime host for online access SHALL be stored with the token and default to the host last used by the deploy tool when known.

#### Scenario: Enable online access
- **WHEN** the user turns on online access in a project and saves
- **THEN** `canopen.json` has `master.diagnostics` with `token_verifier` and neither the token nor `token_sha256`, and the configurator's settings hold the token for this project

#### Scenario: Token from another PC
- **WHEN** the project already has `token_verifier` and this PC has no token for it
- **THEN** the online view asks for the token and accepts it only if it matches the verifier

#### Scenario: Upgrade an old project
- **WHEN** the project has `token_sha256`, this PC holds its token, and the user presses **Upgrade** and saves
- **THEN** `canopen.json` has a `token_verifier` for the same token and no `token_sha256`, and the copied token still works after the next upload

### Requirement: Online view
With online access set up, the configurator SHALL offer an online view that connects to the runtime over the encrypted channel, refreshes about twice a second, and shows the bus state and counters, the master state, and for each node its state, status bit, boot result with error text, retry and hold state, last EMCY with class, SDO variable values and status, and a mark on each monitored TPDO that is timed out with its timeout count, using the node names from the config. Opening a node SHALL show its EMCY history with times and CiA 301 error classes, and for each monitored TPDO its timeout, count and time since its last PDO. When the runtime's config fingerprint differs from the saved `canopen.json`, the view SHALL say that the runtime runs a different configuration. Connection failures SHALL be shown with the reason (host unreachable, port closed, wrong token, runtime could not prove the token, plugin too old for encryption, no CANopen session) and retried.

#### Scenario: Watch a node come back
- **WHEN** the online view is open and node 23's cable is plugged back in
- **THEN** within about a second node 23's state goes from 0 to 127 to 5 and its boot result shows success

#### Scenario: Different config on the runtime
- **WHEN** the user saved a change but has not uploaded it yet
- **THEN** the online view shows that the runtime runs a different configuration

#### Scenario: Timed-out PDO
- **WHEN** node 23 is OPERATIONAL and its monitored TPDO 1 has timed out
- **THEN** node 23's row stays green for its state and shows "TPDO 1 timed out" with the count

#### Scenario: Plugin too old
- **WHEN** the runtime's plugin does not complete a TLS handshake
- **THEN** the view says the runtime's plugin is too old for encrypted diagnostics and must be updated, and offers no unencrypted connection
