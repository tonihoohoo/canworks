## 1. Fixes

- [ ] 1.1 Refuse what would leave a device without LSS support (`LSS_Supported` 0 or left out) without a node ID: the `forget_node_id` fault (control protocol, start-up faults, scenario step), an extra device with node 0, a simulated node with `lss.assign`, and the standalone `--node 0`, each with "node N: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back" in the answer and the log; the same check in the PC tools' simulation check. Sim test: refused on `cpp-slave.eds`, and the device keeps its node ID; on an EDS with `LSS_Supported=1` the forgotten device is found by the master's Fastscan, `lss_set_id` makes it node 70, it answers SDO, and a power cycle gives back its configured node ID. Python test for the PC check. Check that the repo's examples and fixtures still load.
- [ ] 1.2 NMT state of a device without a node ID named in `sim_status` and the standalone `status` ("no node ID, waiting for LSS") (sim unit test)
- [ ] 1.3 `Simulator::Find()` also matches the current node ID of a powered device, after configured node IDs and names (sim unit test: fault, clear, get and override by the LSS-given node ID; name and configured node ID still work; a configured node ID wins)
- [ ] 1.4 `emcy` code 0x0000 sends one error reset EMCY with the given register and manufacturer bytes, clears 0x1003 and a periodic EMCY; `period_ms` with code 0 refused (sim test on the bus with and without an earlier EMCY; file check and control protocol refusal; `test_diag_sim.py`)
- [ ] 1.5 Standalone simulator: `fault 70 heartbeat-stop` after LSS gave a `--node 0` device node 70 (test/simulator/run.sh)

## 2. Docs and version

- [ ] 2.1 docs/simulator.md: Faults table (`emcy` code 0; `forget_node_id` refused without LSS); faults and devices without a node ID need an EDS with `LSS_Supported=1` (`--node 0`, `extra_devices` node 0, `lss.assign`); addressing a device by its current node ID
- [ ] 2.2 Tools 0.56.1: `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, `tools/deploy/tests/data/doc/*.json`

## 3. Hardware

- [ ] 3.1 Bench: `forget-node-id` on an in-plugin simulated device whose EDS has no LSS is refused with the message; on one whose EDS has `LSS_Supported=1` the device is found by `canworks-diag lss-find` and by the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`, gets a node ID with `lss_set_node`, and a power cycle gives it its configured node ID back
- [ ] 3.2 Bench: `canworks-diag sim fault <node> emcy 0x0000` puts one EMCY 0000 on the bus (candump), and the master logs the error reset
