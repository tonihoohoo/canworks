# Design: stopped-master-stays-silent

## Decision: filter at the send hook

Lely's master runs its whole start-up after the reset in `Start`: its boot-up, a reset of every node, the slave boots, and its own START once the mandatory nodes are back. Each of these could be suppressed one by one, but a new Lely path would open the gap again. The plugin already filters NMT START at the send hook (no-start-for-held-nodes). The stopped-master filter sits in front of it and works on an allow list: NMT STOP (`000#02..`), the master's heartbeat (0x700 + ID) and EMCY (0x80 + ID), SDO requests (0x601-0x67F) and LSS (0x7E5). Everything else, including 29-bit and RTR frames, is dropped. A STOPPED node answers no SDO, so Lely's boot of a node times out and reports its error. That is what a STOPPED network shows.

The filter and the re-STOP apply while the master is STOPPED, and after a reset of the stopped master: a new session's `Start` after the stop, or Lely resetting it from STOPPED. A master that left STOPPED on an explicit command first is not held by them (the existing SYNC and TIME tests).

The plugin's state follows too. A START or pre-operational entry that Lely reports while the stop holds is answered with STOP to the master. `master_op_` is false while the stop holds, so no TPDO is switched on in between.

## Not changed

- The simulated device that was powered off powers on again in a new session, because the simulator is built per session. A powered-off fault therefore does not survive a link bounce. This is noted for a later change, since the master's behaviour does not depend on it.
