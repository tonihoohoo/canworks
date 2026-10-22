## MODIFIED Requirements

### Requirement: Config target
A config SHALL target one system: OpenPLC through Modbus when it has a top-level `bridge` object holding an `openplc` object, the Modbus bridge when it has a `bridge` object without one, CODESYS when it has a top-level `codesys` object. A config with both `bridge` and `codesys` SHALL be an error. A config with neither SHALL be refused by the bridge, the deploy tool and the configurator's check with one message: the config is for the removed OpenPLC plugin, and the configurator's **Switch to OpenPLC through Modbus** converts it. A CODESYS config SHALL be version 2.

#### Scenario: Both markers
- **WHEN** a config has both `bridge` and `codesys`
- **THEN** the check fails saying a config targets one system

#### Scenario: OpenPLC through Modbus
- **WHEN** a config has `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}`
- **THEN** its target is OpenPLC through Modbus and `canworks-bridge` runs it

#### Scenario: Old plugin config
- **WHEN** `canworks-bridge --check-only` or `canworks-deploy --check` runs on a config with neither `bridge` nor `codesys`
- **THEN** it exits non-zero with the message naming **Switch to OpenPLC through Modbus**, and nothing is started or uploaded

### Requirement: Bridge configs are byte-addressed
A config with a `bridge` object SHALL be a bridge config. Its locations SHALL be byte-addressed and checked as the modbus-bridge capability describes. Word, double and long locations (`%IW`, `%QD` and the like) SHALL be refused, naming the field.

#### Scenario: Bridge config uploaded to OpenPLC
- **WHEN** `canworks-deploy --config bridge.json --runtime HOST` is run with a bridge config
- **THEN** it fails as for any unknown option, since the deploy tool no longer uploads to an OpenPLC runtime

#### Scenario: Word location
- **WHEN** a bridge config's node has `status_location` `%IW10`
- **THEN** the bridge and the PC tools refuse it, naming the field and saying locations are byte-addressed

## REMOVED Requirements

### Requirement: Location overlaps in version 1 configs
**Reason**: Version 1 configs held word and bit locations of the plugin's image tables; overlaps on the bridge are byte overlaps, checked for every version by the bridge rules.
**Migration**: None.
