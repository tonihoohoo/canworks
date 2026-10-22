## MODIFIED Requirements

### Requirement: Live control
A running simulator SHALL offer, over its control protocol: the list of simulated devices with their NMT state, power state and injected faults; reading any object's current value without bus traffic; setting a value once; overriding a value (a held value that wins over value sources and models until released); giving, changing and removing value sources; injecting and clearing faults; and starting, stopping and listing scenarios with their state. Every change SHALL be logged with its origin.

A request and a scenario step SHALL address a device by its configured node ID, its name, or the node ID it has now (one an LSS master gave it), in the plugin and in the standalone simulator alike. When a number is both one device's configured node ID and another device's current node ID, it SHALL address the configured device.

#### Scenario: Override a sensor value
- **WHEN** a user overrides 0x7130:1 of node 5 with 1500 while a sine drives it
- **THEN** the object reads 1500 until the override is released, then follows the sine again

#### Scenario: Read without bus traffic
- **WHEN** a client reads 0x6000:1 of a simulated node through the control protocol
- **THEN** the value is returned and no CAN frame is sent

#### Scenario: Device addressed by the node ID LSS gave it
- **WHEN** a standalone device started without a node ID and named "lss0" gets node ID 70 by LSS, and a user runs `canworks-canopen-sim fault 70 heartbeat-stop`
- **THEN** the fault applies to that device, and `fault lss0 ...` still addresses it
