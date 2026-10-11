## 1. Fixes

- [x] 1.1 No LSS for a node whose EDS does not say `LSS_Supported=1` (0 or left out):
  - Config: the plugin (`eds_check.cpp`) and `contract.py` reject any `lss` object on such a node, real or simulated, with "node N (name): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS", and a slave with `node_id: null` on such an EDS. Shared cases in `test/fixtures/config/cases.json`: `lss.assign`, `{}` and a simulated node on `cpp-slave.eds` rejected, `{}` on `lss-slave.eds` accepted; the slave with `node_id: null` on an EDS without LSS in `test_slave.py` and `slave_tests` (`slave_lss_needs_an_lss_eds`).
  - Online: `Network::DiagLss()` refuses inquire, set node ID, set bit rate and store tied to such a configured node (its EDS vendor ID and product code plus its `serial_number`, or Set node ID to its node ID), sending nothing. Find is unchanged. Sim test through the diagnostics channel (`sim_simulated_lss_and_error_reset`: inquire on node 2's address refused, no LSS frame; the CiA 309-3 gateway's `lss_*` requests go through the same `DiagLss()`), and Find still runs there.
  - Configurator: LSS checkboxes disabled with the reason; a loaded `lss` on such a node shown as a problem with a remove action; "Use for node..." lists the node disabled; "Add as node" / "Add to a config..." add it without `lss.assign` and say why (page tests).
  - Simulator: `forget_node_id` refused without LSS (control protocol, scenario step, start-up fault), as are an extra device with node 0 and `--node 0`, each with "node N: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back" in the answer and the log; the same in `simfile.py`. Sim test: refused on `cpp-slave.eds`, the device keeps its node ID; on `lss-slave.eds` the forgotten device is found by the master's Fastscan, `lss_set_id` makes it node 70, it answers SDO, a power cycle gives back its configured node ID. Python test for the PC simulation check.
  - Existing tests and fixtures that use LSS with an EDS without LSS support and must change:
    - `test/fixtures/config/cases.json`, case "LSS assignment with an EDS without LSS_Supported" (node 2 on `cpp-slave.eds`): accept with a warning becomes reject with the new message.
    - `tools/deploy/tests/test_configurator_page.py`, `test_lss_settings` (tail): on `cpp-slave.eds` it expects the warning and an enabled "Assign" box; it now expects a disabled box with the reason.
    - `tools/deploy/tests/test_configurator_online_page.py`, `test_lss_commission_new_device`: the found device matches `cpp-slave.eds` and is added as node 40 with `lss.assign`. Use an LSS EDS in the test's library (e.g. `lss-slave.eds`) for that path, and add a case where a `cpp-slave.eds` match is added without `lss.assign`.
    - `tools/deploy/tests/test_configurator_online_page.py`, `test_scan_use_for_node`: node 2 (`cpp-slave.eds`) gets `lss.assign` from "Use for node". Give the test's node an LSS EDS, and add a case where the `cpp-slave.eds` node is listed disabled.
    - `tools/deploy/tests/test_configurator_commissioning_page.py`, `test_guided_commissioning_log_and_add_to_a_config`: "Add to a config..." with `fixed-io.eds` (`LSS_Supported=0`) expects `lss.assign` true. It now expects no `lss` and the reason shown, or switch to an LSS EDS and keep the assertion.
    - Checked and unchanged (EDS says `LSS_Supported=1`): `test/sim/sim_tests.cpp` LSS cases (`lss-slave.eds`), `test/lss/run.sh`, `test/slave/slave_tests.cpp` (`openplc-slave.eds`), `examples/virtual-plant/canworks/canworks.json` node 7 (`dio16.eds`), the other `cases.json` LSS cases (`lss-slave.eds`), `test/localbus/run.sh` (no config).
- [x] 1.2 NMT state of a device without a node ID named in `sim_status` and the standalone `status` ("no node ID, waiting for LSS") (`sim_simulated_lss_and_error_reset`)
- [x] 1.3 `Simulator::Find()` also matches the current node ID of a powered device, after configured node IDs and names (`sim_simulated_lss_and_error_reset`: fault and clear by the LSS-given node ID 70 and by the configured node ID; test/simulator/run.sh: `fault 70` and the name)
- [x] 1.4 `emcy` code 0x0000 sends one error reset EMCY with the given register and manufacturer bytes, clears 0x1003 and a periodic EMCY; `period_ms` with code 0 refused (sim test on the bus with and without an earlier EMCY; file check and control protocol refusal; `test_diag_sim.py`)
- [x] 1.5 Standalone simulator: `fault 70 heartbeat-stop` after LSS gave a `--node 0` device (`lss-slave.eds`) node 70 (test/simulator/run.sh)

## 2. Docs and version

- [x] 2.1 docs/config.md (LSS needs `LSS_Supported=1`; fix the EDS when it leaves the flag out), docs/configurator.md (LSS settings disabled for such an EDS), docs/simulator.md (Faults table: `emcy` code 0, `forget_node_id` refused without LSS; faults and devices without a node ID need an EDS with `LSS_Supported=1`; addressing a device by its current node ID)
- [x] 2.2 Tools 0.56.1: `tools/deploy/pyproject.toml`, `tools/deploy/canworks/__init__.py`, `tools/deploy/tests/data/doc/*.json`

## 3. Hardware

- [ ] 3.1 Bench: `forget-node-id` on an in-plugin simulated device whose EDS has no LSS is refused with the message; on one whose EDS has `LSS_Supported=1` the device is found by `canworks-diag lss-find` and by the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`, gets a node ID with `lss_set_node`, and a power cycle gives it its configured node ID back
- [ ] 3.2 Bench: `canworks-diag sim fault <node> emcy 0x0000` puts one EMCY 0000 on the bus (candump), and the master logs the error reset
- [ ] 3.3 Bench: the gateway's `lss_switch_sel` plus `lss_set_node` on the LSS address of a configured node whose EDS has no LSS (its serial number in the config) is refused with that node's message, and nothing is sent
