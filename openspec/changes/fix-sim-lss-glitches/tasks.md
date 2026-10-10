## 1. Fixes

- [ ] 1.1 LSS slave on a simulated device without a node ID: `co_dev_set_lss` before the reset in `PowerOn()` (node ID 0xFF) and in `ForgetNodeId()`, with the log line when the EDS lacks `LSS_Supported=1` (sim test: an in-plugin device built from an EDS with `LSS_Supported=0` given `forget_node_id` is found by the master's Fastscan, `lss_set_id` makes it node 70 and it answers SDO; the same for an extra device with node 0)
- [ ] 1.2 NMT state of a device without a node ID named in `sim_status` and the standalone `status` ("no node ID, waiting for LSS") (sim unit test)
- [ ] 1.3 `Simulator::Find()` also matches the current node ID of a powered device, after configured node IDs and names (sim unit test: fault, clear, get and override by the LSS-given node ID; name and configured node ID still work; a configured node ID wins)
- [ ] 1.4 `emcy` code 0x0000 sends one error reset EMCY with the given register and manufacturer bytes, clears 0x1003 and a periodic EMCY; `period_ms` with code 0 refused (sim test on the bus with and without an earlier EMCY; file check and control protocol refusal; `test_diag_sim.py`)
- [ ] 1.5 Standalone simulator: `fault 70 heartbeat-stop` after LSS gave a `--node 0` device node 70 (test/simulator/run.sh)

## 2. Docs and version

- [ ] 2.1 docs/simulator.md: Faults table (`emcy` code 0, `forget_node_id` with the LSS slave), addressing a device by its current node ID, LSS slave on a device without a node ID
- [ ] 2.2 Tools 0.56.1: `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, `tools/deploy/tests/data/doc/*.json`

## 3. Hardware

- [ ] 3.1 Bench: an in-plugin simulated device given `forget-node-id` is found by `canworks-diag lss-find` and by the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`, gets a node ID with `lss_set_node`, and a power cycle gives it its configured node ID back
- [ ] 3.2 Bench: `canworks-diag sim fault <node> emcy 0x0000` puts one EMCY 0000 on the bus (candump), and the master logs the error reset
