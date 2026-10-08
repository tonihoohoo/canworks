## MODIFIED Requirements

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open; instead the mode SHALL offer "Add to a config…", which picks a project or standalone config folder and opens it with the device added as an unsaved node (node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session). The mode SHALL show a Steps panel listing Bit rate, Find the device, Node ID and bit rate, Identity and EDS, Write configuration, PDO test, Store, Verify after power cycle and Back up; each step SHALL open its panel and show done or skipped with a one-line result, steps SHALL be possible in any order or skipped, and none SHALL run by itself. In this mode the page SHALL show no config editing: no Project or Export menu, no Save, no Problems pane, and a side bar with only the online pages (Online, Scan the bus, Trace, Frame lab), so nothing suggests a config is being edited.

#### Scenario: New device on the desk
- **WHEN** the user opens "Commission a device", connects to a CANable at 250 kbit/s with "Allow changes" on, finds an unconfigured device with LSS and gives it node ID 12
- **THEN** a scan lists node 12, and nothing was stored on the device unless the user ticked "store"

#### Scenario: Nothing to save
- **WHEN** the user opens "Commission a device"
- **THEN** the header shows the mode badge, the theme choice and Close only, the side bar lists Online, Scan the bus, Trace and Frame lab, and no problem is reported

#### Scenario: Guided commissioning
- **WHEN** the user detects the bit rate, gives the device node ID 12 by LSS, writes a configuration from a DCF and backs it up
- **THEN** the Steps panel marks Bit rate, Node ID and bit rate, Write configuration and Back up as done with their results, and Store as not done

#### Scenario: Carry the device into a config
- **WHEN** the user presses "Add to a config…" after setting node ID 12 by LSS and picks a standalone config folder
- **THEN** that config opens with node 12 added as an unsaved node with the device's EDS, serial number and LSS assignment ticked

## ADDED Requirements

### Requirement: Write configuration dialog
A node's Parameters tab SHALL have "Write configuration…" (also in the Commission a device steps), enabled only with Allow changes. It SHALL take a DCF file or a node of a config folder (the open config's own node by default when the target is not a runtime that configures it), show the plan from `canopen-device-commissioning` (writes with source value, device value and differs or same, PDO sequences grouped, communication writes marked, left-out entries with reasons, identity and node ID checks), and write only after the user confirms. "Hold in PRE-OPERATIONAL while writing" SHALL start ticked; "Restore defaults first" and "Store on device afterwards" SHALL start unticked every time the dialog opens. It SHALL run in the configurator like restore, with progress and Cancel, and show the result with the read-back verdict. "Verify" in the same dialog SHALL compare without writing.

#### Scenario: Plan before writing
- **WHEN** the user picks node5.dcf in Write configuration
- **THEN** the dialog lists the planned writes with both values, writes nothing until the user confirms, and both store and restore-defaults ticks are off

### Requirement: Restore defaults button
The Parameters tab SHALL have "Restore defaults…" next to "Store on device…", offered only when the EDS has 0x1011 and enabled only with Allow changes. It SHALL ask first, offer "Reset the node afterwards" (ticked), and show whether the device accepted it.

#### Scenario: Restore defaults asks
- **WHEN** the user presses Restore defaults… on node 5
- **THEN** a confirmation names node 5 and 0x1011, and nothing is written unless the user confirms

### Requirement: PDO test tab
On a USB adapter target, each node SHALL have a "PDO test" tab. It SHALL load the node's PDO layout from the open config when the node is configured, otherwise from the device, and show TPDOs with live decoded values, periods and counts, and RPDOs with an input per entry and Send. It SHALL offer NMT Start for the node, and SYNC with a period (off by default). Every control SHALL be disabled without Allow changes and say why. When another master is detected the page SHALL ask before using `force`. Leaving the tab or closing the page SHALL stop the test and the SYNC. On a runtime target the tab SHALL not be shown, because the PLC runs the PDOs there.

#### Scenario: Set an output
- **WHEN** the user types 15 in RPDO1's 0x6200:01 input and presses Send
- **THEN** the frame is sent and the RPDO's sent count goes up by one

### Requirement: Lone device in Detect
The adapter connect box's Detect and the Scan page's Detect bit rate on a USB adapter SHALL have "Only this device is on the bus", unticked by default. Ticked, it SHALL ask for confirmation that nothing else is on the bus and that the adapter's error frames will reach it at wrong rates, need Allow changes on the Scan page, and run the lone-device sweep with the LSS probe. A `silent` result without it SHALL suggest ticking it when a single device is on the bench.

#### Scenario: Bench device found
- **WHEN** the only device runs at 125 kbit/s, the user ticks "Only this device is on the bus", confirms and presses Detect
- **THEN** the form shows `125 kbit/s detected` and selects 125 kbit/s

### Requirement: Commissioning log
In Commission a device and on a USB adapter target, the configurator SHALL record every change made through the page in this session (SDO write, NMT, LSS set ID, set bit rate and store, write configuration, restore defaults, store) with UTC time, node, what was done and the result. "Save log" SHALL download `node<N>-commissioning-<time>.txt` with the device identity and EDS name at the top. The log SHALL not contain host names or tokens and SHALL not be written to any project.

#### Scenario: Save the record
- **WHEN** the user gave the device node ID 12, wrote a configuration and stored it, then pressed Save log
- **THEN** the file lists those three changes in order with their results
