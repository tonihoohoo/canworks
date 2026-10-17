# Design: stopped-master-boots-nothing

## Decision: the stopped master does not run Lely's slave boot

Lely boots every slave whose 0x1F81 bit 2 (boot) is set: at its own start-up, on each boot-up message, and again after a failed boot (error status B, about once a second). The plugin's `ScheduleRetry` already does nothing while the master is STOPPED, but Lely's own boot is not under the plugin's control.

In `Start`, when `run_->master_stopped` is set, the plugin clears bit 2 of each slave's 0x1F81 entry in the master's object dictionary after `Reset()`. That is before Lely's asynchronous start-up reads it, so Lely starts no boot and schedules no retry. Error control (the 0x1016 heartbeat consumer) stays on, so heartbeats keep the node states up to date. The entries come back from the DCF at the next PLC start, the only thing that lifts the stop.

To check during apply: Lely must read 0x1F81 at start-up and on boot-up, not cache it at `Reset()`. If it caches it, the fallback is to cancel the boot right after Lely starts it (the `BasicMaster` boot cancel, or a `co_nmt_boot` abort) and to drop the boot SDO in the send hook. The fallback is a second path, so the 0x1F81 route is preferred.

The send hook allow list from stopped-master-stays-silent stays as it is. SDO requests still pass, so the program's and the diagnostics channel's SDO keep working. A STOPPED node does not answer them, as CiA 301 says.

## Node state and boot error

When the plugin sends NMT STOP to every node (`Command(STOP, 0)` in `Start`, and the STOP after a boot-up), it sets each configured node's state to STOPPED. A later heartbeat or boot-up from the node replaces it, as the "Node states follow the real NMT state" rule asks. The state the master last saw is then the state it commanded.

The `OnTick` absent check (`kAbsentAfter`) skips nodes while the stop holds: no boot error B and no "not answering" log. One info line per session replaces it: "the master is STOPPED after a mandatory node was lost (master.stop_all_nodes): it boots no node until the plugin restarts". The mandatory-node message about PRE-OPERATIONAL is logged only when the master is not stopped. A node that sends no heartbeat at all stays at the STOPPED the master commanded. Its status bit is FALSE, as is every node's while the master is STOPPED.

## Simulated power state across sessions

The simulated bus builds its devices per session. The power state (off through `power off`, a fault or a scenario) moves into the per-run state the plugin already keeps for stored values. A device that was off when the session ended is created powered off. `power on`, `clear` or a scenario step powers it on, and a PLC restart starts it powered on. The real-device guard ("taken by a real device") stays per session.

## Not changed

- `reset_all_nodes`, and a master stopped by `CO_NETWORK_STOP`, an operator command or the gateway: those masters boot nodes as before.
