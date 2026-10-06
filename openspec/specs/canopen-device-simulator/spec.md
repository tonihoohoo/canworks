# canopen-device-simulator Specification

## Purpose
A simulated CANopen device built from an EDS or DCF that behaves on the bus as the file describes, with value sources, device models, fault injection, scenarios and live control, so configurations and PLC programs can be built and tested without real devices.

## Requirements

### Requirement: Device built from its EDS or DCF
A simulated device SHALL be built from one EDS or DCF file and a node ID. Its object dictionary, data types, access types, default values, PDO communication and mapping parameters, heartbeat or node guarding, SDO server, EMCY producer and identity (0x1018) SHALL be the ones the file describes. With a DCF, each `ParameterValue` SHALL be the object's starting value, so a parameter backup made with `openplc-canopen-diag backup` starts a device with the backed-up values. A file that fails the CiA 306 lint the plugin uses SHALL be refused with the lint's messages.

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
- **WHEN** the plugin boots a simulated node and writes its PDO mapping, heartbeat time and startup SDOs
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
- **WHEN** the plugin with `config_check` downloads a node's configuration, the node stores it, and the simulated device is power cycled
- **THEN** the master finds the same 0x1020 date and time and skips the download

### Requirement: Default behaviour by device profile
Without any behaviour configured for it, a simulated device SHALL choose its behaviour from the device profile in the low 16 bits of 0x1000:
- CiA 401: each digital output object (0x6200, 0x6220, 0x6250) SHALL be copied to the digital input object at the same subindex (0x6000, 0x6020, 0x6050), and each analogue output (0x6411) to the analogue input (0x6401), when both exist;
- CiA 404: each process value object the EDS maps by default into a TPDO SHALL move slowly (a sine of 60 seconds period) between 25 % and 75 % of its EDS limits, or of its data type's range when the EDS gives none;
- CiA 402: the drive model;
- any other profile: objects keep their values, so only the master and the user change them.
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

### Requirement: Value sources
A user SHALL be able to give any readable object of a simulated device a value source that writes it periodically (default every 10 ms, 1-60000 ms): constant, sine, triangle, square, sawtooth (each with minimum, maximum, period and phase), ramp (from, to, duration, then hold or repeat), step sequence (list of value and duration, repeating or not), random walk (minimum, maximum, largest step) and noise added to another source, counter (start, step, wrap), CSV time series (a file of time and value, with linear or step interpolation, played once or looping), and an expression. Values SHALL be converted to the object's data type, rounded for integer types and clamped to the type's range; a VISIBLE_STRING object SHALL take only a constant. A value source on an object the master writes (an RPDO entry or a written SDO) SHALL be refused with that reason.

#### Scenario: Sine on a temperature
- **WHEN** 0x7130:1 (INTEGER16) gets a sine from 200 to 260 with a period of 10 s
- **THEN** the value read every 10 ms stays within 200-260 and repeats every 10 s

#### Scenario: CSV playback
- **WHEN** 0x6401:1 gets a CSV series with rows `0,100` and `2,300`, linear interpolation, not looping
- **THEN** the value is 200 one second after the source started and stays 300 after two seconds

#### Scenario: Source on an RPDO object
- **WHEN** a value source is given to 0x6200:1, which the configured RPDO 1 writes
- **THEN** the source is refused, naming RPDO 1

### Requirement: Expressions
An expression value source SHALL be able to use numbers, `t` (seconds since the device was last powered on), `dt` (seconds since the previous evaluation), the value of any object of the same device or of another simulated device (`[0x6200:1]`, `[5/0x6200:1]`), arithmetic, comparisons, logical and bit operators, and the functions `abs`, `min`, `max`, `clamp`, `floor`, `ceil`, `round`, `sqrt`, `exp`, `log`, `sin`, `cos`, `if`, `bit`, `setbit`, `noise`, `lag` (first-order lag with a time constant), `delay` (dead time), `rate_limit`, `integrate`, `hold` (sample and hold on a rising condition) and `edge`. An expression SHALL be checked when it is loaded: an unknown name, object or function, or a reference cycle without `lag`, `delay` or `integrate` in it, SHALL be refused with its position in the text. Evaluating SHALL never stop the device: a division by zero or a non-finite result SHALL keep the object's previous value and be reported once.

#### Scenario: Heater and temperature
- **WHEN** 0x6401:1 has the expression `20 + lag(if(bit([0x6200:1], 0), 80, 0), 30)`
- **THEN** after the master sets bit 0 of 0x6200:1, 0x6401:1 rises from 20 towards 100 with a 30 s time constant, and falls back towards 20 once the bit is cleared

#### Scenario: Unknown object
- **WHEN** an expression refers to `[0x6999:1]`, which the EDS does not have
- **THEN** loading is refused with a message naming `0x6999:1` and its position

### Requirement: CiA 402 drive model
A simulated device whose profile is CiA 402 SHALL run a drive model: the power drive state machine on 0x6040/0x6041 (including fault and fault reset, quick stop and the "target reached", "set-point acknowledge" and "following error" bits), the modes of operation in 0x6060/0x6061 that its EDS lists in 0x6502 among profile position, profile velocity, homing, cyclic synchronous position and cyclic synchronous velocity, actual position and velocity (0x6064, 0x606C) following the demand with configurable acceleration limits and a first-order lag, software position limits (0x607D), a following error window (0x6065) that faults the drive with EMCY 0x8611 when exceeded, and limit switch inputs that a user can set. Objects the EDS does not have SHALL be left out of the model and reported once.

#### Scenario: Enable the drive
- **WHEN** a master writes controlword 0x0006, then 0x0007, then 0x000F
- **THEN** the statusword passes through "ready to switch on" and "switched on" and reaches "operation enabled"

#### Scenario: Profile position move
- **WHEN** the drive is enabled in profile position mode and the master sets target position 10000 with a rising new set-point bit
- **THEN** the drive acknowledges the set-point, the actual position moves to 10000 at no more than the profile velocity, and "target reached" is set

#### Scenario: Following error
- **WHEN** a user blocks the simulated axis and the master commands a move beyond the following error window
- **THEN** the drive goes to FAULT and sends EMCY 0x8611

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

#### Scenario: Node lost and back
- **WHEN** a user powers off simulated node 5 while the plugin runs, then powers it on 10 s later
- **THEN** the plugin reports node 5 lost by its heartbeat, then boots and configures it again after its boot-up

#### Scenario: SDO abort rule
- **WHEN** a rule makes 0x2000:1 abort writes with 0x08000020 for the next transfer, and a master writes it twice
- **THEN** the first write aborts with 0x08000020 and the second succeeds

#### Scenario: Wrong product
- **WHEN** a simulated node 23's 0x1018:2 is overridden with another product code and it is power cycled
- **THEN** the plugin's identity check fails the node's boot with the identity error

### Requirement: Simulation file
Behaviour SHALL be configurable in a simulation file that names, per node ID, the value sources, model settings, start-up faults and whether the default behaviour is on, plus extra devices (EDS or DCF, node ID or none for LSS, identity overrides) that are simulated without being in the config, and named scenarios. The file SHALL be optional: without it every device gets its default behaviour. A file entry for a node that is neither configured nor an extra device SHALL be refused.

#### Scenario: No simulation file
- **WHEN** a config with three nodes is simulated without a simulation file
- **THEN** three devices are simulated with their default behaviour

#### Scenario: Extra device for scan
- **WHEN** the simulation file adds an extra device as node 40 with the ping-pong EDS
- **THEN** a bus scan finds node 40 as a device that is not in the config

### Requirement: Scenarios
A scenario SHALL be a named list of steps run in order, each with an optional start time or delay: set or override a value, give or remove a value source, inject or clear a fault, wait until a condition on any simulated object holds (with a timeout), expect a condition (now, within a time, or for a whole duration), log a message, and repeat a block. A scenario SHALL be startable and stoppable while the simulator runs and SHALL report its current step. Scenarios marked `autostart` SHALL start when the simulation starts. Several scenarios MAY run at the same time. An expect that fails, or a wait that times out, SHALL fail the scenario with the step, the condition and the value seen; the simulation SHALL go on.

#### Scenario: Test a PLC alarm
- **WHEN** a scenario sets 0x7130:1 of node 5 to 900, then expects 0x6200:1 bit 2 of node 7 to become 1 within 500 ms
- **THEN** the scenario passes when the PLC program switches on the alarm output in time, and fails with the value seen otherwise

### Requirement: Live control
A running simulator SHALL offer, over its control protocol: the list of simulated devices with their NMT state, power state and injected faults; reading any object's current value without bus traffic; setting a value once; overriding a value (a held value that wins over value sources and models until released); giving, changing and removing value sources; injecting and clearing faults; and starting, stopping and listing scenarios with their state. Every change SHALL be logged with its origin.

#### Scenario: Override a sensor value
- **WHEN** a user overrides 0x7130:1 of node 5 with 1500 while a sine drives it
- **THEN** the object reads 1500 until the override is released, then follows the sine again

#### Scenario: Read without bus traffic
- **WHEN** a client reads 0x6000:1 of a simulated node through the control protocol
- **THEN** the value is returned and no CAN frame is sent
