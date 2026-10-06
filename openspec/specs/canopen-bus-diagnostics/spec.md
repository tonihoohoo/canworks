# canopen-bus-diagnostics Specification

## Purpose
Reports the CAN controller's own health (bus state, error counters, bus-off count and recovery) to the PLC program, separate from per-node supervision.

## Requirements

### Requirement: Bus state logging
While the PLC runs, the plugin SHALL follow the CAN controller's error state and log every change: a warning when the bus enters error-warning, error-passive or bus-off, an error line for bus-off that says the link stays bus-off when `adapter.restart_ms` is not set, and an info line when the bus returns to error-active. When the state changes more than 5 times within one second, the plugin SHALL log at most one summary line per second giving the number of changes and the current state.

#### Scenario: Bus-off logged
- **WHEN** the controller of `can0` goes bus-off and `restart_ms` is not set
- **THEN** the log has an error line naming `can0`, bus-off, and that the link stays bus-off until it is restarted or `restart_ms` is set

#### Scenario: Recovery logged
- **WHEN** the controller returns from error-passive to error-active
- **THEN** the log has an info line naming the interface and error-active

#### Scenario: Flapping bus
- **WHEN** the state changes 40 times within one second
- **THEN** the log has at most one summary line for that second, naming the number of changes and the current state

### Requirement: Bus state byte
The `master` object MAY give a `bus_state_location` (an `%IB` input byte). When it is given, the plugin SHALL keep that byte at: 0 when there is no usable bus (interface missing, down, not permitted, or no CANopen session running), 1 error-active, 2 error-warning, 3 error-passive, 4 bus-off. A virtual (`vcan`) interface that is up SHALL read 1. The byte SHALL reflect a state change by the next scan after the plugin's next supervision tick (at most 100 ms after the change).

#### Scenario: Healthy bus
- **WHEN** `bus_state_location` is `%IB100` and the master runs on an up `can0` with no errors
- **THEN** `%IB100` reads 1

#### Scenario: Cable unplugged
- **WHEN** the CAN cable is pulled so that no node acknowledges the master's frames
- **THEN** `%IB100` reads 3 (error-passive), and every node's state byte later reads 0 by its own loss detection

#### Scenario: Bus-off
- **WHEN** the controller goes bus-off
- **THEN** `%IB100` reads 4 until the controller is restarted, then 1

#### Scenario: Interface gone
- **WHEN** the configured interface is taken down or removed while the PLC runs
- **THEN** `%IB100` reads 0, and reads 1 again once the plugin has reopened the interface

#### Scenario: Virtual bus
- **WHEN** the master runs on an up `vcan0`
- **THEN** `%IB100` reads 1

### Requirement: Error counter bytes
The `master` object MAY give a `tx_error_count_location` and a `rx_error_count_location` (each an `%IB` input byte). When given, the plugin SHALL keep them at the controller's transmit and receive error counters, clamped to 255, updated with the bus state byte. When the interface does not report counters (including `vcan`), they SHALL read 0, and the plugin SHALL log once that the driver gives no error counters (not for `vcan`). Between sessions they SHALL keep their last value.

#### Scenario: Counters follow the controller
- **WHEN** the controller reports transmit error counter 128 and receive error counter 3
- **THEN** the transmit byte reads 128 and the receive byte reads 3

#### Scenario: Driver without counters
- **WHEN** the driver of `can0` reports no error counters
- **THEN** both bytes read 0 and one log line names `can0` and says it gives no error counters

### Requirement: Bus-off count word
The `master` object MAY give a `bus_off_count_location` (an `%IW` input word). When given, the plugin SHALL keep it at the number of bus-off events on the interface since the PLC started, taken from the interface's statistics so that a bus-off shorter than one supervision tick is still counted. It SHALL wrap from 65535 to 0. It SHALL read 0 on `vcan`.

#### Scenario: Short bus-off counted
- **WHEN** the controller goes bus-off twice and `restart_ms` 10 recovers it each time before the next supervision tick
- **THEN** the word increases by 2 although the state byte may never have read 4

#### Scenario: Count starts at PLC start
- **WHEN** the interface has had 7 bus-off events before the PLC starts and none after
- **THEN** the word reads 0

### Requirement: Bus diagnostic fields in the configuration
The four fields SHALL be optional and independent. The plugin and the deploy tool SHALL reject a configuration in which `bus_state_location`, `tx_error_count_location` or `rx_error_count_location` is not an `%IB` location, `bus_off_count_location` is not an `%IW` location, or any of them overlaps another location of the configuration, naming the field.

#### Scenario: Wrong size
- **WHEN** `bus_state_location` is `%IW100`
- **THEN** the configuration is rejected with an error naming `master.bus_state_location` and the expected `%IB` type

#### Scenario: Overlap with a node field
- **WHEN** `bus_state_location` is `%IB20` and node 5 has `state_location` `%IB20`
- **THEN** the configuration is rejected with an error naming both fields

#### Scenario: Fields absent
- **WHEN** none of the four fields is given
- **THEN** the plugin reserves no locations for them and still logs bus state changes

### Requirement: Bus diagnostics with slcan
With an `slcan` adapter, the bus diagnostics inputs SHALL follow what the kernel reports for the interface, as for any SocketCAN interface. When the adapter reports no CAN error state, the bus state byte SHALL read 1 while the interface is up and 0 when it is missing or down, and the error counters SHALL read 0. When any bus diagnostics location is configured, the plugin SHALL log once per PLC start that the slcan adapter does not report the CAN error state, that the bus state shows only whether the link is up, and that candleLight (gs_usb) firmware used with type `socketcan` reports error state and counters.

#### Scenario: Bus state on a CANable with slcan firmware
- **WHEN** `bus_state_location` is configured, the adapter is `slcan`, and the CAN cable is unplugged from the bus while the adapter stays connected
- **THEN** the bus state byte keeps reading 1, the node state bytes drop to 0 as their heartbeats time out, and the log has the one-time slcan diagnostics line

#### Scenario: CANable with candleLight firmware
- **WHEN** a CANable runs candleLight firmware and the config uses `{"type": "socketcan", "interface": "can0", "bitrate": 500000}`
- **THEN** the plugin sets up the link as for any native SocketCAN interface and the bus state byte reads 3 (error-passive) after the CAN cable is unplugged
