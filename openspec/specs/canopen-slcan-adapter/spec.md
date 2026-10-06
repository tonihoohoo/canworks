# canopen-slcan-adapter Specification

## Purpose
Drives a serial-line CAN adapter (CANable and other slcan firmware) directly from the plugin: it attaches the slcan line discipline, names the interface, sets the bitrate, removes the interface on PLC stop and recreates it after an unplug, so no `slcand` unit is needed.

## Requirements

### Requirement: slcan adapter configuration
The adapter type `slcan` SHALL describe a serial-line CAN adapter (CANable with slcan firmware, Lawicel CANUSB and compatibles) with `device` (required, absolute path of the serial device), `interface` (required, the network interface name to create), `bitrate` (required, the same CiA 301 rates as `socketcan`) and `serial_baudrate` (optional, positive integer). `configure_link` and `restart_ms` SHALL NOT be accepted with `slcan`. The plugin, the published JSON Schema and the deploy tool SHALL apply the same rules.

#### Scenario: CANable on the Pi
- **WHEN** the config has `"adapter": {"type": "slcan", "device": "/dev/serial/by-id/usb-Openlight_Labs_CANable2_b158aa7-if00", "interface": "can0", "bitrate": 500000}`
- **THEN** the config loads and validates against the schema

#### Scenario: Device missing from the config
- **WHEN** an `slcan` adapter has no `device`
- **THEN** the plugin and the deploy tool reject the config with an error naming `adapter.device`

#### Scenario: Option of the other type
- **WHEN** an `slcan` adapter has `configure_link: false`
- **THEN** the config is rejected with an error saying `configure_link` does not apply to `slcan`

### Requirement: Plugin creates the slcan interface
When the PLC starts with an `slcan` adapter, the plugin SHALL open `device`, set it to raw mode (and to `serial_baudrate` when given), attach the kernel's slcan driver to it, give the resulting interface the configured `interface` name, set the bit rate, set the transmit queue length to 1000, and bring it up, without any external program. It SHALL log the device, interface and bit rate. When the PLC stops, the plugin SHALL take the interface down and release the device, so the interface no longer exists.

#### Scenario: Start from nothing
- **WHEN** the PLC starts, the CANable is plugged in as the configured `device`, and no `can0` exists
- **THEN** `can0` exists, is up at 500 kbit/s with a transmit queue length of 1000, the log names the device, `can0` and 500000, and network bring-up starts

#### Scenario: PLC stop
- **WHEN** the PLC is stopped
- **THEN** `can0` no longer exists and the serial device is free for other programs

#### Scenario: Serial device missing
- **WHEN** the PLC starts and `device` does not exist
- **THEN** the plugin logs that the serial device is missing, naming it, the PLC keeps scanning, every node reports not operational, and the plugin retries in the background as for a missing interface

#### Scenario: Kernel cannot set the slcan bit rate
- **WHEN** the running kernel's slcan driver does not accept a bit rate over netlink
- **THEN** the plugin logs an error that this kernel needs `slcand` with adapter type `socketcan` and `configure_link: false`, releases the device, and retries in the background

### Requirement: Interface name already taken
When an interface with the configured name already exists and was not created by the plugin, the plugin SHALL NOT use, change or delete it. It SHALL log an error naming the interface and suggesting to stop the program that created it (such as an `slcand` service) or to use type `socketcan` with `configure_link: false`, and SHALL retry in the background.

#### Scenario: Old slcand service still running
- **WHEN** a systemd unit has already created `can0` with `slcand` and the config uses `slcan` with `interface: "can0"`
- **THEN** the plugin logs the error naming `can0`, leaves `can0` as it is, every node reports not operational, and once the unit is stopped the next retry creates `can0` itself

### Requirement: Recovery after unplugging the adapter
When the serial device goes away while the PLC runs, the plugin SHALL treat the bus as missing (nodes not operational, as for a missing interface) and SHALL recreate the interface by itself once the device is back, without a PLC restart.

#### Scenario: Unplug and replug the CANable
- **WHEN** the CANable is unplugged while nodes are operational and plugged back in a few seconds later
- **THEN** every node reports not operational while it is out, `can0` is recreated after it is back, and the nodes are booted and become operational again, with no manual step
