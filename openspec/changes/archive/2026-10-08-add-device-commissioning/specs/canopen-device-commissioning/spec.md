## ADDED Requirements

### Requirement: Write a configuration to a device
The PC tools SHALL write a node's configuration to a live device over SDO from one of two sources: a node of a `canopen.json` (the writes the plugin makes to that node at boot, in the same order) or a CiA 306 DCF (every entry with access `rw`, `rwr` or `rww` that has a `ParameterValue`, with `$NODEID` resolved by the target node ID). They SHALL leave out, and list with the reason, 0x1010, 0x1011, 0x1F50 to 0x1F57, DOMAIN entries and DCF entries without an access type. It SHALL run on the PC over `sdo_read`, `sdo_write` and `nmt`, on a runtime and on a USB adapter, and SHALL need allow-changes.

#### Scenario: Configure from a config node over an adapter
- **WHEN** node 5 of a standalone config maps TPDO1 to two entries and has one startup SDO, and the user runs `openplc-canopen-diag --adapter slcan:COM5 --bitrate 250 --allow-changes configure 5 --config canopen.json --from-node 5 --yes` against a device at node 5
- **THEN** the device's 0x1A00 mapping, its 0x1800 parameters and the startup SDO entry hold the config's values, and the result says "verified"

#### Scenario: Configure from a DCF
- **WHEN** the user runs `configure 5 --dcf node5.dcf` with a DCF exported for node 5
- **THEN** each writable entry of the DCF that differs on the device is written, and 0x1010 is not written

#### Scenario: Without allow-changes
- **WHEN** `configure` runs on a connection without allow-changes
- **THEN** it is refused with "changes not allowed" and nothing is written

### Requirement: Configuration plan and preview
Before writing, the tools SHALL read each planned entry from the device and show the plan: each write in order with source value, device value and "differs" or "same", and each left-out entry with its reason. Only differing writes SHALL be sent, except that a PDO sequence SHALL be sent whole when any of its values differs. Without `--yes`, the CLI SHALL ask before writing. `--dry-run` SHALL show the plan and write nothing.

#### Scenario: Nothing to do
- **WHEN** `configure 5 --dcf node5.dcf` runs a second time on the same device
- **THEN** the plan shows every entry as "same" and no SDO write is sent

### Requirement: PDO write order
For each PDO in the plan, the tools SHALL write: the COB-ID with bit 31 set, mapping subindex 0 as 0, the mapping entries, mapping subindex 0 as the entry count, the other communication entries the source has, and the COB-ID as the source has it. Read-only communication entries SHALL be skipped. On a device whose mapping object is read-only or constant, no mapping writes SHALL be sent and the plan SHALL say so. A failed write inside a sequence SHALL skip the rest of that sequence, leave the PDO switched off, and continue with the next sequence.

#### Scenario: Remap a TPDO
- **WHEN** a DCF maps TPDO2 to 0x6401:01 and 0x6401:02 and the device has it mapped to 0x6000:01
- **THEN** the SDO writes go 0x1801:01 (off), 0x1A01:00=0, 0x1A01:01, 0x1A01:02, 0x1A01:00=2, then 0x1801:01 (on), in that order

#### Scenario: Mapping refused by the device
- **WHEN** the device aborts the write of 0x1A01:01
- **THEN** TPDO2 stays switched off, the result lists the abort code, the next PDO is still written, and the command exits non-zero

### Requirement: Configuration checks the device
A configuration write SHALL be refused, with nothing written, when the device's vendor ID or product code (0x1018) differs from the source's, unless the user overrides the identity check. A different revision SHALL be a warning. It SHALL be refused, naming both IDs, when the source's node ID differs from the target node. On a runtime, it SHALL be refused for a node in the running configuration, saying that the master writes that node's configuration at every boot.

#### Scenario: Wrong product
- **WHEN** the source is a valve's DCF and node 5 is a different product
- **THEN** the request is refused naming product code with both values

#### Scenario: Node the runtime configures
- **WHEN** `openplc-canopen-diag --runtime plc.local --allow-changes configure 5 --dcf node5.dcf` runs and node 5 is in the runtime's config
- **THEN** it is refused, saying the master writes node 5's configuration at every boot

#### Scenario: Different node ID
- **WHEN** the DCF's `[DeviceComissioning]` says NodeID=7 and the target is node 5
- **THEN** it is refused naming node 7 and node 5

### Requirement: Hold and read-back
By default the tools SHALL send NMT pre-operational to the node before the first write and SHALL put it back in OPERATIONAL after the last write only if it was OPERATIONAL before, also after a failure or cancel. `--no-hold` SHALL skip both. After writing, every planned entry SHALL be read again and compared with the source. The result SHALL list written, same, skipped and failed entries and any read-back difference, and SHALL say "verified" when there is none.

#### Scenario: Operational device
- **WHEN** the device's heartbeat says OPERATIONAL and `configure` runs
- **THEN** it gets NMT pre-operational before the first write and NMT start after the read-back

### Requirement: Store and restore defaults only on request
A configuration write SHALL NOT write 0x1010 or 0x1011 on its own. With `--store` (configurator: "Store on device afterwards", unticked whenever the dialog opens) the tools SHALL run the existing store after the write, and only when no write failed. With `--restore-defaults` (configurator: "Restore defaults first", unticked whenever the dialog opens) they SHALL write "load" to 0x1011 subindex 1 and reset the node before reading the plan. Both SHALL be offered only when the node's EDS lists the object.

#### Scenario: Store after a failure
- **WHEN** `configure 5 --dcf node5.dcf --store` has one failed write
- **THEN** 0x1010 is not written and the result says the store was skipped because of the failure

### Requirement: Restore defaults command
`openplc-canopen-diag restore-defaults NODE [--subindex N] [--reset] [--yes]` and the configurator's "Restore defaults…" SHALL write the "load" signature to 0x1011 (subindex 1 by default) after asking, only with allow-changes and only when the EDS lists that subindex. With `--reset` they SHALL then send NMT reset node. The result SHALL say whether the device accepted it and that the defaults take effect at the next reset or power cycle when no reset was sent.

#### Scenario: Back to factory settings
- **WHEN** the user runs `restore-defaults 5 --reset` and confirms
- **THEN** 0x1011:01 gets "load", node 5 gets NMT reset node, and after its boot-up the changed entries read their EDS defaults

### Requirement: Verify a configuration
`configure ... --verify-only` SHALL read the device and compare it with the source's planned values, write nothing, need no allow-changes, and list each difference. Its exit status SHALL be 0 when nothing differs and 1 otherwise.

#### Scenario: Not stored
- **WHEN** a device was configured without store and power-cycled, and `configure 5 --dcf node5.dcf --verify-only` runs
- **THEN** it lists the entries that went back to their defaults and exits 1

### Requirement: Commissioning tests
CI SHALL test configure from a config node and from a DCF against the standalone simulator on vcan, including a PDO remap, a dry run, the identity and node ID refusals, the runtime refusal for a configured node, `--verify-only` before and after a simulated power cycle with and without store, and `restore-defaults --reset`.

#### Scenario: CI
- **WHEN** the vcan CI job runs
- **THEN** the commissioning test configures the simulated device, verifies it, restores defaults and passes
