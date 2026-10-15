## ADDED Requirements

### Requirement: Cyclic job ends on an input error
When a running `CAN_SEND_CYCLIC` job gets a `PERIOD` outside 1 ms to 60 s or a `DLC` above 8, the plugin SHALL end the job before the block reports `ERROR_ID` 3, so the frame stops on the bus. A block SHALL stop its job in the plugin whenever it lets go of a job handle.

#### Scenario: Period set to zero while running
- **WHEN** a job sends 0x123 every 10 ms and the program sets `PERIOD := T#0s`
- **THEN** the block reports `ERROR_ID` 3, `ACTIVE` is FALSE, and 0x123 stops on the bus

#### Scenario: Re-enable after the error
- **WHEN** after that error the program sets a valid `PERIOD` and gives `ENABLE` a new rising edge
- **THEN** exactly one job sends 0x123
