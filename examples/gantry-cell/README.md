# Gantry cell: a simulated machine with three CiA 402 axes

An OpenPLC Editor project that runs on the [local simulator runtime](../../docs/local-runtime.md) with no CAN adapter and no devices. Its one network is simulated, and a [machine model](../../docs/machine.md) sits on top of the simulated devices: an XYZ gantry with a gripper picks boxes from the end of a conveyor and places them on a 3 × 3 pallet, which a pallet changer swaps when it is full. The configurator's **Machine** view shows it in 3D. [docs/tour.md](../../docs/tour.md#15-machine) walks through it.

## The network

| Network | Bus | What is on it |
|---|---|---|
| `motion` | `sim1`, 500 kbit/s | The master with SYNC from the PLC cycle. Nodes 4 `x`, 5 `y` and 6 `z` (SD-402, CiA 402) as PLCopen axes in cyclic synchronous position mode, 1000 counts per mm, homing method 21 on the home switch. Node 10 `io` (DIO-16, CiA 401): output byte 0x6200:1 runs the conveyor (bit 0), closes the gripper (bit 1) and asks for a pallet change (bit 2); input byte 0x6000:1 reports a part at the pick position (bit 3), the gripper holding a part (bit 4) and a pallet in place (bit 5). |

The diagnostics channel is on with changes allowed, so the Machine view's fault buttons work. Its token is `gantry-cell-demo`; that is fine on your own PC, but set a token of your own (the configurator's **Online access**) before the config goes anywhere else.

## The machine

`canopen/machine.json` describes the cell ([docs/machine.md](../../docs/machine.md) is the reference):

- joints `x` (0 to 900 mm), `y` (0 to 600 mm) and `z` (0 to 300 mm, down), each with a home flag at 0, limit switches 5 mm beyond the travel and hard stops at 12 mm; `z` carries the load of the gripper and the part;
- a gripper whose fingers close along x in 120 ms;
- conveyor `infeed` from x −400 to 120 at y 480, 250 mm/s, fed with a box every 2 to 3 s (seed 1, so every run feeds the same sequence);
- sensor `part_at_pick` at the conveyor's end stop;
- fixture `pallet`: 3 × 3 slots from (500, 120) at a 120 mm pitch, changed in 3.3 s.

## The program

`pous/programs/main.st` starts with what `openplc-canopen-deploy --new-project --task-interval T#10ms` declares for this config, then:

- powers the three axes and homes Z, then X and Y;
- waits for a part at the pick position, moves X and Y in a straight line (both axes get the same S-curve scaled to their share of the distance) and lowers Z;
- closes the gripper and waits for "gripped" (1 s, else it tries the next part);
- lifts Z and starts the XY move to the next slot as soon as the part is clear, lowers Z, opens the gripper;
- with the pallet full, asks for a pallet change and waits for the empty pallet;
- on any drive fault (a jam, a hard stop) releases the moves, waits 2 s, resets the drives (again every half second while a fault stays), lifts Z and carries on with the part in hand, or goes back to the conveyor.

## Files

| File | What it is |
|---|---|
| `project.json`, `devices/`, `pous/` | The editor project (Editor 4.3.2 layout, OpenPLC Runtime v4 target, the `openplc_canopen` library enabled). |
| `canopen/canopen.json` | The CANopen config (`schema_version` 2, one network). |
| `canopen/simulation.json` | The simulation file, version 2 with section `motion`: the machine file, the drive model's settings (1 ms device tick, start positions 20 mm from home), two test scenarios (`fill-a-pallet`, `z-jam`) and two to try by hand (`sensor-stuck-off`, `feeder-empty`). |
| `canopen/machine.json` | The machine file. |
| `canopen/servo402.eds`, `canopen/dio16.eds` | Copies from [`examples/virtual-plant`](../virtual-plant/README.md). |

CI runs the program against the simulated bus and the machine in the `sim_gantry_demo` case of `test/sim/sim_tests.cpp`: it homes, places two parts, jams Z, and checks the drive faults with EMCY 0x8611 and the program recovers.
