## ADDED Requirements

### Requirement: Raw messages in the schema
The version 2 JSON Schema SHALL describe protocol `none`, `adapter.listen_only` and the `raw` object with its `rx`, `tx` and signal entries, so an editor with JSON Schema support completes and checks them. Checks the schema cannot express (unique `tx` identifiers, signals inside the DLC, protocol ownership, location sizes and clashes) SHALL be made by the plugin and by the PC tools with the same messages, from shared test fixtures.

#### Scenario: Schema check of a raw message
- **WHEN** a config's `raw.rx` entry has `id` 0x800 without `extended`
- **THEN** the PC tools and the plugin both reject it naming the path and the 11-bit range

### Requirement: Configs with raw messages are version 2
A version 1 config SHALL NOT have `raw` or `listen_only`. Writers SHALL save version 2 whenever any network has `raw` or protocol `none`.

#### Scenario: Adding a raw message to a version 1 project
- **WHEN** the configurator adds a raw message to a project whose file is version 1
- **THEN** it saves the file as version 2 with one network holding the old content and the raw message
