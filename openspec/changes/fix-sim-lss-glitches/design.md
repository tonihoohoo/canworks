## Context

Three glitches from the 2026-10-10 bench run (add-cia309-gateway task 9.4). The root causes below come from reading the simulator and the Lely sources at the pinned commit (`tools/deploy/canworks/_lely_dcf/VERSION`). Each one gets a test that fails before the fix (tasks 1.x).

## Root causes

### 1. No LSS answer after `forget-node-id`

`SimDevice::ForgetNodeId()` sets the pending node ID to 0xFF and resets communication. That part works: after the reset Lely's active and pending node IDs are both 0xFF and the NMT state stays in reset communication (Lely's state 7, shown as "unknown" by `sim status`). The plugin's `lss_watch` lets Fastscan through because the device has no valid node ID.

The device still does not answer. Lely creates its LSS slave service only when the device says it supports LSS. In `nmt_srv.c`, `co_nmt_srv_init_lss()` returns at once when `co_dev_get_lss()` is false, and that flag is read from `[DeviceInfo] LSS_Supported` in the EDS. Many EDS files leave it out or set it to 0, including the repo's `cpp-slave.eds` and `servo402.eds`. A config node's simulated device built from such an EDS has no LSS slave at all. Nothing answers the Fastscan's first frame (the "any device without a node ID?" check, bit check 0x80), so Lely's master ends the scan after one LSS timeout (about 0.1 s) with `timed_out`. The plugin reports that as "none found". The standalone device was found because its EDS says `LSS_Supported=1`. A full search takes 13 s because it runs about 128 steps, each one LSS timeout.

The master's side is not involved. The same fastscan path found the standalone device, and the in-plugin device gets the master's frames through its own SocketCAN socket (loopback), like every other request it answers. The same gap affects a device that starts without a node ID (`--node 0`, an extra device with node 0, a node with `lss.assign`) when its EDS lacks the flag. It cannot be found or configured.

### 2. `fault 70` not found after LSS

`Simulator::Find()` matches only the configured node ID (`spec.node`, 0 for a device started without one) and an extra device's name. `sim_status` already reports the current node ID (`node_id` when it differs, printed as "now node 70"), but the lookup never reads it. The plugin's sim control (`canworks-diag sim`) and scenario steps go through the same `Find()`, so they have the same gap.

### 3. `emcy 0x0000` sends nothing

The fault calls `SimDevice::SendEmcy()`, which calls Lely's `Error()`, which calls `co_emcy_push()`. `co_emcy_push()` refuses error code 0 (`ERRNUM_INVAL`, "not an error"), and the return value is ignored. The fault is still logged and kept as active. `clear emcy` / `clear all` call `co_emcy_clear()`, which sends the error reset only when Lely's error stack has entries. That is why the clear works after an earlier EMCY and does nothing on a clean device. Nothing deliberate is behind this: CiA 301 defines code 0000 as "error reset or no error", and a device sends it with its current error register.

## Decisions

- **LSS slave on when the device has no node ID.** Before the device's first reset in `PowerOn()` with node ID 0xFF, and in `ForgetNodeId()` before its reset communication, the simulator calls `co_dev_set_lss(dev, 1)` when the flag is not set. It logs once: "EDS does not say LSS_Supported=1; simulated with an LSS slave so it can get a node ID". Lely's reset communication then creates the service (`co_nmt_srv_set(..., CO_NMT_SRV_LSS)` reads the flag at that moment). The flag stays on for the rest of the device's power-on, so the device can still be configured and stored after it got a node ID. A power cycle rebuilds the device from its EDS, and a device that starts with a node ID keeps the EDS's choice. A device with a node ID and `LSS_Supported=0` still does not answer LSS. Alternative considered: refuse `forget_node_id` for such an EDS. Rejected because docs/config.md already says many EDS files leave the flag out on devices that support LSS, and a device without a node ID and without LSS is useless in a simulation.
- **NMT state name.** `nmt_name()` and the log name the reset communication state of a device without a node ID "no node ID" (status JSON `"nmt": "lss"`, printed "no node ID, waiting for LSS"), so the status no longer says "unknown" or a bare 7.
- **Lookup order.** `Find(ref)` checks the configured node IDs and the names first, then the current node ID of a powered device (`dev->node_id()` 1-127). A configured node ID always wins: it is the stable key the configuration and the simulation file use. A device found by its current node ID keeps its configured node ID and name. If a powered device's current node ID equals another device's configured one, the request goes to the configured device. That is a node ID conflict, which the status shows. The error for an unknown number stays "node N is not simulated".
- **EMCY code 0.** `SimDevice::SendErrorReset(reg, msef)` empties Lely's error stack and 0x1003, sets 0x1001 to `reg`, and sends one frame (code 0000, `reg`, `msef`) on the 0x1014 COB-ID through the device's send hook, so power and other faults still apply. If the stack had entries, the reset frame Lely's `co_emcy_clear()` sends is suppressed by a one-shot filter in the send hook (EMCY COB-ID, code 0), so exactly one error reset frame goes out. The engine stops a periodic EMCY and drops the active `emcy` fault, like `clear emcy`. The device must still have 0x1014. `period_ms` with code 0 is refused in the file check and the control protocol ("emcy: code 0x0000 is the error reset; it takes no period_ms").

## Risks

- `co_dev_set_lss` changes the device's DeviceInfo in memory only. The EDS on disk and the plugin's own `LSS_Supported` warning for `lss.assign` stay as they are.
- The one-shot EMCY filter must not drop a later genuine error reset. It is armed only for the duration of the synchronous `co_emcy_clear()` call. If the EMCY inhibit time (0x1015) holds Lely's frame back, the filter stays armed until that frame goes out, and then disarms.
