## ADDED Requirements

### Requirement: Linked PDOs in the DBC
A link SHALL NOT add a message: its frame is the producer TPDO's message. That message SHALL list each consumer node as a receiver, next to `Master`, and each signal SHALL list as receivers the consumers whose layout maps a real object (not a dummy entry) at that signal's position. The message comment SHALL name the link and, per consumer, the RPDO number and the objects it writes. A signal of a producer entry without `iec_location` SHALL still be exported, with a comment that the PLC does not use it.

#### Scenario: Two consumers
- **WHEN** node 10's TPDO 1 links to node 20 RPDO 2 and node 21 RPDO 1
- **THEN** message `stick_TPDO1` at 0x18A has receivers `Master`, `valves` and the name of node 21, and its comment names the link and both RPDOs

#### Scenario: Dummy position
- **WHEN** node 20 maps a dummy entry at the producer's second position
- **THEN** the second signal does not list node 20 as a receiver
