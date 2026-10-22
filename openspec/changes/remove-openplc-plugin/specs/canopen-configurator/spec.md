## MODIFIED Requirements

### Requirement: Project target
A project SHALL have one target: "OpenPLC" (default; OpenPLC Runtime through its Modbus master and the bridge), "Modbus bridge" or "CODESYS", chosen in a "Project target" field on the Project page (see "Network tree") and shown in the header, where the badge opens the Project page. No network's Bus page and no Modbus bridge page SHALL have the field. The target SHALL come from the config: a `bridge` object holding `openplc` makes it OpenPLC, any other `bridge` object Modbus bridge, a `codesys` object CODESYS. A config with neither (a config of the removed OpenPLC plugin) SHALL open read-only with one message saying the plugin is no longer supported, with **Switch to OpenPLC through Modbus**, which repacks the locations for the bridge, adds `"bridge": {"openplc": {}, "writers": ["127.0.0.1"]}` and removes what the bridge does not use (including `axis`, `sync_source`, `sync_cycles` and `scan_watchdog_ms`), as one undo step. Until the switch the page SHALL NOT save the config.

#### Scenario: Target shown
- **WHEN** the user opens a config with a `codesys` object
- **THEN** the Project page's Project target field and the header show CODESYS

#### Scenario: Plugin config opened
- **WHEN** the user opens a config with no `bridge` and no `codesys` object, whose master has `"sync_source": "plc_cycle"` and whose node `drive` has `axis`
- **THEN** the message offers Switch to OpenPLC through Modbus and Save is disabled; after the switch the config has `bridge.openplc`, no `sync_source` and no `axis`, timer SYNC is asked for in Problems, and one Undo restores the plugin config

### Requirement: Only what the target uses is shown
The page SHALL hide every field, table column, choice option, fieldset, node tab, tree entry, menu item, page and start-page action that the project's target does not use, as the relevance table of `canopen-config-contract` lists them, whether or not the config has a value for it, and SHALL NOT list, mark or ask about such values (Requirement: Settings the target does not use are left out on save). Hints, labels and page texts that differ between targets SHALL use the project target's wording: a bridge or CODESYS project SHALL NOT be told about the plugin, the Linux device, the PLC scan or PLC locations where they do not apply. The editor project's address scan line SHALL be shown for OpenPLC only. A section SHALL be hidden only when none of its controls is left, and a section whose settings the target does not use (the Emergency section for CODESYS) SHALL not be drawn. A node tab left with nothing SHALL say in one line that the target does not use its settings instead of staying blank. The same rules SHALL apply to all three targets. No target SHALL show a CiA 402 axis setting, a scan watchdog, SYNC from the PLC cycle or a Variable declarations page: they no longer exist.

#### Scenario: CODESYS project
- **WHEN** the project's target is CODESYS
- **THEN** the page shows no IEC location fields or column, status locations, SDO variables, EDS lint, simulated devices, raw CAN messages, gateway, Online access, Emergency section or OpenPLC Editor project actions, and the protocol choice offers only CANopen master

#### Scenario: Bridge project
- **WHEN** the project's target is Modbus bridge
- **THEN** the Project menu has no editor project actions and the Bus page's role hint says the bridge is the network's master

#### Scenario: OpenPLC project
- **WHEN** the project's target is OpenPLC
- **THEN** no Modbus bridge or CODESYS page, field or action is shown

#### Scenario: Leftover value
- **WHEN** a CODESYS project still has `on_plc_stop` set to `keep`
- **THEN** the field is hidden, nothing on the page or in Problems mentions it, and the next save leaves it out

#### Scenario: Leftover location in a CODESYS project
- **WHEN** a CODESYS project's node `dio` has one TPDO entry with `iec_location` `%IW100`
- **THEN** the node's PDO table has no PLC location column and the PDOs tab shows nothing about it

#### Scenario: Leftover simulate in a CODESYS project
- **WHEN** a CODESYS project's node has `simulate` set
- **THEN** the node has no Simulation tab and no simulated mark

#### Scenario: Supervision with the EDS's own settings in a CODESYS project
- **WHEN** a CODESYS project's node has no heartbeat or guarding settings (Method "EDS default") and the user opens its Supervision tab
- **THEN** the Method choice is shown, there is no Emergency section, and the tab is not blank

#### Scenario: Wording guard
- **WHEN** the browser tests open every page and node tab of a config with every setting set, once per target
- **THEN** no field the target does not use is visible, no node tab is blank, and no visible text uses another target's words (for CODESYS: the bridge, the Linux device, PLC location, an IEC address, OpenPLC), apart from the Project target field's help

## REMOVED Requirements

### Requirement: CiA 402 axis setting
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Map CiA 402 objects
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Map CiA 402 objects on a fixed-mapping device
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Axis lines in the declarations
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: None; drive objects can still be mapped as plain PDO values.

### Requirement: Located variable declarations
**Reason**: The Variable declarations page served the plugin target's located variables; an OpenPLC project now gets the generated `canworks` variable list (canopen-editor-project, change add-openplc-modbus-target).
**Migration**: **Update declarations** on the Project page.

### Requirement: Declarations at a glance
**Reason**: The Variable declarations page served the plugin target's located variables; an OpenPLC project now gets the generated `canworks` variable list (canopen-editor-project, change add-openplc-modbus-target).
**Migration**: **Update declarations** on the Project page.
