## ADDED Requirements

### Requirement: Result of a PDO layout read
A PDO layout read in Commission a device SHALL keep, for each PDO with a valid COB-ID, whether it now decodes, and if not, the first object not read and why (abort code and text, or no answer). A mapping read with no answer SHALL be tried once more. The message after **Read PDOs from device** SHALL name as read only the PDOs that now decode and each other PDO with its reason, and SHALL be an error when no PDO decodes.

#### Scenario: Mapping not readable
- **WHEN** the user presses Read PDOs from device for node 49, whose TPDO1-3 communication objects answer and whose mapping objects get no answer, even when tried again
- **THEN** the error message says that no PDO of node 49 decodes and names 0x1A00:0 not read (no answer)

#### Scenario: One PDO not usable
- **WHEN** node 49's TPDO1 and TPDO2 read completely and reading 0x1A02:1 is aborted with 0x06020000
- **THEN** the message reads "Node 49: TPDO1, TPDO2 read from the device." and names TPDO3 with "TPDO3 not usable: 0x1A02:1 not read (abort 0x06020000, object does not exist in the object dictionary)", and TPDO1 and TPDO2 frames decode

### Requirement: PDO layout read result in the Decoding panel
The Decoding panel's PDO layout column SHALL show the node's last read: the PDOs read from the device with the time, and each PDO that does not decode with its reason; "not read" with the reason when no PDO is usable. "unknown" SHALL be shown only for a node never read and with no other layout source. A node with an EDS SHALL keep decoding with its EDS defaults the PDOs whose mapping the device did not give.

#### Scenario: Nothing usable
- **WHEN** a read of node 49 gave no usable PDO because 0x1A00:0 got no answer
- **THEN** node 49's PDO layout column reads "not read" with that reason instead of "unknown"

#### Scenario: Automatic read
- **WHEN** an automatic read of node 32 gives TPDO1 but TPDO2's mapping is aborted
- **THEN** no message is shown, and node 32's row shows TPDO1 read from the device and TPDO2 with its reason on its own line
