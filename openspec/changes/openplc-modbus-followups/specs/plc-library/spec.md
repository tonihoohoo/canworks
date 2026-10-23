## MODIFIED Requirements

### Requirement: Blocks over the bridge
`CO_SDO_READ` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE, DATA : UDINT), `CO_SDO_WRITE` (EXECUTE, NETWORK, NODE, INDEX, SUBINDEX, DATA : UDINT, SIZE, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID, ABORT_CODE), `CO_NMT` (EXECUTE, NETWORK, NODE, COMMAND, TIMEOUT → BUSY, DONE, ERROR, ERROR_ID) and `CO_NODE_LIVE` (NETWORK, NODE → LIVE) SHALL be ST blocks with an in-out `LINK : ARRAY[0..88] OF WORD` (the generated `canworks.link`). They SHALL work through the bridge's SDO bridge registers, control block and live lists with its counter handshake, with the PLCopen EXECUTE/BUSY/DONE/ERROR behaviour of today's blocks. Instances SHALL share the one SDO slot and the one control block: a block whose request finds the slot owned by another instance SHALL stay BUSY until the slot is free, and requests SHALL be served in the order they started. A write's SIZE SHALL be 1-4; a read returns the object's value in DATA, zero-extended. ERROR_ID SHALL keep today's codes, add 20 (bridge not reachable: `canworks.ok` false at start or during the request), 21 (SDO writes not allowed: abort 0x08000020 from the bridge) and 22 (the config has no SDO registers or control block for the request). ERROR_ID 8 (cancelled) SHALL also be reported when the bridge restarted and did not run the request (control result 6 or abort 0x08000022); the program may start it again. The blocks SHALL use no runtime-specific interface, so they build for any IEC 61131-3 runtime that has the generated link variable.

#### Scenario: Read the vendor ID
- **WHEN** a program sets EXECUTE of `CO_SDO_READ` with NETWORK 0, NODE 5, INDEX 16#1018, SUBINDEX 1
- **THEN** BUSY is TRUE until the bridge answers, then DONE is TRUE with node 5's vendor ID in DATA

#### Scenario: Two blocks at once
- **WHEN** two `CO_SDO_READ` instances start in the same scan
- **THEN** the first finishes, then the second runs, and both end with DONE

#### Scenario: Bridge not running
- **WHEN** `CO_NMT` starts while `canworks.ok` is FALSE
- **THEN** it ends with ERROR TRUE and ERROR_ID 20 without writing the control block

#### Scenario: Bridge restarted
- **WHEN** `CO_NMT` waits for its answer and the bridge restarts, answering its counter with result 6
- **THEN** it ends with ERROR TRUE and ERROR_ID 8, and a new rising edge of EXECUTE runs the command
