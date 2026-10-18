# Gantry cell: a simulated machine with three CiA 402 axes

An OpenPLC Editor project that runs on the [local simulator runtime](../../docs/local-runtime.md) with no CAN adapter and no devices. Its one network is simulated, and a [simulated machine](../../docs/simulator.md#simulated-machine) sits on top of the simulated devices: an XYZ gantry with a gripper picks boxes from the end of a conveyor and places them on a 3 × 3 pallet, which a pallet changer swaps when it is full. The **Machine** tab of the configurator's **Simulation** view shows it in 3D. [docs/tour.md](../../docs/tour.md#15-simulated-machine) walks through it.

## The network

| Network | Bus | What is on it |
|---|---|---|
| `motion` | `sim1`, 500 kbit/s | The master with SYNC from the PLC cycle. Nodes 4 `x`, 5 `y` and 6 `z` (SD-402, CiA 402) as PLCopen axes in cyclic synchronous position mode, 1000 counts per mm, homing method 21 on the home switch. Node 10 `io` (DIO-16, CiA 401): output byte 0x6200:1 runs the conveyor (bit 0), closes the gripper (bit 1) and asks for a pallet change (bit 2); input byte 0x6000:1 reports a part at the pick position (bit 3), the gripper holding a part (bit 4), a pallet in place (bit 5), the safety relay closed (bit 6) and someone in the scanner's warning field (bit 7). Node 11 `panel` (a DIO-16 copy with its own EDS, `panel.eds`): the operator panel's buttons on input bytes 0x6000:1 and 0x6000:2, its lamps on output byte 0x6200:1. Both I/O nodes send their inputs on change and every 100 ms. |

The diagnostics channel is on with changes allowed, so the Machine tab's fault buttons work. Its token is `gantry-cell-demo`; that is fine on your own PC, but set a token of your own (the configurator's **Online access**) before the config goes anywhere else.

## The machine

`canworks/machine.json` describes the cell ([docs/simulator.md](../../docs/simulator.md#simulated-machine) is the reference):

- joints `x` (0 to 900 mm), `y` (0 to 600 mm) and `z` (0 to 300 mm, down), each with a home flag at 0, limit switches 5 mm beyond the travel and hard stops at 12 mm; `z` carries the load of the gripper and the part;
- a gripper whose fingers close along x in 120 ms;
- conveyor `infeed` from x −400 to 120 at y 480, 250 mm/s, fed with a box every 2 to 3 s (seed 1, so every run feeds the same sequence);
- sensor `part_at_pick` at the conveyor's end stop;
- fixture `pallet`: 3 × 3 slots from (500, 120) at a 120 mm pitch, changed in 3.3 s;
- `z` has a holding brake: it stays put in safe torque off;
- an operator panel on node 11 and a virtual safety relay (stop category 1, 300 ms) tripped by the emergency stop and the safety scanner, reset by Reset; it takes the three drives into safe torque off and stops the conveyor. The scanner at the cell's corner has an L-shaped warning field around the fence and a protective field inside it. **This is a model to write the program against, not a safety function.**

| Button | Key | Bit | What the program does with it |
|---|---|---|---|
| Manual (switch) | M | 0x6000:1 bit 0 | Holds the sequence; the axes ramp down where they are and the jog buttons drive them. |
| X+ / X− | → / ← | bits 1, 2 | Jog X. |
| Y+ / Y− | ↑ / ↓ | bits 3, 4 | Jog Y. |
| Z up / Z down | PageUp / PageDown | bits 5, 6 | Jog Z. |
| Fast | Shift | bit 7 | Jog at 150 mm/s instead of 20 mm/s (homed only). |
| Gripper | G | 0x6000:2 bit 0 | In MANUAL: open or close the gripper. |
| Conveyor | C | bit 1 | In MANUAL: start or stop the conveyor. |
| Home | H | bit 2 | In MANUAL: home Z, then X and Y. |
| Start | Enter | bit 3 | In AUTO: go on with the sequence (also after a stop). |
| Stop | S | bit 4 | Stop after the part in hand. |
| Reset | R | bit 5 | Closes the safety relay, and resets drives in fault. |
| Enable | Space | bit 6 | Not needed in this program (`needEnable := TRUE` makes the jog an enabling-button jog). |
| Emergency stop (latching) | E | bit 7 | Trips the relay. |

Lamps on 0x6200:1: bit 0 Manual, bit 1 Homed, bit 2 Fault (blinks while the relay is open), bit 3 Auto.

## The program

`pous/programs/main.st` starts with what `canworks-deploy --new-project --task-interval T#10ms` declares for this config, then:

- powers the three axes and homes Z, then X and Y;
- waits for a part at the pick position, moves X and Y in a straight line (both axes get the same S-curve scaled to their share of the distance) and lowers Z;
- closes the gripper and waits for "gripped" (1 s, else it tries the next part);
- lifts Z and starts the XY move to the next slot as soon as the part is clear, lowers Z, opens the gripper;
- with the pallet full, asks for a pallet change and waits for the empty pallet;
- on any drive fault (a jam, a hard stop) releases the moves, waits 2 s, resets the drives (again every half second while a fault stays), lifts Z and carries on with the part in hand, or goes back to the conveyor;
- in MANUAL, or after a safety stop, holds the sequence: the jog takes the axes from where they are at the speed they have, so a running move ramps down instead of stopping dead; the jog ramps at 1000 mm/s² and stays inside the soft limits (0 to 900, 600 and 300 mm) once homed; `CO402_CyclicPosition` writes its set-point every cycle;
- on a safety stop (the relay's feedback goes off) ramps the axes down at 4000 mm/s², inside the relay's 300 ms, and disables them after 250 ms; once Reset closes the relay it powers them again, and Start goes on: Z up and on with the part in hand, or a pallet change where it was;
- runs the XY and Z moves at a quarter of their speed while someone is in the scanner's warning field.

## Files

| File | What it is |
|---|---|
| `project.json`, `devices/`, `pous/` | The editor project (Editor 4.3.2 layout, OpenPLC Runtime v4 target, the `canworks` library enabled). |
| `canworks/canworks.json` | The CANopen config (`schema_version` 2, one network). |
| `canworks/simulation.json` | The simulation file, version 2 with section `motion`: the machine file, the drive model's settings (1 ms device tick, start positions 20 mm from home), three test scenarios (`fill-a-pallet`, `z-jam`, `emergency-stop`) and three to try by hand (`sensor-stuck-off`, `feeder-empty`, `person-in-cell`). |
| `canworks/machine.json` | The machine file. |
| `canworks/servo402.eds`, `canworks/dio16.eds` | Copies from [`examples/virtual-plant`](../virtual-plant/README.md). |
| `canworks/panel.eds`, `canworks/panel.eds.notes.json` | The operator panel: a copy of `dio16.eds` and notes that name each button and lamp bit. |

CI runs the program against the simulated bus and the machine in the `sim_gantry_demo` case of `test/sim/sim_tests.cpp`: it homes, places two parts, jams Z, and checks the drive faults with EMCY 0x8611 and the program recovers. Then it switches to MANUAL during a move (the axes ramp down with no fault), jogs X fast to its soft limit, goes back to AUTO with Start, presses the emergency stop during a fast move (the axes are stopped before safe torque off and Z holds on its brake), resets and starts again, and puts a person in the scanner's warning field (a quarter speed) and its protective field (a safety stop).
