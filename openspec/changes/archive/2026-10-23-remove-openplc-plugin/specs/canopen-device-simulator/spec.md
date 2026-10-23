## RENAMED Requirements

- FROM: `### Requirement: Simulation file checked like the plugin checks it`
- TO: `### Requirement: Simulation file checked like the bridge checks it`

## MODIFIED Requirements

### Requirement: Default behaviour by device profile
Without any behaviour configured for it, a simulated device SHALL choose its behaviour from the device profile in the low 16 bits of 0x1000:
- CiA 401: each digital output object (0x6200, 0x6220, 0x6250) SHALL be copied to the digital input object at the same subindex (0x6000, 0x6020, 0x6050), and each analogue output (0x6411) to the analogue input (0x6401), when both exist;
- CiA 404: each process value object the EDS maps by default into a TPDO SHALL move slowly (a sine of 60 seconds period) between 25 % and 75 % of its EDS limits, or of its data type's range when the EDS gives none;
- any other profile, CiA 402 included: objects keep their values, so only the master, value sources, expressions and the user change them.
A device's default behaviour SHALL be switchable off.

#### Scenario: I/O module loopback
- **WHEN** a simulated CiA 401 module with 0x6200:1 and 0x6000:1 gets 0x6200:1 = 0x05 from the master's RPDO
- **THEN** its next TPDO carrying 0x6000:1 carries 0x05

#### Scenario: Profile without a default
- **WHEN** a device with profile 0 is simulated with no behaviour configured
- **THEN** none of its objects change except by SDO, RPDO or the user

#### Scenario: Default switched off
- **WHEN** a CiA 401 device is simulated with its default behaviour switched off
- **THEN** 0x6000:1 keeps its file value when 0x6200:1 changes

#### Scenario: Drive EDS
- **WHEN** a device whose 0x1000 says profile 402 is simulated and the master writes 0x6040 = 0x000F
- **THEN** 0x6041 keeps its file value, as for any profile without a default

### Requirement: Scenarios
A scenario SHALL be a named list of steps run in order, each with an optional start time or delay: set or override a value, give or remove a value source, inject or clear a device fault, wait until a condition on any simulated object holds (with a timeout), expect a condition (now, within a time, or for a whole duration), log a message, and repeat a block. A scenario SHALL be startable and stoppable while the simulator runs and SHALL report its current step. Scenarios marked `autostart` SHALL start when the simulation starts. Several scenarios MAY run at the same time. An expect that fails, or a wait that times out, SHALL fail the scenario with the step, the condition and the value seen; the simulation SHALL go on.

#### Scenario: Test a PLC alarm
- **WHEN** a scenario sets 0x7130:1 of node 5 to 900, then expects 0x6200:1 bit 2 of node 7 to become 1 within 500 ms
- **THEN** the scenario passes when the PLC program switches on the alarm output in time, and fails with the value seen otherwise

#### Scenario: Machine fault step
- **WHEN** a scenario has a machine fault step or a `drive_input` fault step
- **THEN** the step is refused as unknown, naming the step and the scenario

### Requirement: Device built from its EDS or DCF
A simulated device SHALL be built from one EDS or DCF file and a node ID. Its object dictionary, data types, access types, default values, PDO communication and mapping parameters, heartbeat or node guarding, SDO server, EMCY producer and identity (0x1018) SHALL be the ones the file describes. With a DCF, each `ParameterValue` SHALL be the object's starting value, so a parameter backup made with `canworks-diag backup` starts a device with the backed-up values. A file that fails the CiA 306 lint the bridge uses SHALL be refused with the lint's messages.

#### Scenario: Device from an EDS
- **WHEN** a device is simulated from `config/rtd-sensor/rtd8.eds` as node 5
- **THEN** it sends its boot-up message as node 5, answers SDO reads of 0x1018 with the EDS identity and its other objects with their EDS default values

#### Scenario: Device from a backup
- **WHEN** a device is simulated from a backup DCF in which 0x2100:3 has `ParameterValue=7` and the EDS default is 0
- **THEN** an SDO read of 0x2100:3 answers 7

#### Scenario: Broken EDS
- **WHEN** a device is simulated from an EDS whose object 0x1A00 lists 3 mapping entries but defines only 2
- **THEN** the simulator refuses to start that device and prints the lint message for 0x1A00

### Requirement: Standard CANopen device behaviour
A simulated device SHALL follow CiA 301 as a NMT slave: boot-up after power on and after reset, the NMT states and commands, SDO expedited, segmented and block transfers, PDOs according to their transmission types (synchronous, SYNC counter start, event-driven with inhibit time and event timer), RPDO deadline monitoring, heartbeat production and consumption or node guarding, and EMCY. Writes SHALL be checked against the object's access type, data type and the EDS `LowLimit`/`HighLimit`, with the CiA 301 abort codes.

#### Scenario: Master configures the device
- **WHEN** the bridge boots a simulated node and writes its PDO mapping, heartbeat time and startup SDOs
- **THEN** the device accepts them as a real device with that EDS would and reaches OPERATIONAL

#### Scenario: Value above the EDS limit
- **WHEN** a master writes 300 to an object whose EDS `HighLimit` is 255
- **THEN** the device aborts the write with 0x06090031

### Requirement: Stored parameters and configuration date
A simulated device whose EDS has 0x1010 SHALL keep the values saved with "save" across a simulated power cycle or reset, and one with 0x1011 SHALL go back to the file's values after "load". Stored values SHALL live in memory for the life of the simulator, or in a state directory when one is given, so they also survive a restart of the simulator. A device whose EDS has 0x1020 SHALL keep the configuration date and time the master writes like any other stored value.

#### Scenario: Store then power cycle
- **WHEN** a master writes 5 to 0x2000:1, writes "save" to 0x1010:1, and the device is powered off and on
- **THEN** 0x2000:1 reads 5

#### Scenario: Not stored
- **WHEN** a master writes 5 to 0x2000:1 without "save" and the device is powered off and on
- **THEN** 0x2000:1 reads its file value again

#### Scenario: Configuration check skips the download
- **WHEN** the bridge with `config_check` downloads a node's configuration, the node stores it, and the simulated device is power cycled
- **THEN** the master finds the same 0x1020 date and time and skips the download

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

An EMCY with code 0x0000 SHALL send one error reset EMCY (code 0000, the given error register, default 0, and the given manufacturer bytes) and clear the device's error history (0x1003) and a periodic EMCY, whether or not an EMCY was sent before. An EMCY with code 0x0000 and a period SHALL be refused. A simulated device SHALL answer LSS only when its EDS says `LSS_Supported=1`. For a device whose EDS does not say so (0 or left out), the simulator SHALL refuse everything that would leave it without a node ID: forgetting the node ID (from the control protocol, the command line, a scenario step or the file's start-up faults), and starting it without a node ID (a standalone `--node 0`, an extra device with node 0; a simulated node with an `lss` object is already refused by the configuration check). The refusal SHALL say "node N: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back" (for an extra device without a node ID, it names the device by its name). It SHALL go to the caller and into the log, and the device SHALL keep its node ID and state. The PC tools' simulation check SHALL refuse the same. A device without a node ID SHALL show in the status as without a node ID and waiting for LSS.

#### Scenario: Node lost and back
- **WHEN** a user powers off simulated node 5 while the bridge runs, then powers it on 10 s later
- **THEN** the bridge reports node 5 lost by its heartbeat, then boots and configures it again after its boot-up

#### Scenario: SDO abort rule
- **WHEN** a rule makes 0x2000:1 abort writes with 0x08000020 for the next transfer, and a master writes it twice
- **THEN** the first write aborts with 0x08000020 and the second succeeds

#### Scenario: Wrong product
- **WHEN** a simulated node 23's 0x1018:2 is overridden with another product code and it is power cycled
- **THEN** the bridge's identity check fails the node's boot with the identity error

#### Scenario: Forgotten node ID found by LSS
- **WHEN** a bridge-simulated node 40, built from an EDS with `LSS_Supported=1`, is given `forget_node_id` and a diagnostics client starts an LSS search
- **THEN** the search finds the device's identity with no node ID, a following LSS configure node ID 70 makes it answer SDO as node 70, and a power cycle makes it node 40 again

#### Scenario: Forget refused without LSS
- **WHEN** a user runs `canworks-diag sim fault 40 forget-node-id` for a simulated node 40 whose EDS says `LSS_Supported=0`
- **THEN** the command fails with "node 40: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back", the bridge log has the same, and node 40 keeps its node ID and NMT state

#### Scenario: Start without a node ID refused without LSS
- **WHEN** the standalone simulator is started with `--eds cpp-slave.eds --node 0 --name new` and that EDS says `LSS_Supported=0`
- **THEN** it exits with an error naming "new" and saying that its EDS has no LSS, so it could never get a node ID

#### Scenario: Error reset EMCY
- **WHEN** a user injects `emcy` with code 0x0000 into a simulated node 5 that has sent no EMCY
- **THEN** node 5 sends one EMCY with code 0000 and error register 0, and 0x1003:0 reads 0

#### Scenario: Periodic error reset refused
- **WHEN** a user injects `emcy` with code 0x0000 and a period of 100 ms
- **THEN** the request is refused with a message saying that code 0x0000 is the error reset and takes no period, and nothing is sent

### Requirement: Live control
A running simulator SHALL offer, over its control protocol: the list of simulated devices with their NMT state, power state and injected faults; reading any object's current value without bus traffic; setting a value once; overriding a value (a held value that wins over value sources and models until released); giving, changing and removing value sources; injecting and clearing faults; and starting, stopping and listing scenarios with their state. Every change SHALL be logged with its origin.

A request and a scenario step SHALL address a device by its configured node ID, its name, or the node ID it has now (one an LSS master gave it), in the bridge and in the standalone simulator alike. When a number is both one device's configured node ID and another device's current node ID, it SHALL address the configured device.

#### Scenario: Override a sensor value
- **WHEN** a user overrides 0x7130:1 of node 5 with 1500 while a sine drives it
- **THEN** the object reads 1500 until the override is released, then follows the sine again

#### Scenario: Read without bus traffic
- **WHEN** a client reads 0x6000:1 of a simulated node through the control protocol
- **THEN** the value is returned and no CAN frame is sent

#### Scenario: Device addressed by the node ID LSS gave it
- **WHEN** a standalone device started without a node ID and named "lss0" gets node ID 70 by LSS, and a user runs `canworks-canopen-sim fault 70 heartbeat-stop`
- **THEN** the fault applies to that device, and `fault lss0 ...` still addresses it

### Requirement: Simulation file checked like the bridge checks it
The PC tools' check of the simulation file (the configurator's Simulation view, its save, and the deploy tool) SHALL refuse everything the bridge refuses when it loads the file, with a message naming the network, node and object: a value source on an object the master writes (an entry of a configured RPDO mapping), an override or `set` value that does not fit the object's data type, and a scenario step or fault on a node that is not simulated on that network. The bridge's control protocol SHALL refuse an override that does not fit the object's data type instead of storing it. An override on an object the master writes SHALL be a warning, since the bridge accepts it and the device then ignores the master's writes to it.

#### Scenario: Source on an RPDO entry
- **WHEN** the user adds a value source on node 6's 0x6200:1, which node 6's RPDO 1 maps, and saves
- **THEN** Problems lists "node 6: 0x6200:1 is written by the master (RPDO 1); a value source cannot drive it" and Save is disabled

#### Scenario: Override that does not fit
- **WHEN** an override of "abc" is sent for an INTEGER16 object, from the page or over the control protocol
- **THEN** it is refused with a message naming the data type, and the object keeps its value

### Requirement: Power cycle keeps the network running
Powering a simulated device off and on again, by the user, a fault or a scenario, SHALL leave the network's bus running: the master SHALL see the device boot again, the diagnostics channel SHALL keep answering, and stopping the PLC SHALL end the bus thread. A network whose simulation the bridge refuses at start SHALL run its master without simulated devices and SHALL NOT keep a thread busy.

#### Scenario: Power off and on
- **WHEN** simulated node 5 is powered off for 2 s and powered on again, five times in a row
- **THEN** node 5 is OPERATIONAL again after each cycle, the status request answers within 1 s throughout, and the bridge stops within 2 s when the PLC stops

### Requirement: Expression size limits
An expression SHALL be refused when it is longer than 4096 characters or nests deeper than 128 levels, with its position, wherever it comes from (simulation file, control protocol, `sim_check_expr`). Checking or evaluating an expression SHALL never crash the process that runs the simulator.

#### Scenario: Deep nesting
- **WHEN** a client checks an expression made of 10,000 `(` followed by `1` and 10,000 `)`
- **THEN** the check answers with an error naming the nesting limit and its position, and the bridge keeps running

### Requirement: Forced simulation switch values
When `CANWORKS_FORCE_SIMULATE` is set to a value other than `1` or empty, the bridge SHALL log a warning that the value is ignored and the configured interfaces are used.

#### Scenario: Wrong value
- **WHEN** `CANWORKS_FORCE_SIMULATE=true`
- **THEN** the log warns that only `1` forces simulation

### Requirement: Expressions mean the same everywhere
The PC check and the bridge SHALL accept the same expression spellings (subindex as `0x` hex or decimal, no leading-zero device numbers) and give the same values, including on the first tick.

#### Scenario: Leading-zero device
- **WHEN** an expression uses `[05/0x7130:1]`
- **THEN** the configurator and the bridge both refuse it

#### Scenario: Offline check
- **WHEN** the expression editor checks an expression with no runtime connected
- **THEN** errors are shown

## REMOVED Requirements

### Requirement: CiA 402 drive model
**Reason**: CiA 402 support is dropped entirely (Toni, 2026-10-22).
**Migration**: A drive's objects can be given value sources or expressions in the simulation file like any device's.

### Requirement: Drive reset on NMT reset node
**Reason**: The drive model is removed; NMT reset node resets every simulated device as "Standard CANopen device behaviour" says.
**Migration**: None.
