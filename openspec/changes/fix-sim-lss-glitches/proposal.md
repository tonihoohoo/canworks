## Why

The 2026-10-10 bench run of the CiA 309-3 gateway (add-cia309-gateway, task 9.4) found three glitches in the device simulator:
- A simulated device in the plugin or the bridge (`"simulate": true`) given `forget-node-id` waits for LSS, but an LSS Fastscan (`canworks-diag lss-find`, or the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`) reports none found after 0.1-0.2 s, one LSS timeout. A standalone `--node 0` device on the same bus was found in 13 s.
- A standalone `--node 0` device that got node ID 70 by LSS shows as "now node 70" in `status`, but `fault 70 ...` answers "node 70 is not simulated". Only its name works.
- `fault <node> emcy 0x0000` logs the fault and sends nothing, while `clear <node> all` sends the error reset EMCY.

## What Changes

- A simulated device that starts without a node ID (`--node 0`, an extra device with node 0, a node with `lss.assign`) or loses it (`forget_node_id`) always runs an LSS slave, even when its EDS does not say `LSS_Supported=1`. Until now Lely's LSS slave came only with that flag, so such a device could not be found or configured. The log says so when the EDS does not have the flag. The status names the NMT state of a device without a node ID ("no node ID, waiting for LSS") instead of "unknown".
- A control request (fault, clear, get, set, override, source, power) and a scenario step address a device by its configured node ID, its name, or the node ID it has now (one an LSS master gave it). This is the same lookup in the plugin's sim control and in the standalone simulator.
- `emcy` with code 0x0000 sends the CiA 301 error reset EMCY (code 0000, the given register, default 0, and the given manufacturer bytes). It clears the device's error stack (0x1003) and a periodic EMCY. `period_ms` with code 0 is refused.

## Impact

- Specs: `canopen-device-simulator` (Fault injection, Live control).
- Code: `plugin/src/canopen/sim/sim_device.{h,cpp}` (LSS slave on, error reset EMCY), `plugin/src/canopen/sim/sim_engine.cpp` (device lookup, EMCY 0, NMT state name, power on without node ID), `plugin/src/canopen/sim/sim_file.cpp` (EMCY 0 with `period_ms` refused), `tools/deploy/canworks/simcli.py` (help text) if needed.
- Tests: `test/sim/sim_tests.cpp` (an in-plugin device with an EDS without `LSS_Supported` given `forget_node_id`, found by the master's Fastscan and given a node ID; EMCY 0 on the bus), `test/sim_unit/sim_control_tests.cpp` (lookup by the current node ID), `test/simulator/run.sh` (standalone `fault 70` after LSS), `tools/deploy/tests/test_diag_sim.py` (EMCY 0 request).
- Docs: `docs/simulator.md` (Faults table: `emcy` code 0, `forget_node_id`; addressing a device by its current node ID; LSS slave on a device without a node ID).
- Tools version 0.56.1 (`tools/deploy/pyproject.toml`, `canworks/__init__.py`, the doc golden JSON files).
