# CiA 402 drive as a PLCopen axis

A made-up single-axis servo drive, **SD-402**, used as a PLCopen axis with the editor's built-in motion blocks. In the tests it is played by `Cia402Slave` (`test/drive/cia402_slave.hpp`) on the virtual bus and by an ST model (`test/cia402/drive_model.st`). See [docs/cia402.md](../../docs/cia402.md) for how axes work.

| File | What it is |
|---|---|
| `servo402.eds` | The drive's EDS, written by `make_eds.py` (`python3 config/cia402-drive/make_eds.py config/cia402-drive`). It describes no real product. |
| `canopen_config.json` | The master's config: node 4 `drive` as an axis, heartbeat supervision, the PDO map, startup SDOs for ramps and homing method. |
| `drive_demo.st` | Demo program: power on, home, move to 1000, run at 200 units/s for 2 s, halt; a fault or a lost drive goes to a fault reset and starts again. |

## The device

Device type 0x00020192 (profile 402, servo drive), profile position, profile velocity and homing (method 35: the current position is home). Four RPDOs and four TPDOs with writable mapping; the default mapping is the one the config uses:

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
