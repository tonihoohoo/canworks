## MODIFIED Requirements

### Requirement: Simulator commands in the command-line client
`canworks-diag` SHALL have `sim` subcommands (`status`, `get`, `set`, `override`, `release`, `source`, `fault`, `clear`, `scenario start|stop|list`) that talk to the plugin's simulated devices with `--runtime` or to a standalone simulator with `--sim HOST[:PORT]`, with the same arguments, fault kind names and output as `canworks-sim`'s own subcommands.

#### Scenario: Fault from the PC
- **WHEN** a user runs `canworks-diag sim fault 5 emcy 0x5000 --register 1 --runtime plc.local` against a runtime that simulates node 5, with `allow_changes`
- **THEN** simulated node 5 sends EMCY 0x5000 and the online view shows it in node 5's EMCY history

#### Scenario: NMT state fault
- **WHEN** a user runs `canworks-diag sim fault 5 nmt-state stopped --sim localhost`
- **THEN** simulated node 5 goes to STOPPED, as with `canworks-sim fault 5 nmt-state stopped`, and `canworks-diag sim fault 5 nmt stopped` is refused as an unknown fault kind
