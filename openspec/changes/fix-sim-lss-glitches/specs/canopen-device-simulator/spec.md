## MODIFIED Requirements

### Requirement: Fault injection
A user SHALL be able to inject into a simulated device, at once or from a scenario:
- an EMCY with a code, error register and manufacturer bytes, once or every N ms until cleared, and the EMCY error reset;
- heartbeat stop and resume, with the device otherwise still working;
- power off (the device sends nothing and answers nothing) and power on (boot-up, values back to the file or the stored values);
- a self-initiated reset or a change to STOPPED or PRE-OPERATIONAL;
- SDO rules per object: abort with a given code on read, write or both, for the next N transfers or until removed; answer delay; refuse writes while OPERATIONAL with 0x08000022;
- stop and resume a TPDO;
- override the identity in 0x1018 and the device type in 0x1000;
- forget the node ID, so the device waits for LSS like a device without DIP switches.

An EMCY with code 0x0000 SHALL send one error reset EMCY (code 0000, the given error register, default 0, and the given manufacturer bytes) and clear the device's error history (0x1003) and a periodic EMCY, whether or not an EMCY was sent before. An EMCY with code 0x0000 and a period SHALL be refused. A simulated device without a node ID, because it started without one or forgot it, SHALL answer LSS (Fastscan, switch selective, inquire, configure node ID and store) even when its EDS does not say `LSS_Supported=1`, and the log SHALL say so for such an EDS. A device that has a node ID SHALL answer LSS only as its EDS says. The device's status SHALL show it as without a node ID and waiting for LSS.

#### Scenario: Node lost and back
- **WHEN** a user powers off simulated node 5 while the plugin runs, then powers it on 10 s later
- **THEN** the plugin reports node 5 lost by its heartbeat, then boots and configures it again after its boot-up

#### Scenario: SDO abort rule
- **WHEN** a rule makes 0x2000:1 abort writes with 0x08000020 for the next transfer, and a master writes it twice
- **THEN** the first write aborts with 0x08000020 and the second succeeds

#### Scenario: Wrong product
- **WHEN** a simulated node 23's 0x1018:2 is overridden with another product code and it is power cycled
- **THEN** the plugin's identity check fails the node's boot with the identity error

#### Scenario: Forgotten node ID found by LSS
- **WHEN** a plugin-simulated node 40, built from an EDS with `LSS_Supported=0`, is given `forget_node_id` and a diagnostics client starts an LSS search
- **THEN** the search finds the device's identity with no node ID, a following LSS configure node ID 70 makes it answer SDO as node 70, and a power cycle makes it node 40 again

#### Scenario: Error reset EMCY
- **WHEN** a user injects `emcy` with code 0x0000 into a simulated node 5 that has sent no EMCY
- **THEN** node 5 sends one EMCY with code 0000 and error register 0, and 0x1003:0 reads 0

#### Scenario: Periodic error reset refused
- **WHEN** a user injects `emcy` with code 0x0000 and a period of 100 ms
- **THEN** the request is refused with a message saying that code 0x0000 is the error reset and takes no period, and nothing is sent

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
- **WHEN** a standalone device started without a node ID and named "lss0" gets node ID 70 by LSS, and a user runs `canworks-sim fault 70 heartbeat-stop`
- **THEN** the fault applies to that device, and `fault lss0 ...` still addresses it
