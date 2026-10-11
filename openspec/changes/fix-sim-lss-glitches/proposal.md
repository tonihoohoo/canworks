## Why

The 2026-10-10 bench run of the CiA 309-3 gateway (add-cia309-gateway, task 9.4) found three glitches in the device simulator:
- A simulated device in the plugin or the bridge (`"simulate": true`) given `forget-node-id` waits for LSS, but an LSS Fastscan (`canworks-diag lss-find`, or the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`) reports none found after 0.1-0.2 s, one LSS timeout. A standalone `--node 0` device on the same bus was found in 13 s.
- A standalone `--node 0` device that got node ID 70 by LSS shows as "now node 70" in `status`, but `fault 70 ...` answers "node 70 is not simulated". Only its name works.
- `fault <node> emcy 0x0000` logs the fault and sends nothing, while `clear <node> all` sends the error reset EMCY.

## What Changes

- A device whose EDS does not say `LSS_Supported=1` (0 or left out) does not support LSS. Not answering an LSS Fastscan is correct for it, and the simulator does not give it an LSS slave. What changes is that the simulator no longer lets such a device lose its node ID. `forget_node_id` on it is refused: "node N: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back". The refusal goes back to the caller (`canworks-sim fault`, `canworks-diag sim fault`, a scenario step) and into the log. Starting such a device without a node ID is refused with the same reason: `--node 0`, an extra device with node 0, a simulated node with `lss.assign`. A device with LSS support behaves as before. The status names the NMT state of a device without a node ID ("no node ID, waiting for LSS") instead of "unknown".
- A control request (fault, clear, get, set, override, source, power) and a scenario step address a device by its configured node ID, its name, or the node ID it has now (one an LSS master gave it). This is the same lookup in the plugin's sim control and in the standalone simulator.
- `emcy` with code 0x0000 sends the CiA 301 error reset EMCY (code 0000, the given register, default 0, and the given manufacturer bytes). It clears the device's error stack (0x1003) and a periodic EMCY. `period_ms` with code 0 is refused.

## Impact

- Specs: `canopen-device-simulator` (Fault injection, Live control).
- Code: `plugin/src/canopen/sim/sim_device.{h,cpp}` (error reset EMCY), `plugin/src/canopen/sim/sim_engine.cpp` (`forget_node_id` and start without a node ID refused without LSS, device lookup, EMCY 0, NMT state name), `plugin/src/canopen/sim/sim_file.cpp` and `plugin/src/canopen/sim_config.cpp` (device without a node ID on an EDS without LSS refused, EMCY 0 with `period_ms` refused), `tools/sim/main.cpp` (`--node 0` refused the same way), the PC tools' simulation check (`tools/deploy/canworks/simfile.py`, same refusals), `tools/deploy/canworks/simcli.py` (help text) if needed.
- Tests: `test/sim/sim_tests.cpp` (`forget_node_id` refused on an EDS with `LSS_Supported=0`; on an EDS with `LSS_Supported=1` the device is found by the master's Fastscan and given a node ID; EMCY 0 on the bus), `test/sim_unit/sim_control_tests.cpp` (lookup by the current node ID), `test/simulator/run.sh` (standalone `fault 70` after LSS), `tools/deploy/tests/test_diag_sim.py` (EMCY 0 request).
- Docs: `docs/simulator.md` (Faults table: `emcy` code 0, `forget_node_id`; faults and devices that need LSS need an EDS with `LSS_Supported=1`; addressing a device by its current node ID).
- Tools version 0.56.1 (`tools/deploy/pyproject.toml`, `canworks/__init__.py`, the doc golden JSON files).
