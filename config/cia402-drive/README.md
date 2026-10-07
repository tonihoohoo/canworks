# CiA 402 drive as a PLCopen axis

A made-up single-axis servo drive, **SD-402**, used as a PLCopen axis with the editor's built-in motion blocks. In the tests it is played by `Cia402Slave` (`test/drive/cia402_slave.hpp`) on the virtual bus and by an ST model (`test/cia402/drive_model.st`). See [docs/cia402.md](../../docs/cia402.md) for how axes work.

| File | What it is |
|---|---|
| `servo402.eds` | The drive's EDS, written by `make_eds.py` (`python3 config/cia402-drive/make_eds.py config/cia402-drive`). It describes no real product. |
| `canopen_config.json` | The master's config: node 4 `drive` as an axis, heartbeat supervision, the PDO map, startup SDOs for ramps and homing method. |
| `drive_demo.st` | Demo program: power on, home, move to 1000, run at 200 units/s for 2 s, halt; a fault or a lost drive goes to a fault reset and starts again. |
| `canopen_config_cyclic.json` | The same drive as a cyclic synchronous axis: SYNC from the PLC cycle, synchronous PDOs (transmission type 1), following error window and homing method by startup SDO. |
| `drive_cyclic_demo.st` | Cyclic demo program (task interval T#10ms): power on, home, a jerk-limited CSP move to 1000, 2 s at 200 units/s in CSV, a torque step in CST, standstill in CSV; a fault (also from a PLC stop) goes to a fault reset and starts again. |

## The device

Device type 0x00020192 (profile 402, servo drive), profile position, profile velocity, homing (method 35: the current position is home) and the cyclic synchronous modes 8, 9 and 10 (0x6502 is 0x000003A5), with an interpolation time period 0x60C2 and a following error window 0x6065/0x6066. Four RPDOs and four TPDOs with writable mapping; the default mapping is the one the config uses:

| PDO | Objects | PLC |
|---|---|---|
| RPDO 1 | controlword 0x6040, modes of operation 0x6060 | `%QW100`, `%QB100` |
| RPDO 2 | target position 0x607A, profile velocity 0x6081 | `%QD100`, `%QD101` |
| RPDO 3 | target velocity 0x60FF | `%QD102` |
| TPDO 1 | statusword 0x6041, modes of operation display 0x6061 | `%IW100`, `%IB100` |
| TPDO 2 | position actual value 0x6064 | `%ID100` |
| TPDO 3 | velocity actual value 0x606C | `%ID101` |

RPDO 4 and TPDO 4 (torques) are not in the config, so the master switches them off. All PDOs keep the EDS's transmission type 255 (event-driven); the TPDOs also send every 50 ms (event timer). The status bit is `%IX10.0`.

## Try it

1. Create an editor project from the config: `openplc-canopen-deploy --config config/cia402-drive/canopen_config.json --new-project <folder>/drive-demo`, or **New editor project…** in the configurator.
2. In the editor (4.3.2), replace `main` with `drive_demo.st`: its VAR block and first lines are what the generator wrote, followed by the demo.
3. Build and upload. The sequence runs once after start (`start` is TRUE by default; set it FALSE to hold at step 0); `step` shows where it is (50 done, 90 fault reset).

## The cyclic variant

`canopen_config_cyclic.json` maps the drive for the cyclic synchronous modes:

| PDO | Objects | PLC |
|---|---|---|
| RPDO 1 | controlword 0x6040, modes of operation 0x6060, target position 0x607A | `%QW100`, `%QB100`, `%QD100` |
| RPDO 2 | target velocity 0x60FF, target torque 0x6071 | `%QD101`, `%QW101` |
| TPDO 1 | statusword 0x6041, modes of operation display 0x6061, position actual value 0x6064 | `%IW100`, `%IB100`, `%ID100` |
| TPDO 2 | velocity actual value 0x606C, torque actual value 0x6077 | `%ID101`, `%IW101` |

All four have transmission type 1, and the master sends SYNC from the PLC cycle; the plugin writes 0x60C2 from the runtime's cycle time. Create the project with `--task-interval T#10ms` (the generated `fCycleTime` line follows it) and replace `main` with `drive_cyclic_demo.st`; the generated project enables the `openplc_canopen` library with the `CO402_Cyclic*` blocks. See [docs/cia402.md](../../docs/cia402.md#cyclic-synchronous-modes).
