## MODIFIED Requirements

### Requirement: LSS node settings
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1` (left out or 0), both checkboxes SHALL be disabled and unticked, with the reason next to them ("This device's EDS has no LSS (LSS_Supported=1 missing)"). A loaded node that still has an `lss` object SHALL show it as a problem with the plugin's message and offer to remove it. Saving SHALL be refused until it is removed or the node gets an EDS with LSS.

#### Scenario: Turn on LSS for a node
- **WHEN** the user ticks "Assign node ID by serial number (LSS)" for node 12, enters serial number 0x1234 and saves
- **THEN** node 12 has `"lss": {"assign": true}` and `"serial_number"` 0x1234 (kept as typed, like the other identity fields), and no `lss.store`

#### Scenario: Assign without a serial number
- **WHEN** "Assign" is ticked for node 12 and its serial number is empty
- **THEN** saving is refused and the serial number field says it is needed for LSS

#### Scenario: EDS without LSS
- **WHEN** the user adds a node whose EDS says `LSS_Supported=0`
- **THEN** both LSS checkboxes are disabled with the reason, and the saved node has no `lss`

### Requirement: Unconfigured devices in the online view
When the runtime allows changes, the online view SHALL offer an "Unconfigured devices" panel that finds a device without a node ID through the runtime, shows its vendor ID (with the vendor name when an EDS gives it), product code, revision and serial number and a matching EDS when one is found (as on the scan page), and offers "Set node ID" and "Set bit rate" for it. Both dialogs SHALL have a "Store in the device" checkbox that is unticked each time the dialog opens. "Set node ID" SHALL suggest the lowest node ID that is neither configured nor the master's and SHALL offer, after success, to add the device as a node with that ID and EDS (as the scan page adds a found device), with `serial_number` and `lss.assign` set. "Set bit rate" SHALL say before sending that the device switches after its next power cycle and that the adapter bit rate must be changed to match. When the runtime does not allow changes the panel SHALL be shown disabled with the reason.

When the matching EDS does not say `LSS_Supported=1`, the device SHALL be added without `lss.assign`, and the page SHALL say that its EDS has no LSS, so the node gets no LSS assignment.

#### Scenario: Commission a new sensor
- **WHEN** the user finds a device without node ID, sets node ID 40 with "Store in the device" ticked, and accepts adding it as a node
- **THEN** the runtime sets and stores node ID 40, and the project gets node 40 with the matching EDS, the device's serial number and `"lss": {"assign": true}`, unsaved until the user saves

#### Scenario: Store unticked by default
- **WHEN** the user opens "Set node ID" a second time after storing once
- **THEN** the "Store in the device" checkbox is unticked

### Requirement: Use a scanned device for a node
On the scan page, a found device with a serial number SHALL offer "Use for node…", listing the configured nodes whose EDS vendor ID and product code match the device. Picking a node SHALL set that node's `serial_number` from the device and tick its `lss.assign`, unsaved until the user saves, and SHALL say that the device gets the node's ID at the next PLC start.

A configured node whose EDS does not say `LSS_Supported=1` SHALL be listed disabled with the reason ("its EDS has no LSS"), and SHALL NOT be picked.

#### Scenario: Replacement device
- **WHEN** node 12 is configured for a valve with serial 0x1234, the scan finds a valve with the same vendor ID and product code at node 5 with serial 0x5678, and the user picks "Use for node 12"
- **THEN** node 12 gets `serial_number` 0x5678 and `"lss": {"assign": true}`, and the page says the device becomes node 12 at the next start

#### Scenario: Matching node without LSS
- **WHEN** the only configured node matching a scanned device's vendor ID and product code has an EDS with `LSS_Supported=0`
- **THEN** "Use for node..." lists that node disabled, saying its EDS has no LSS, and nothing in the config changes

### Requirement: Commission a device without a config
The configurator's start page SHALL offer "Commission a device", which opens the online pages on a USB adapter without any project or config: scan, object dictionary view (EDS from the scan match in the EDS library, or picked by the user), LSS, Parameters (backup, compare, restore, store) and Trace. "Add as node" SHALL be offered only when a config is open; instead the mode SHALL offer "Add to a config…", which picks a project or standalone config folder and opens it with the device added as an unsaved node (node ID, EDS imported, serial number, and LSS assignment ticked when the node ID was set by LSS in this session and the device's EDS says `LSS_Supported=1`; with an EDS without LSS, the node is added without it and the page says why). The mode SHALL show a Steps panel listing Bit rate, Find the device, Node ID and bit rate, Identity and EDS, Write configuration, PDO test, Store, Verify after power cycle and Back up; each step SHALL open its panel and show done or skipped with a one-line result, steps SHALL be possible in any order or skipped, and none SHALL run by itself. In this mode the page SHALL show no config editing: no Project or Export menu, no Save, no Problems pane, and a side bar with only the online pages (Online, Scan the bus, Trace, Frame lab), so nothing suggests a config is being edited. This mode SHALL connect only through a USB adapter on this PC: the Connect form SHALL show the adapter form with no Runtime choice, whatever target the settings last held, and no text in this mode SHALL link to a page the mode does not show.

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

#### Scenario: Runtime choice not offered
- **WHEN** the user opens "Commission a device" on a PC whose online settings last used the Runtime target
- **THEN** the Online page shows the USB adapter form, with no Runtime choice and no "Online access is off for this config" text
