## MODIFIED Requirements

### Requirement: Simulator commands in the command-line client
`canworks-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to the plugin's simulated devices with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments, fault kind names and output as `canworks-canopen-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `canworks-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a runtime that simulates node 5, with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history

#### Scenario: NMT state fault
- **WHEN** a user runs `canworks-diag sim fault 5 nmt-state stopped --sim localhost`
- **THEN** simulated node 5 goes to STOPPED, as with `canworks-canopen-sim fault 5 nmt-state stopped`, and `canworks-diag sim fault 5 nmt stopped` is refused as an unknown fault kind

### Requirement: Encrypted clients
`canworks-diag`, the configurator and `canworks-canopen-sim` SHALL connect with TLS, log in with SCRAM-SHA-256 bound to the certificate they received, and check the plugin's server signature before using any answer; a wrong signature SHALL drop the connection with "the runtime could not prove it knows this project's token". They SHALL NOT validate the certificate chain or pin a certificate. They SHALL NOT fall back to an unencrypted connection.

#### Scenario: Wrong signature
- **WHEN** a machine in the middle answers the client's login with a signature made without the verifier
- **THEN** the client drops the connection saying the runtime could not prove it knows this project's token, and sends no request
