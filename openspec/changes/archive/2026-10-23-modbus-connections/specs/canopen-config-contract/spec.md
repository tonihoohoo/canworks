## MODIFIED Requirements

### Requirement: Config target
A config SHALL target one system: the Modbus bridge when it has a top-level `bridge` object, CODESYS when it has a top-level `codesys` object. A config with both SHALL be an error. A config with neither SHALL be refused by the bridge, the deploy tool and the check with one message: it is for the removed OpenPLC plugin, and the configurator's **Use with canworks-bridge** converts it. A CODESYS config SHALL be version 2.

#### Scenario: Both markers
- **WHEN** a config has both `bridge` and `codesys`
- **THEN** the check fails saying a config targets one system

#### Scenario: OpenPLC through Modbus
- **WHEN** a config has a `bridge` object with `plc_link` true and an `openplc` entry in `connections`
- **THEN** its target is the Modbus bridge and `canworks-bridge` runs it

#### Scenario: Old plugin config
- **WHEN** `canworks-bridge --check-only` or `canworks-deploy --check` runs on a config with neither `bridge` nor `codesys`
- **THEN** it exits non-zero with the message naming **Use with canworks-bridge**, and nothing is started or uploaded
