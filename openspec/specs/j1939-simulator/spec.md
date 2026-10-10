# j1939-simulator Specification

## Purpose
How canworks-j1939-sim simulates J1939 ECUs from a DBC file on a PC adapter, for testing a PLC without real devices.

## Requirements

### Requirement: J1939 ECU simulator command
The PC tools SHALL install `canworks-j1939-sim`, which runs one simulated J1939 ECU on a SocketCAN interface or a USB CAN adapter. It claims an address with a NAME, sends every DBC message whose sender is the chosen node at its cycle time with values that ramp within each signal's range (or from a scenario file), and answers requests for those PGNs. A multiplexed message SHALL be sent as every one of its pages at each cycle, or one page per cycle in turn with `--mux rotate`.

#### Scenario: Simulate an ECU on vcan
- **WHEN** a user runs `canworks-j1939-sim --dbc machine.dbc --node Engine --interface vcan0 --address 0`
- **THEN** vcan0 carries an Address Claimed from 0 and then the Engine's messages at their cycle times

#### Scenario: Through a USB adapter
- **WHEN** the same command runs with `--adapter slcan:/dev/tty.usbmodem1 --bitrate 250000` on macOS
- **THEN** the adapter sends the claim and the messages on the bus

#### Scenario: Multiplexed message
- **WHEN** the Engine sends PGN 65284 every 100 ms with pages 1 and 2
- **THEN** vcan0 carries a page 1 and a page 2 frame of 65284 every 100 ms

### Requirement: Simulator receives
The simulator SHALL print, or log to a file, every message it receives that the DBC defines, with decoded signals, so a test can check what the PLC sent.

#### Scenario: PLC setpoint seen
- **WHEN** the PLC sends PGN 65281 with `Setpoint` 500
- **THEN** the simulator prints PGN 65281 from the PLC's address with `Setpoint=500`

### Requirement: Address contention mode
With `--contend ADDRESS --name-value N`, the simulator SHALL claim the given address with the given NAME, so claim loss and defence can be tested.

#### Scenario: Force the PLC to move
- **WHEN** the simulator contends for 128 with a NAME lower than the PLC's, and the PLC's range is [128, 135]
- **THEN** the PLC moves to another address in its range, and the simulator keeps 128
