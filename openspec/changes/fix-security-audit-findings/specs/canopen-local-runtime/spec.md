## ADDED Requirements

### Requirement: Certificate changes are refused
The saved certificate fingerprint SHALL be replaced only by `canworks-sim-runtime start` right after it created or recreated the container itself. Any other time the local runtime answers with a different certificate, the tools SHALL stop before sending credentials and name `canworks-sim-runtime start`. The password SHALL be printed only by `status --show-password`.

#### Scenario: Another program on the port
- **WHEN** another program answers on the local runtime's port with its own certificate and `canworks-deploy --runtime local` runs
- **THEN** the tool stops before logging in and says the certificate changed
