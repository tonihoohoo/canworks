## Why

The 2026-10-10 bench run of the CiA 309-3 gateway (add-cia309-gateway, task 9.4) found three glitches in the device simulator:
- A simulated device in the plugin or the bridge (`"simulate": true`) given `forget-node-id` waits for LSS, but an LSS Fastscan (`canworks-diag lss-find`, or the gateway's `_lss_fastscan 0 0 0 0 0 0 0 0`) reports none found after 0.1-0.2 s, one LSS timeout. A standalone `--node 0` device on the same bus was found in 13 s.
- A standalone `--node 0` device that got node ID 70 by LSS shows as "now node 70" in `status`, but `fault 70 ...` answers "node 70 is not simulated". Only its name works.
- `fault <node> emcy 0x0000` logs the fault and sends nothing, while `clear <node> all` sends the error reset EMCY.

The first one comes from an EDS without LSS support (`LSS_Supported` 0 or left out). Such a device does not support LSS, so not answering is correct. What is wrong is that the toolkit let LSS be used on such a node at all: the simulator, the configuration and the online LSS tools.

## What Changes

- **No LSS for a node without LSS support.** A node whose EDS does not say `LSS_Supported=1` (0 or left out):
  - The configuration is rejected when the node has an `lss` object, real or simulated, by the plugin and the deploy tool: "node N (name): 'lss' needs an EDS with LSS_Supported=1; this node's EDS has no LSS". Until now this was a warning. A slave network with `node_id: null` on an EDS without LSS is rejected the same way.
  - The configurator shows the node's LSS settings disabled with the reason. "Use for node..." does not offer the node. Adding a device found by LSS as a node with such an EDS adds it without `lss.assign` and says why.
  - Online LSS operations tied to such a configured node are refused with the same reason, before any frame is sent. This covers the configurator's online view, `canworks-diag` and the CiA 309-3 gateway. An operation is tied to the node when it is on that node's LSS address (EDS vendor ID and product code, and the node's serial number) or sets that node's node ID. Find (Fastscan) for unknown devices is unchanged.
  - The simulator never gives such a device an LSS slave. It refuses `forget_node_id` on it with "node N: its EDS has no LSS (LSS_Supported=0), so it could never get a node ID back", in the answer and the log. It also refuses starting it without a node ID (`--node 0`, an extra device with node 0).
  - The status names the NMT state of a device without a node ID ("no node ID, waiting for LSS") instead of "unknown".
- **Current node ID usable.** A control request (fault, clear, get, set, override, source, power) and a scenario step address a device by its configured node ID, its name, or the node ID it has now (one an LSS master gave it). This is the same lookup in the plugin's sim control and in the standalone simulator.
- **EMCY 0 sends the error reset.** `emcy` with code 0x0000 sends the CiA 301 error reset EMCY (code 0000, the given register, default 0, and the given manufacturer bytes). It clears the device's error stack (0x1003) and a periodic EMCY. `period_ms` with code 0 is refused.

## Impact

- Specs:
  - `canopen-device-simulator` (Fault injection, Live control)
  - `canopen-master-bringup` (LSS configuration checks: warning becomes rejection)
  - `canopen-slave-device` (LSS slave)
  - `canopen-configurator` (LSS node settings, Unconfigured devices in the online view, Use a scanned device for a node, Commission a device without a config)
  - `canopen-online-diagnostics` (LSS commissioning)
- Code:
  - `plugin/src/canopen/eds_check.cpp` and `tools/deploy/canworks/contract.py` (rejections)
  - `plugin/src/canopen/network_lss.cpp` (online refusal)
  - `tools/deploy/canworks/configurator/static/app.js` and `server.py` (disabled settings, Use for node, Add as node)
  - `plugin/src/canopen/sim/sim_engine.cpp` (`forget_node_id` refused without LSS, device lookup, EMCY 0, NMT state name)
  - `plugin/src/canopen/sim/sim_device.{h,cpp}` (error reset EMCY)
  - `plugin/src/canopen/sim/sim_file.cpp` and `tools/deploy/canworks/simfile.py` (extra device with node 0 and start-up `forget_node_id` without LSS refused, EMCY 0 with `period_ms` refused)
  - `tools/sim/main.cpp` (`--node 0` refused without LSS)
- Tests and fixtures that change: see tasks.md 1.1.
- Docs:
  - `docs/config.md` (LSS needs `LSS_Supported=1`, replacing the "warning, not an error" note)
  - `docs/configurator.md` (LSS settings disabled for an EDS without LSS)
  - `docs/simulator.md` (Faults table: `emcy` code 0, `forget_node_id`; faults and devices that need LSS need an EDS with `LSS_Supported=1`; addressing a device by its current node ID)
- Tools version 0.56.1 (`tools/deploy/pyproject.toml`, `canworks/__init__.py`, the doc golden JSON files). A config that has `lss` on an EDS without LSS was accepted before and is now refused. That is the fix itself, so it is not a breaking-change bump.
