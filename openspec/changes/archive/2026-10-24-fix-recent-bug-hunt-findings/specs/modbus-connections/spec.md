## ADDED Requirements

### Requirement: Any second writer next to a PLC link
With `plc_link` true, every connection other than the one with the PLC link that has `writes` true SHALL get the Problems warning naming it, whatever its kind. The Add connection dialog SHALL leave Writes off for a new connection while a PLC link exists.

#### Scenario: truST next to OpenPLC
- **WHEN** a config has an OpenPLC connection and the user adds a truST connection
- **THEN** the new row has Writes off, and ticking it gives the warning naming the truST connection

### Requirement: No download with errors on the connection
A connection's Download SHALL be refused while the check has an error on that connection's address or on the bridge's listen address for it, with "The saved config has N errors: fix them first". A README of a connection whose client is not on the bridge's machine SHALL name the bridge's listen address, never 127.0.0.1.

#### Scenario: Bridge on loopback, PLC elsewhere
- **WHEN** the bridge listens on 127.0.0.1 and the user presses Download on an Other PLC connection at 192.168.1.51
- **THEN** nothing is downloaded, the row does not turn In sync, and the message names the listen error

### Requirement: Address required
The Add connection dialog SHALL refuse Add with an empty address with "Give the client's address" under the field, and SHALL prefill 127.0.0.1 for Node-RED and HMI.

#### Scenario: HMI without an address
- **WHEN** the user picks HMI, clears the address and presses Add
- **THEN** no connection is added and the field shows the message

### Requirement: Mailbox warning counts the connections
The warning that nothing uses the mailboxes, and its Turn off fix, SHALL appear only when neither the OpenPLC program nor any connection's canworks blocks choice needs them.

#### Scenario: truST blocks next to OpenPLC
- **WHEN** a config has an OpenPLC connection whose program declares no mailbox block and a truST connection with canworks blocks SDO and send
- **THEN** Problems has no Turn off the mailboxes warning

### Requirement: OpenPLC add text
The Add connection dialog and the banner after adding OpenPLC SHALL list what adding it turns on (PLC link, low word first, live lists, packing) and SHALL say that the mailboxes stay off until the program declares a mailbox block.

#### Scenario: Add OpenPLC
- **WHEN** the user adds an OpenPLC connection
- **THEN** the banner does not say the mailboxes are on
