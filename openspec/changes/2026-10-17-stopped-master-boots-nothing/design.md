# Design: stopped-master-boots-nothing

## Decision: the stopped master does not run Lely's slave boot

Lely boots every slave whose 0x1F81 bit 2 (boot) is set: at its own start-up, on each boot-up message, and again after a failed boot (error status B, about once a second). The plugin's `ScheduleRetry` already does nothing while the master is STOPPED, but Lely's own boot is not under the plugin's control.

The plugin clears bit 2 of each slave's 0x1F81 entry in the master's object dictionary in `OnCommand`, which Lely calls synchronously with the master's lock held (so it uses the C API, `co_sub_set_val_u32`, not `Device::Write`):
- on the master's STOP, and
- on a reset (communication or node) while the stop holds. A reset restores 0x1F81 from the DCF just before `OnCommand(RESET_COMM)`, and Lely's start-up runs right after it. The first boot of a mandatory slave runs inside `Reset()` itself, so clearing the bit after `Reset()` returns would be too late.

Lely reads 0x1F81 again for every boot attempt (`co_nmt_boot_wait_on_time`). Without bit 2 it skips the boot and only starts error control, sends no START (`co_nmt_boot_con` needs bits 0 and 2), and never retries with status B. Heartbeat consumption stays on, so heartbeats keep the node states up to date. When the master leaves STOPPED on an explicit command (no relapse), `OnCommand` puts the cleared entries back. The next PLC start restores them from the DCF anyway.

`HandleBoot` while the stop holds is only that error-control start after a boot-up. The node is not configured, nothing is read from it, it gets NMT STOP and it reads STOPPED. The plugin's own `ScheduleRetry` does nothing while the stop holds.

The send hook allow list from stopped-master-stays-silent stays as it is. SDO requests still pass, so the program's and the diagnostics channel's SDO keep working. A STOPPED node does not answer them, as CiA 301 says.

## Node state and boot error

When the plugin sends NMT STOP to every node (`Command(STOP, 0)` in `Start`, and the STOP after a boot-up), it sets each configured node's state to STOPPED. A later heartbeat or boot-up from the node replaces it, as the "Node states follow the real NMT state" rule asks. The state the master last saw is then the state it commanded.

The `OnTick` absent check (`kAbsentAfter`) skips nodes while the stop holds: no boot error B and no "not answering" log. One info line per session replaces it: "the master is STOPPED after a mandatory node was lost (master.stop_all_nodes): it boots no node until the plugin restarts". The mandatory-node message about PRE-OPERATIONAL is logged only when the master is not stopped. A node that sends no heartbeat at all stays at the STOPPED the master commanded. Its status bit is FALSE, as is every node's while the master is STOPPED.

## Simulated power state across sessions

The simulated bus builds its devices per session. The power state (off through `power off`, a fault or a scenario) moves into the run's state (`RunState::sim_powered_off`, by device store key), which the bus passes to each session's simulator (`SimOptions::powered_off`). The stored values live longer, for the life of the runtime, but power state must not survive a PLC restart. A device that was off when the session ended is created powered off. `power on`, `clear` or a scenario step powers it on, and a PLC restart starts it powered on. The real-device guard ("taken by a real device") stays per session.

## Not changed

- `reset_all_nodes`, and `CO_NETWORK_STOP` (it keeps Lely's master OPERATIONAL and holds it in the plugin): those masters boot nodes as before. A master that leaves STOPPED on a command boots nodes again (`OnCommand` puts bit 2 back).
