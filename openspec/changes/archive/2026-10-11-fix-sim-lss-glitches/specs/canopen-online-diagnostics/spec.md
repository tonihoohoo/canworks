## MODIFIED Requirements

### Requirement: LSS commissioning
An authenticated client SHALL be able to run LSS operations on the bus while CANopen runs. Every LSS operation SHALL be refused with "changes not allowed" and send nothing when `allow_changes` is false, and SHALL be refused with "LSS busy" while another LSS operation (from any client, or the master's own assignment) is in progress. Every operation carried out SHALL be logged with the peer address, the LSS address and the result. A device's LSS address is its vendor ID, product code, revision number and serial number. The operations are:
- **Find**: look for one device that has no node ID (0xFF) using LSS fastscan, optionally with a known vendor ID and product code to shorten the search. The result is that device's LSS address, or "none found". Finding runs in the background like the network scan: the client starts it and reads its progress and result; it SHALL finish within 20 seconds at 125 kbit/s or faster. The found device SHALL be left in the LSS waiting state.
- **Inquire**: given an LSS address, read that device's node ID (0xFF for none), or "not found".
- **Set node ID**: given an LSS address, a node ID from 1 to 127 and `store` (default false), set that node ID and, only when `store` is true, send LSS "store configuration"; then switch all devices to the LSS waiting state. It SHALL be refused, sending nothing, when the node ID is the master's own or that of a configured node that is currently booted. The result SHALL say whether the device had no node ID before (it then starts with the new ID right away) or had another ID (the new one becomes active after the device's next communication reset or power cycle).
- **Set bit rate**: given an LSS address, a bit rate from the CiA 301 table (10, 20, 50, 125, 250, 500, 800 or 1000 kbit/s) and `store` (default false), set that device's bit rate and, only when `store` is true, store it; then switch all devices to the LSS waiting state. The master SHALL NOT send LSS "activate bit timing parameters" and SHALL NOT change its own bit rate. The result SHALL say that the device uses the new bit rate after its next power cycle and that `adapter.bitrate` must be changed to match.
A device that refuses a request SHALL make the operation fail with the reason, and the master SHALL still switch all devices to the LSS waiting state. LSS operations SHALL NOT disturb PDO exchange or heartbeat supervision of the configured nodes.

An LSS operation tied to a configured node whose EDS does not say `LSS_Supported=1` SHALL be refused with that node's "node N (name): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS" message and send nothing. An operation is tied to a configured node when its LSS address has that node's vendor ID and product code (from its EDS) and that node's `serial_number`, or when Set node ID asks for that node's node ID. This SHALL hold for every client: the configurator's online view, `canworks-diag` and the CiA 309-3 gateway. Find, and operations on an address that matches no configured node this way, SHALL stay as they are.

#### Scenario: Find and assign a new device
- **WHEN** `allow_changes` is true, a device with node ID 0xFF is on the bus, and a client starts a find, then sets node ID 40 for the found address without `store`
- **THEN** the find returns the device's vendor ID, product code, revision and serial number, the set returns "had no node ID", the device boots as node 40, and no "store configuration" request is sent

#### Scenario: Store only when asked
- **WHEN** a client sets node ID 40 for a found address with `store` true
- **THEN** the master sends one LSS "store configuration" request after the node ID was set

#### Scenario: Read-only diagnostics
- **WHEN** `allow_changes` is false and a client asks to find a device
- **THEN** the request is refused with "changes not allowed" and no LSS frame is sent

#### Scenario: Node ID in use
- **WHEN** node 3 is configured and booted and a client asks to set node ID 3 for some LSS address
- **THEN** the request is refused, naming node 3 as in use, and no LSS frame is sent

#### Scenario: Set a bit rate
- **WHEN** a client sets 250 kbit/s for a device's LSS address with `store` true while the bus runs at 125 kbit/s
- **THEN** the device gets the bit rate and the store request, no "activate bit timing" request is sent, the bus keeps running at 125 kbit/s, and the result says the device switches after its next power cycle and `adapter.bitrate` must match

#### Scenario: No unconfigured device
- **WHEN** every device on the bus has a node ID and a client starts a find
- **THEN** the result is "none found"

#### Scenario: Set node ID for a node without LSS
- **WHEN** node 23 (io) is configured with an EDS that has `LSS_Supported=0`, and a client asks to set node ID 23 for some LSS address
- **THEN** the request is refused with "node 23 (io): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS" and no LSS frame is sent

#### Scenario: Find not tied to a node
- **WHEN** the same config is running and a client starts a find
- **THEN** the find runs as before
