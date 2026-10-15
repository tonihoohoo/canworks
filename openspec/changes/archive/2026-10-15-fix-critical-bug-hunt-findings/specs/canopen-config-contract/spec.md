## ADDED Requirements

### Requirement: Number strings are decimal or hex
A number written as a JSON string SHALL be read as decimal, or as hex with a `0x` or `0X` prefix, by the schema, the PC tools and the plugin alike. A string with a leading zero other than `"0"` itself SHALL be refused by all of them with the same message, which names the field and suggests the decimal and hex spellings. No tool SHALL read a number string as octal.

#### Scenario: Leading zero
- **WHEN** a config has `"node_id": "012"`
- **THEN** the configurator, `canworks-deploy` and the plugin all refuse it with "leading zero: write 12 or 0x0C", and nothing is deployed

#### Scenario: Hex and decimal
- **WHEN** a config has `"cob_id": "0x200"` and `"node_id": "12"`
- **THEN** every tool and the plugin read COB-ID 0x200 and node 12

### Requirement: No repeated keys
A config object that has the same key twice SHALL be refused by the PC tools and by the plugin, naming the key and the object's path.

#### Scenario: Node ID twice
- **WHEN** a node object has `"node_id": 5` and later `"node_id": 6`
- **THEN** the configurator check and the plugin both refuse the config naming `node_id`
