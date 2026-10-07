## ADDED Requirements

### Requirement: Frame inspector panel
In the Trace view, selecting a frame SHALL open an inspector panel with the four layers of the `canopen-frame-explain` model: meaning, identifier bits split into function code and node ID, a data grid with one row per byte (most significant bit on the left, CANopen bit number on each bit, each bit coloured by its field), the field list with values and working, and the wire strip with framing, stuff bits marked, the bus level line and the timing figures. Pointing at or focusing a bit or field SHALL show its explanation in a box that stays in view and SHALL highlight the same bits in every layer (a data bit in the grid and on the wire, a field's bits in the grid). Every bit SHALL be reachable with the keyboard. The panel SHALL follow the selected frame when the user moves through the list with the arrow keys, and SHALL offer the frame's SDO conversation, SYNC cycle or boot story where one exists. It SHALL work on opened trace files without a runtime, offline, in light and dark themes and at phone width.

#### Scenario: Point at a data bit
- **WHEN** the user points at bit 2 of byte 0 of node 5's TPDO1 whose bit 2 is mapped to `%IX100.2`
- **THEN** the box names the input, its value, `%IX100.2`, the object and the wire bit number, and that bit is highlighted in the grid and on the wire strip

#### Scenario: Keyboard
- **WHEN** the user tabs into the data grid and moves with the arrow keys
- **THEN** each focused bit is explained in the box

### Requirement: Sequences in the Trace view
The Trace view SHALL have a Sequences tab listing SDO conversations and boot stories with filters by node and result, and a SYNC cycle timeline with stepping and a jump to the slowest cycle, as the `canopen-bus-trace` capability describes. Sequence diagrams and timelines SHALL be drawn without a third-party library, and every step SHALL open its frame in the inspector panel.

#### Scenario: From a conversation to the frame
- **WHEN** the user clicks the abort arrow of an SDO conversation
- **THEN** the inspector panel opens on that abort frame with its abort code explained

### Requirement: Frame lab view
The side bar SHALL have a Frame lab view that works without a runtime and without a trace. It SHALL accept a frame typed as identifier and data or pasted in candump syntax, offer example frames generated from the open configuration (saved or not) and the frame builder of the `canopen-frame-explain` capability, and show the result in the inspector panel at the network's bit rate, with a bit rate picker. It SHALL have an arbitration demo: two frames chosen by the user are shown sent at the same time bit by bit, with each sender's bit, the bus level and the bit where the sender of a recessive bit reads a dominant level and stops, and which frame wins. The Frame lab SHALL never send anything to the bus and SHALL say so.

#### Scenario: Paste a frame
- **WHEN** the user pastes `705#7F` in the Frame lab
- **THEN** it is explained as node 5's heartbeat in Pre-operational

#### Scenario: Arbitration
- **WHEN** the user picks node 5's TPDO1 (0x185) and node 3's TPDO1 (0x183) for the arbitration demo
- **THEN** the demo shows both identical up to identifier bit 2, node 3's frame driving it dominant there, node 5's sender stopping, and 0x183 winning

#### Scenario: Example frames follow the config
- **WHEN** the user adds node 7 without saving and opens the Frame lab
- **THEN** the example frames include node 7's boot-up, heartbeat, SDO read of 1018h:01 and its PDOs
