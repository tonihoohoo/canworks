# canopen-machine-model Specification

## Purpose
A kinematic machine model (an XYZ gantry with a gripper, conveyors, sensors and a pallet) that runs on a simulated network on top of the simulated CiA 402 drives and CiA 401 I/O: its file, its checks, how it reads drive positions and output bits and writes switches, load and input bits, its faults and conditions, and the state it reports on the diagnostics channel.

## Requirements

### Requirement: Machine on a simulated network
A network's simulation file section SHALL be able to name one machine file. The simulator of that network SHALL then run the machine model on its own clock, after the simulated devices' tick and before value sources, in the plugin and in the standalone simulator alike. The machine's own step SHALL default to 2 ms and be settable in the machine file. Every node the machine names SHALL be a simulated node of that network.

#### Scenario: Machine runs with the network
- **WHEN** the `motion` section of a version 2 simulation file names `machine.json` and the network is simulated
- **THEN** the PLC start log names the machine and `sim_machine` with `network: "motion"` answers with its state

#### Scenario: Node not simulated
- **WHEN** the machine binds joint `z` to node 6 and node 6 has `"simulate": false`
- **THEN** the check fails naming the joint and node 6

### Requirement: Machine only on simulated networks
A machine SHALL only run on a network that is simulated (`adapter.simulate`, or forced by the runtime). On a real network the plugin SHALL log that the machine is not used, and the deploy tool's check SHALL warn the same.

#### Scenario: Real network
- **WHEN** the same config runs `motion` on a real interface
- **THEN** the plugin logs that the machine is not used and no drive input or I/O object is written by it

### Requirement: Joints from drive positions
A joint SHALL be bound to one CiA 402 axis node and SHALL take its position from that drive's actual position, converted with the joint's counts per unit, offset and direction. A joint SHALL set the drive's home switch input while it is inside its home flag, its positive or negative limit switch input while it is past a limit, and its blocked input while it is at a hard stop. These inputs SHALL be combined with the drive input fault, so either one sets an input.

#### Scenario: Homing on the flag
- **WHEN** joint `x` has its home flag at 0 mm and the PLC homes node 4 with a method that searches the home switch in the negative direction
- **THEN** the drive's home switch input turns on as the joint reaches 0 mm and the homing ends there

#### Scenario: Hard stop
- **WHEN** joint `y` has a hard stop at 612 mm and the PLC commands node 5 beyond it
- **THEN** the joint stops at 612 mm, the drive's following error grows, and the drive goes to FAULT with EMCY 0x8611

### Requirement: Load on a joint
A joint SHALL be able to have a load: a holding torque for a vertical joint and a torque per kilogram of payload, both in per mille of rated torque, plus a share proportional to the joint's acceleration. The drive model SHALL show the load in its actual torque (0x6077) while operation is enabled. In cyclic synchronous torque mode, the load SHALL reduce the acceleration the target torque gives.

#### Scenario: Holding a part
- **WHEN** joint `z` has a holding torque of 165 per mille and 140 per mille per kilogram, and the gripper holds a 0.4 kg part at standstill
- **THEN** node 6's 0x6077 reads 221 within the drive model's lag

### Requirement: Gripper tool
The machine SHALL be able to have a gripper on its tool point, closed by a bit of a CiA 401 output object and reporting "gripped" on a bit of an input object. The fingers SHALL take the configured stroke time to open or close.

#### Scenario: Close on nothing
- **WHEN** the PLC closes the gripper with no part between the fingers
- **THEN** the fingers close fully and the "gripped" bit stays off

### Requirement: Gripping a part
A part between the fingers, at the tool's height and within the pick tolerance, SHALL become held when the fingers close on it, and SHALL then move with the tool. The "gripped" input SHALL be on only while a part is held and the gripper is closed. Opening the gripper SHALL release the part.

#### Scenario: Pick a part
- **WHEN** a part waits at the pick position, the tool is lowered to it and the PLC sets the close bit
- **THEN** after the stroke time the "gripped" bit turns on and the part rises with the tool

### Requirement: Conveyors and feeders
A belt conveyor SHALL move the parts on it at its speed while its run bit is on. Parts SHALL queue against the end stop and against each other, keeping a gap. A feeder SHALL place a new part at the conveyor's start at an interval within its configured range, when there is room.

#### Scenario: Conveyor stopped
- **WHEN** the run bit goes off while a part is halfway along the belt
- **THEN** the part stops where it is and moves on when the bit is on again

### Requirement: Presence sensors
A presence sensor SHALL set its input bit while a part, or the tool when configured, is inside its detection box.

#### Scenario: Part at pick
- **WHEN** a part reaches the end stop inside the pick sensor's box
- **THEN** the sensor's input bit turns on and the I/O node sends it in its TPDO as any input change

### Requirement: Fixtures with slots
A fixture SHALL hold slots on a grid. A released part that lands on a slot within the place tolerance SHALL snap into the slot and count as placed. A part that lands anywhere else SHALL count as misplaced, and a part released above nothing SHALL fall onto the table and count as dropped. A fixture with a change request bit SHALL, while the bit is on, clear its ready input, move the full pallet out, empty it and bring it back over the configured time, then set its ready input again.

#### Scenario: Full pallet
- **WHEN** nine parts are placed on a 3 x 3 pallet and the PLC sets the change bit
- **THEN** the ready bit goes off, the pallet comes back empty after the change time, and the ready bit turns on

### Requirement: Contacts block motion
When the tool, the fingers or a held part would move into a part, a fixture or the table, the moving joint SHALL be blocked at the contact, so the drive model raises its following error as on a real machine.

#### Scenario: Lowering onto a part
- **WHEN** the PLC lowers the tool onto a part that sits where the program expects an empty slot
- **THEN** joint `z` stops at the part's top and node 6 goes to FAULT with EMCY 0x8611

### Requirement: Machine faults
A user SHALL be able to inject into a machine, at once or from a scenario step, and clear again:
- a jam of a joint (blocked until cleared);
- a sensor stuck on or stuck off;
- a gripper slip that drops the held part;
- a feeder stop, and an empty feeder;
- a part misaligned on the belt by a given offset, so a pick misses.

`clear` with `all` SHALL remove every machine fault.

#### Scenario: Dirty sensor
- **WHEN** a user sets the pick sensor stuck off while parts queue at the end stop
- **THEN** the sensor bit stays off, the program waits, and after clearing the fault the bit turns on

### Requirement: Machine conditions in scenarios
Scenario `wait` and `expect` steps SHALL accept conditions on the machine's counters (placed, dropped, misplaced, picked) and sensor states, with the same comparison operators as object conditions.

#### Scenario: Throughput test
- **WHEN** a `test` scenario expects `placed` to be at least 9 within 60 s and `dropped` to stay 0 for the whole time
- **THEN** it passes when the program places nine parts in time without dropping one, and fails naming the counter and its value otherwise

### Requirement: Machine state request
The simulator SHALL answer a read-only `sim_machine` request, which needs only the token, with the machine's state at one simulator time. The answer for a machine with up to 50 parts SHALL fit in 16 KB. On a network without a machine it SHALL answer `no machine`.

#### Scenario: Viewer poll
- **WHEN** a client sends `sim_machine` for `motion` 30 times per second for a minute
- **THEN** every answer arrives, time stamps increase, and the PLC's SYNC on that network keeps its period

### Requirement: Machine state contents
A `sim_machine` answer SHALL hold:
- the simulator's time stamp in microseconds and a sequence number;
- per joint its position, velocity, demand position, drive state and fault;
- the tool's opening and whether it holds a part;
- every part with its id, kind, position, yaw and state (on a belt, held, falling, placed, on the table);
- every sensor's state, every fixture's state and pallet offset, and the counters.

#### Scenario: Part held
- **WHEN** the gripper holds a part and a client sends `sim_machine`
- **THEN** the answer shows that part as held at the tool's position and the tool as closed with a part
