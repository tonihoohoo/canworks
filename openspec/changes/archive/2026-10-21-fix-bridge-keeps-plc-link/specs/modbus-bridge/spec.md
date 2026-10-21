## ADDED Requirements

### Requirement: Bridge install keeps another config's remote link
`install-bridge.sh --with-link NAME` SHALL NOT repoint a remote link that serves another config (one not under `/etc/canworks-bridge/`, such as the PLC's). It SHALL skip the link step and say so.

#### Scenario: PLC device with a remote link
- **WHEN** the bridge is installed with `--with-link line3` on a device whose remote link serves `/opt/canworks/lib/canworks.json`
- **THEN** the link keeps serving that config and the output says the link step was skipped
