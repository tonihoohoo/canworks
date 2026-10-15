## ADDED Requirements

### Requirement: Device identity of heard nodes
While connected in Commission, and in Configure while connected to a runtime, the configurator SHALL read the identity of every node in the Nodes table without a scan: 0x1018 sub-indices 1-4, 0x1000, 0x1008, 0x1009 and 0x100A, with the connection's manual SDO read, one node at a time. Identity reads SHALL NOT need force or Allow changes.

#### Scenario: Heard nodes are read without a scan
- **WHEN** the user connects an adapter, nodes 23, 32 and 49 send heartbeats and no scan has run
- **THEN** the configurator reads each node's identity with SDO, one node at a time

### Requirement: When identity is read again
The configurator SHALL read a node's identity once per connection, again after the node boots up, and SHALL wait while the node is STOPPED. A scan's answer for a node SHALL count as its identity read.

#### Scenario: Stopped node
- **WHEN** node 49 is heard in STOPPED
- **THEN** its identity is read once the node goes pre-operational or operational

#### Scenario: New device on the same node ID
- **WHEN** node 23 is replaced by another device that boots up with node ID 23
- **THEN** node 23's identity is read again

#### Scenario: Scan then heard
- **WHEN** a scan has already read node 23
- **THEN** no identity read is sent for node 23 when its heartbeat is heard

### Requirement: Device names in the Nodes table
The Nodes table's Device column SHALL show, in full and wrapped when long, the first of: the device's name from 0x1008; the product name of a matching EDS in the project or EDS library; the device profile named by 0x1000 (such as "CiA 401 I/O device"); the vendor and product numbers. Muted text after it SHALL give the vendor (with the matching EDS's vendor name), product and profile not already shown.

#### Scenario: Heard nodes get their names
- **WHEN** nodes 23, 32 and 49 have been heard and their identity read
- **THEN** each row's Device column shows the device's 0x1008 name, with vendor and product numbers in muted text

#### Scenario: Device without a name object
- **WHEN** node 32 aborts the read of 0x1008 and its 0x1000 reads 0x00020191
- **THEN** its Device column shows "CiA 401 I/O device" followed by its vendor and product numbers

### Requirement: Device column while the identity is unknown
While a node's identity is being read, its Device cell SHALL say "Reading…"; while the node is STOPPED and not read yet, that it waits for the node to leave Stopped; when the node does not answer SDO, "No SDO answer" with **Read again**.

#### Scenario: Stopped node waits
- **WHEN** node 49 is heard in STOPPED and its identity is not read yet
- **THEN** its Device column says it is waiting for the node to leave Stopped

#### Scenario: No answer
- **WHEN** node 49's identity reads time out
- **THEN** its Device column says No SDO answer and offers Read again

### Requirement: Device name outside the Nodes table
With a config, the Nodes table's Name column SHALL keep the configured name and show the device's own name under it in muted text. A node without a configured name SHALL use the device's name in its heading and its tree entry in Commission a device, and **Add to a config…** SHALL suggest it as the node name.

#### Scenario: Heading of a heard node
- **WHEN** the user opens heard node 23 in Commission a device after its identity was read
- **THEN** the heading reads "Node 23" followed by the device's name, and Add to a config… suggests that name

### Requirement: Standard object dictionary without an EDS
A node with no configured, matched or picked EDS SHALL have a standard object dictionary: the CiA 301 communication objects, plus the CiA 401 or CiA 402 standard objects when its 0x1000 low 16 bits are 401 or 402. Its Object dictionary tab and SDO object picker SHALL use it as they use an EDS (tree, reading, watch, formats, notes, editing). Standard entries SHALL have no default value.

#### Scenario: Object dictionary without an EDS
- **WHEN** the user opens the Object dictionary tab of heard node 49, which has no EDS and whose 0x1000 reads 0x00000000
- **THEN** the tab shows the CiA 301 objects in the communication group

#### Scenario: Profile objects
- **WHEN** node 32's 0x1000 low 16 bits read 402 and it has no EDS
- **THEN** its Object dictionary tab also shows the CiA 402 objects such as 0x6040 Controlword and 0x6041 Statusword in the profile group, with the controlword and statusword bit views

#### Scenario: Pick an object without an EDS
- **WHEN** node 49 has no EDS and the user types `heartbeat` in the SDO panel's filter
- **THEN** the picker offers 0x1016 Consumer heartbeat time and 0x1017 Producer heartbeat time, and picking 0x1017 fills index 0x1017, sub-index 0 and type UNSIGNED16

### Requirement: Standard dictionary says what it is
The standard dictionary's tab SHALL say at the top that these are standard objects and the device may lack some, name the device profile and, for a profile other than 301, 401 and 402, say its profile objects are not built in. It SHALL offer the node's EDS matches and **Pick EDS file…**; picking an EDS SHALL replace the standard dictionary.

#### Scenario: Other profile
- **WHEN** node 49's 0x1000 low 16 bits read 406 and it has no EDS
- **THEN** the tab shows the CiA 301 objects and says the CiA 406 objects are not built in

#### Scenario: EDS picked later
- **WHEN** the user picks the device's EDS from the line at the top of node 49's standard dictionary
- **THEN** the tab shows the EDS's objects, including its manufacturer objects

### Requirement: Objects a device lacks in the standard dictionary
A read of a standard entry refused with abort 0x06020000 or 0x06090011 SHALL mark it "not on this device". An array object SHALL show sub-entries up to the value read from its sub-index 0, and sub-indices 0 and 1 before that.

#### Scenario: Missing object
- **WHEN** the user reads 0x1013 of node 49 and the device aborts with 0x06020000
- **THEN** the entry is marked not on this device

#### Scenario: Error history length
- **WHEN** node 49's 0x1003 sub-index 0 reads 3
- **THEN** 0x1003 shows sub-indices 0 to 3

### Requirement: Read all on the standard dictionary
The standard dictionary SHALL list RPDO and TPDO 1-4. **Read all** SHALL read each object's sub-index 0 before its other entries, skip the rest of an object that does not exist, and add RPDOs and TPDOs from 5 onwards until the first that does not exist.

#### Scenario: Read all hides what is missing
- **WHEN** the user presses Read all on node 49's standard dictionary and the device has no 0x1013 and two TPDOs
- **THEN** 0x1013 and TPDO 3 and 4 are hidden by **Hide objects the device lacks**, and turning the filter off shows them marked "not on this device"

#### Scenario: More PDOs
- **WHEN** node 49 has 8 RPDOs
- **THEN** after Read all its standard dictionary shows RPDO 1-8

### Requirement: Parameters of a node without an EDS
The Parameters tab of a node without an EDS SHALL say that back up, compare and restore need the device's EDS and offer the node's EDS matches and **Pick EDS file…**.

#### Scenario: Parameters without an EDS
- **WHEN** the user opens the Parameters tab of node 49, which has no EDS
- **THEN** the tab says back up, compare and restore need the device's EDS and offers Pick EDS file…

## MODIFIED Requirements

### Requirement: Object dictionary view
In the online view every node SHALL have an object dictionary tab: from its EDS for each configured node and each node with a matched or picked EDS, else from the standard object dictionary (see "Standard object dictionary without an EDS"). The tab SHALL show a tree of every object, grouped as communication (0x1000-0x1FFF), manufacturer (0x2000-0x5FFF) and profile (0x6000-0x9FFF), with index, subindex, name, data type, access, EDS default and device value. Each object SHALL be one row: a VAR object with its value in that row, an ARRAY or RECORD object as a foldable row with its sub-entries below it, each sub-entry named by its own name without the object's name in front. Groups and objects SHALL start folded, except that a search or filter unfolds the groups and objects that hold a match. The tab SHALL use the full width of the online view, and long names SHALL wrap so that the row's buttons and watch box always stay inside the view without sideways scrolling. A search box SHALL filter by name or index.

#### Scenario: Browse node 3
- **WHEN** the user opens the object dictionary tab of node 3
- **THEN** the tree shows the objects from node 3's EDS in three folded groups, values empty until read

#### Scenario: Node without an EDS
- **WHEN** the user opens the object dictionary tab of a heard node that has no EDS
- **THEN** the tree shows the standard objects instead of saying the node has no EDS

#### Scenario: Object with sub-entries
- **WHEN** the user unfolds object 0x6110 "AI Sensor Type" of node 3
- **THEN** one row for the object and one row per sub-entry are shown, the sub-entries named "Number Of Entries", "AI0_Sensor_Type" and so on

#### Scenario: Long names
- **WHEN** a node's EDS has names such as `Store_Parameters_Field_Highest_subindex_supported` and the window is 1280 px wide
- **THEN** the names wrap and every row's Read and Edit buttons and Watch box are fully visible

#### Scenario: Search by index
- **WHEN** the user types `6110` in the search box
- **THEN** only object 0x6110 and its subindices are shown, unfolded

### Requirement: Manual SDO and NMT in the online view
For each node the online view SHALL offer an SDO panel: pick an object from the node's EDS, or from the standard object dictionary when the node has no EDS (all objects, not only mappable ones), or type index and subindex, read it, and show the value decoded with the object's data type (numbers in decimal and hex, VISIBLE_STRING as text, other types as hex bytes), or the abort code with its CiA 301 text. When the runtime allows changes, the panel SHALL also write a value encoded from the object's type after a range check, warning before writing an object the plugin configures itself or one owned by an SDO variable; and the node SHALL have NMT buttons (start, stop, pre-operational, reset node, reset communication), with confirmation for stop, pre-operational and the resets, since each of those holds or interrupts the node. When the runtime does not allow changes, write and NMT controls SHALL be shown disabled with the reason.

#### Scenario: Read the serial number
- **WHEN** the user reads 0x1018 subindex 4 of node 3
- **THEN** the panel shows the serial number in decimal and hex

#### Scenario: Picker without an EDS
- **WHEN** node 49 has no EDS and the user opens the object picker
- **THEN** it lists the standard objects, and does not say "No EDS objects"

#### Scenario: Write blocked
- **WHEN** the runtime's `allow_changes` is false
- **THEN** the write button and NMT buttons are disabled and say that online changes are not allowed in this configuration

#### Scenario: Pre-operational asks first
- **WHEN** the user clicks Pre-operational for node 2
- **THEN** a dialog says the node's PDOs stop until it is started again, with Cancel as the default, and nothing is sent until the user confirms

### Requirement: Filters in the object dictionary view
Next to the search box the object dictionary tab SHALL offer filters that can be combined with the search: changed from the EDS default, writable, set by the configuration or an SDO variable, mapped in a PDO, not readable (an entry whose last read failed), and different in the last compare. For the standard object dictionary it SHALL also offer **Hide objects the device lacks**, on by default, which hides entries marked "not on this device" and objects whose entries are all marked so. A filter that needs values SHALL apply to the entries read so far.

#### Scenario: Only changed values
- **WHEN** the user has read all of node 3 and picks "changed from default"
- **THEN** only the entries whose value differs from the EDS default are shown, with their objects and groups unfolded

#### Scenario: Filter and search together
- **WHEN** the user picks "writable" and types `sensor`
- **THEN** only writable entries whose name or index contains "sensor" are shown

#### Scenario: Show what the device lacks
- **WHEN** node 49's standard dictionary has been read and the user turns off Hide objects the device lacks
- **THEN** the entries the device refused are shown again, marked "not on this device"

### Requirement: Node Status tab
A node's **Status** tab SHALL show, in this order:
- the device: name, vendor, product, revision, serial number, hardware and software version and device profile, as read by "Device identity of heard nodes", with **Read again**;
- NMT state, time since last heard and heartbeat state;
- boot result with its error text, and retry or hold state (with a config);
- the NMT buttons with their confirmations;
- for each monitored TPDO, its timeout, count and time since its last PDO (with a config);
- the EMCY history with times and CiA 301 error classes;
- the error history (0x1003).

Opening the tab SHALL clear the node's new-entry flag on the tree.

#### Scenario: Stopped node
- **WHEN** node 7 is STOPPED and the user opens its Status tab
- **THEN** the tab shows Stopped as text and shape, its last heartbeat age, and Start enabled when changes are allowed

#### Scenario: Device line
- **WHEN** the user opens the Status tab of heard node 23 after its identity was read
- **THEN** the first line shows its device name, vendor, product, revision, serial number and versions; values the device did not answer are left out
