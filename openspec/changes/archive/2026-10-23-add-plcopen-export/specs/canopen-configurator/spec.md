## ADDED Requirements

### Requirement: Export for another PLC
Export ▾ → For the program SHALL offer **For another PLC (PLCopen XML)…** on Modbus bridge configs only, not on OpenPLC or CODESYS configs. Its dialog SHALL ask for the PLC (CODESYS as a Modbus client of the bridge, truST, Other PLC with PLCopen XML), the bridge address the PLC uses (default: `listen` when it is neither a wildcard nor a loopback address), whether to include the library (on), and for CODESYS the optional PLC and Ethernet interface names.

#### Scenario: Only on Modbus bridge configs
- **WHEN** the user opens Export ▾ on an OpenPLC config
- **THEN** For the program has no For another PLC (PLCopen XML)… item

### Requirement: CODESYS route explained
Under the CODESYS choice the dialog SHALL say that CODESYS only reads and writes the bridge's registers while canworks-bridge runs the CAN networks, and SHALL link to the Project page to switch the project target to CODESYS when CODESYS should run the CANopen master itself.

#### Scenario: CODESYS chosen
- **WHEN** the user picks CODESYS in the dialog
- **THEN** the line under it explains the Modbus client route and its link opens the Project page's target field

### Requirement: Export for another PLC download
The dialog SHALL download `<config name>-<target>.zip` with the same files `canworks-deploy --export-plcopen` writes for those settings. On a config without `plc_link` the dialog SHALL say so and offer **Turn on the PLC link and repack**, one undo step.

#### Scenario: Export for CODESYS
- **WHEN** the user exports a bridge config with `plc_link` for CODESYS with bridge address 192.168.10.5
- **THEN** the zip holds `canworks.xml`, the plan with host 192.168.10.5 and `import_canworks_modbus.py`, equal to the command-line export

#### Scenario: PLC link off
- **WHEN** the config has no `plc_link` and the user opens the dialog
- **THEN** the dialog explains the PLC link and offers to turn it on and repack, and Undo restores the previous layout

### Requirement: Reachability warnings for other PLCs
On a bridge config with `plc_link` and without `openplc`, Problems SHALL warn when `listen` is a loopback address ("only a program on the bridge's own device can reach it"), and the export dialog SHALL warn when its bridge address is empty or the PLC address entered is not covered by `writers`.

#### Scenario: Loopback listen
- **WHEN** a config with `plc_link` listens on `127.0.0.1:1502`
- **THEN** Problems shows the warning with a link to the bridge page's listen field
