## ADDED Requirements

### Requirement: Bridge install and the device's remote link
The probe SHALL report the config the remote link serves. For a bridge install on a device whose remote link serves another config, the page SHALL grey the **Remote link** option with a hint that the link stays, and the job SHALL NOT pass `--with-link`.

#### Scenario: Bridge on a PLC device
- **WHEN** the device's remote link serves the PLC's config and the project is a bridge project
- **THEN** **Options** shows **Remote link** greyed with "The device's remote link serves another config (the PLC's) and stays as it is.", and the install leaves the link alone
