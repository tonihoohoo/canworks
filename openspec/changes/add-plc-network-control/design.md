# Design

## Context

- The `canworks` library's SDO blocks reach the loaded plugin with `dlopen("libcanworks_plugin.so", RTLD_NOW | RTLD_NOLOAD)` and `dlsym(..., "canopen_plc_api")` (`library/src/common.inc`). The v1 table has `start` and `poll`; requests go into 64 fixed slots in `PlcRequests` (`plc_api.cpp`), each network takes its own in `Network::ServiceProgram` (`network_plc.cpp`) on the 10 ms request timer and runs them on the Lely loop. `PlcRequests::open(masters)` gets the bit set of CANopen master networks (`canopen_runtime.cpp`); `close()` at PLC stop drops every slot, so old handles end with `ERROR_ID` 8.
- NMT from the program today: `nmt_command_location` per configured node. `Network::ServiceRequests` reads the byte from the latest output snapshot (only after the first scan) and `ApplyNmtCommand` acts on a change: 0/1 release and START, 2/128 set `NodeState::hold` and `SendHold`, 129/130 `ResetNode` (clears the hold, reboots the node through the boot retry path).
- Other NMT sources use the same `hold`: the diagnostics channel and the Modbus control block go through `Network::OperatorNmt` (`hold_by_operator`, configured nodes only; node 0 from the control block means every configured node, one command each), the gateway's `on_upper_loss: "stop_nodes"` sets `hold_by_gateway` and leaves nodes held by anyone else alone.
- A held node is not rebooted when it leaves OPERATIONAL; a node that boots again (power cycle, loss and retry) is configured and then sent the hold again (`OnBooted` -> `SendHold`). `ResetNode` clears the hold.
- The master's own state comes from Lely's `OnCommand` (`HandleCommand` -> `SetMasterState`, `master_op_`). `StartHeldMaster` sends `Command(START, master node ID)` once every mandatory node has booted, because Lely gives up the network boot for good when a mandatory node failed once. A master STOPPED (by `stop_all_nodes`) is logged as "no PDOs are exchanged until the plugin restarts", and the supervision loop skips boot retries while it is STOPPED.
- `StopNodes` at PLC stop sends `master.on_plc_stop`'s command to every configured node that is up, with all master TPDOs off first.

### What starts a master with `start: false` today

Nothing. Checked in the code on main (2026-10-10):
- `Network::StartHeldMaster` returns at once when `cfg_.master.start` is false; it is the only place the plugin sends NMT START to the master's own node ID.
- `Network::OperatorNmt` (diagnostics `nmt` op and Modbus control block) acts only on entries of `nodes_`, the configured slaves; the diagnostics request parser refuses a node that is not in the configuration, and the master is not in `nodes_`. Node 0 from the control block loops over the configured slaves.
- The gateway's upper master starts and stops the PLC's own slave device, and its "stop nodes" reaction holds and releases lower slaves; it never commands the lower network's master.
- An NMT START frame sent onto the bus by hand (the Trace view's frame builder offers "NMT start all nodes") does not reach the master's state machine: Lely's NMT service in master mode does not act on NMT commands it receives. This is the expected Lely behaviour and is checked by a simulation test in this change (task 1.1), not assumed.

So with `start: false` the master configures and starts the nodes (with `start_nodes` true), but stays PRE-OPERATIONAL, every status bit stays FALSE and no PDO moves, until the PLC is restarted with another config. The docs' "until something starts it" and the configurator hint promise something that does not exist. This change supplies the "something" (`CO_NETWORK_START`) and fixes the wording.

## Goals / Non-Goals

**Goals:** NMT commands to any node or all nodes from the program, chosen at run time; start and stop of the network from the program, making `start: false` useful; NMT state of any node and of the master readable from the program; one clear rule for who wins when the program, the command byte, an operator and the master's own boot logic disagree; no effect on scan timing; nothing changes for configs and programs that do not use the blocks.

**Non-goals:** node guarding or heartbeat settings from the program; LSS from the program; changing `nmt_command_location` (it stays, unchanged in meaning); a program-driven "NMT flying master" or a second master; NMT on the PLC's own slave device (`role: slave` networks); EMCY from the program (that is `add-emcy-history`); persisting anything the program commanded across a PLC restart.

## Decisions

### 1. Four blocks, one handshake

| Block | Inputs besides `EXECUTE`, `NETWORK` | Outputs besides `BUSY`, `DONE`, `ERROR`, `ERROR_ID` |
|---|---|---|
| `CO_NMT` | `NODE : USINT` (0 all, 1-127), `COMMAND : USINT` (1, 2, 128, 129, 130) | none |
| `CO_NETWORK_START` | `TIMEOUT : TIME` (`T#0s` no limit) | none |
| `CO_NETWORK_STOP` | `NODE_COMMAND : USINT` (0 as `master.on_plc_stop`, 2 STOP, 128 PRE-OPERATIONAL, 255 none) | none |
| `CO_GET_STATE` | `NODE : USINT` (0 the master only, 1-127) | `STATE`, `MASTER_STATE`, `HELD`, `BOOT_ERROR : USINT`, `CONFIGURED`, `STARTED : BOOL` |

The handshake is the SDO blocks' (`co_sdo::begin`): a rising edge latches the inputs and starts, `BUSY` until it ends, then exactly one of `DONE`/`ERROR`, held while `EXECUTE` stays TRUE, shown for one call when it was already FALSE. `ABORT_CODE` is left out: no SDO is involved.

`COMMAND` uses the CiA 301 command specifiers, the same codes `nmt_command_location` takes, so a program that moves from the byte to the block keeps its constants. Separate start/stop blocks for the master (instead of a mode on `CO_NMT`, or `CO_NMT` with the master's own node ID) keep `CO_NMT` one thing ("command a slave") and make the master start visible in the program's text; `CO_NMT` with `NODE` equal to the master's node ID is refused with `ERROR_ID` 6.

`CO_GET_STATE` answers in the call with the rising edge (never `BUSY`), so a program refreshes it with `EXECUTE := NOT gs.DONE` (every second call) or reads the configured `state_location` bytes for a value on every scan. See open question 1 for an `ENABLE` variant.

### 2. Own entry point, same request path

`extern "C" const void* canopen_plc_nmt_api(uint32_t version)` in a new `canopen_plc_nmt_api.h`, v1:

```c
typedef struct {
  uint8_t network;    /* as canopen_plc_request */
  uint8_t node;       /* 0 all (CO_NMT), 1..127 */
  uint8_t op;         /* 1 node command, 2 network start, 3 network stop */
  uint8_t command;    /* op 1: CiA 301 cs; op 3: 0, 2, 128 or 255 */
  uint32_t timeout_ms;/* op 2: 0 = no limit */
} canopen_plc_nmt_request;

typedef struct {
  uint8_t state, master_state, held, boot_error;
  uint8_t configured, started;
} canopen_plc_nmt_state;

typedef struct {
  uint32_t size;
  uint32_t (*start)(const canopen_plc_nmt_request* req, uint16_t* error_id);
  int (*poll)(uint32_t handle, uint16_t* error_id);              /* 0 busy, 1 done, 2 error */
  uint16_t (*get_state)(uint8_t network, uint8_t node, canopen_plc_nmt_state* out); /* ERROR_ID */
} canopen_plc_nmt_api_v1;
```

Why not grow `canopen_plc_api` v1 (its `size` field allows appending) or add request kinds to it: the parallel `add-emcy-history` change may also grow the plugin API, and two changes appending to one table need a merge order; an older plugin would answer a new kind with `ERROR_ID` 6, which misleads. A second entry point is found the same way (`dlsym` on the same handle), is missing on an older plugin (the NMT blocks end with `ERROR_ID` 4 and look again on their next edge, the SDO blocks are unaffected), and its version moves on its own. The plugin logs once when a block asks for an NMT API version it does not offer, as it does for the SDO table.

Requests go into a second slot table in `PlcRequests`: 16 NMT slots, same mutex, same handle layout (slot index and generation), same `open`/`close` (so a PLC stop or CANopen restart ends them with `ERROR_ID` 8), validated against the same master network bit set. A separate table keeps 64 queued SDO transfers from starving a STOP and keeps NMT slots tiny (no 1024-byte buffer). `Network::ServiceProgram` takes the network's NMT requests (`take_nmt`) before its SDO requests on each request tick and runs them on the bus thread; nothing on the scan path allocates, waits or logs.

`get_state` does not use a slot: the bus thread keeps a per-network snapshot (128 node entries plus the master entry, `std::atomic<uint32_t>` each, packing state, held, boot error and flags) in `PlcRequests`, written from `SetState`, `SetMasterState`, `SetBootError` and every hold change; the scan thread reads one atomic. Cleared at `open`/`close`.

The library side: `library/src/nmt_common.inc`, copied into the four blocks by `library/generate.py` after `common.inc` (whose include guard keeps one copy of the lookup and handshake helpers), with the same pin-name rules (lower-case identifiers only, no system header after the pin `#define`s).

### 3. `CO_NMT`: commands and holds

On the bus thread a node command runs through one function shared with `OperatorNmt`, with the source "the program (CO_NMT)" in the log:
- configured node, STOP or ENTER PRE-OPERATIONAL: set `hold` (Stopped or Preop), clear `hold_by_operator`, `SendHold` (or, if the node has not booted, apply it when it has). Exactly what the command byte's 2 and 128 do: the master keeps the hold after every boot, does not reboot the node when it leaves OPERATIONAL, and sends the hold again to a node that starts by itself.
- configured node, START: clear the hold; START now if the node is booted or has `boot: false`, else the master starts it when its boot ends.
- configured node, RESET NODE / RESET COMMUNICATION: `ResetNode` (clears the hold, reboots and reconfigures the node).
- node the config does not list: the command is sent and nothing is kept: no hold, no boot, no state tracking. The program owns that node's NMT state.
- `NODE := 0`: one CiA 301 broadcast (node ID 0) on the bus, so unlisted nodes get it too, and the per-node bookkeeping above for every configured node (holds set or cleared, resets scheduled). The master's own state does not change; see open question 2 for how the broadcast is sent without Lely applying it to the master.

`DONE` means the command was sent (NMT is unconfirmed) and the hold recorded; the state the node reports afterwards is read with `CO_GET_STATE`. A command that cannot be applied ends with an error and sends nothing: `NODE` above 127 or equal to the master's ID, an unknown `COMMAND`, a `NETWORK` that is not a master network (6); START to a node held by the gateway's upper-loss reaction (9: the gateway releases it when the upper master is back).

**One hold, last command wins.** The command byte, `CO_NMT`, the online view and the Modbus control block write the same `hold`. The byte keeps acting only on a change of its value (as today), so a program that sets a hold with `CO_NMT` while the byte sits at 0 keeps the hold until something releases it, and a later change of the byte overrides it. The docs say: use one of the two per node.

**Boot and retry logic.** Unchanged by a hold: a held node that is lost (heartbeat timeout) is booted again by the retry loop, configured, then held again; so a STOP from the program does not stop the master from re-booting a node that went away, but it does stop the master from starting it. A node the program reset boots as usual.

**Mandatory nodes.** A hold or reset from the program is not a loss: a mandatory node held STOPPED keeps the master OPERATIONAL, and resetting it does not trigger `reset_all_nodes` or `stop_all_nodes`. While it reboots after the program's reset, the master stays OPERATIONAL (the network is not held again). Open question 3 is whether Lely reports the expected boot-up after a reset as an error control event for a mandatory node; the simulation test pins it, and the plugin ignores that event when it follows its own reset.

### 4. `CO_NETWORK_START` and `CO_NETWORK_STOP`

Two network-level flags in `Network`: `prog_start_` (the program asked for a start this run) and `prog_stopped_` (the program stopped the network).

- `StartHeldMaster`'s gate becomes `(cfg_.master.start || prog_start_) && !prog_stopped_`. `CO_NETWORK_START` sets `prog_start_`, clears `prog_stopped_`, and calls `StartHeldMaster`: the master goes OPERATIONAL now, or as soon as every mandatory node has booted. The block is `BUSY` until the master is OPERATIONAL, then `DONE`; after `TIMEOUT` (if not `T#0s`) it ends with `ERROR_ID` 2 and the start stays requested, so the master still starts when the last mandatory node boots. With the master already OPERATIONAL it ends `DONE` at once.
- Nodes held by `CO_NETWORK_STOP` are started again on `CO_NETWORK_START` (START to each booted node the network stop held, unless it has its own hold or `start_nodes` is false), and the nodes' status bits come back as their PDOs flow.
- `CO_NETWORK_STOP` sets `prog_stopped_`, turns the master TPDOs off as `StopNodes` does (so no output goes out between the request and the node commands), sends `Command(ENTER_PREOP, master node ID)`, then sends every configured node that is up the `NODE_COMMAND` (0: `master.on_plc_stop`'s choice; 255: none, the nodes keep their last outputs). Nodes that boot while the network is stopped are configured and then sent the same command, as a hold is; boot retries and supervision keep running so a start is quick. PRE-OPERATIONAL and not STOPPED: STOPPED would end SDO access and boot retries (the supervision loop skips them while the master is STOPPED), and today nothing brings a STOPPED master back.
- A master STOPPED by `stop_all_nodes` after a mandatory loss is the config's safety reaction: `CO_NETWORK_START` ends with `ERROR_ID` 9 and the log says the plugin must restart (open question 4).
- With `reset_all_nodes` the master resets itself after a mandatory loss; `prog_start_` and `prog_stopped_` live in `Network` and survive that, so a network the program started is started again after the reset, and one it stopped stays stopped.

**Autostart-off pattern:** `master.start: false` plus one `CO_NETWORK_START` in the program when the machine is ready. Every PLC start begins with the master PRE-OPERATIONAL and the nodes configured; the program decides when PDOs flow.

### 5. PLC stop and restart

At PLC stop the slots close (blocks that were `BUSY` end with `ERROR_ID` 8 on their next call), and `StopNodes` sends `master.on_plc_stop`'s command to every configured node that is up, whatever the program held, as today for the command byte. `prog_start_`, `prog_stopped_`, the holds and the snapshot belong to the run: the next PLC start builds a new `Network`, so the master starts by itself only with `start: true`, and every node boots and starts as the config says.

### 6. `CO_GET_STATE`

`STATE` uses the state byte's codes (5 OPERATIONAL, 127 PRE-OPERATIONAL, 4 STOPPED, 0 no contact) and is what the master last saw, so it follows heartbeats and guarding, not commands it sent. `MASTER_STATE` the master state byte's codes. `HELD` 0, 2 or 128: the hold the master keeps applying, whoever set it (a network stop shows as the network's node command). `BOOT_ERROR` the boot error byte's code. `CONFIGURED` FALSE for a node the config does not list: its `STATE` is then 0 (open question 5). `STARTED` TRUE while the master is allowed to run (`start` true or `CO_NETWORK_START` this run, and no `CO_NETWORK_STOP` after it). `NODE := 0` fills only the master fields.

### 7. Error IDs

The SDO numbering, so one table in the docs covers both families: 2 `CO_NETWORK_START` timeout; 4 CANopen not running, no plugin, or a plugin without the NMT entry point; 5 more than 16 NMT commands waiting; 6 invalid input; 8 cancelled by a PLC stop or CANopen restart. New: 9 refused by a higher-level state (a node held by the gateway's upper-loss reaction, a master STOPPED by `stop_all_nodes`). 1, 3 and 7 are not used by these blocks.

### 8. Configurator

The online view's NMT buttons (start, stop, pre-operational, reset node, reset communication) get "Copy as ST call", which copies a `CO_NMT` declaration and call for that node and command (with `NETWORK` and the network's name in the instance name when there are several networks, as the SDO calls do). The advanced master setting "Master goes operational" gets the corrected hint ("Off: the master stays pre-operational until the PLC program starts it with CO_NETWORK_START") and a "Copy as ST call" link for a `CO_NETWORK_START` call. No new config field.

### 9. Independence from `add-emcy-history`

That change adds `CO_RECV_EMCY` to the same library. This one does not touch `canopen_plc_api` v1, `common.inc` or the library delivery requirement; it adds its own header, entry point, include file and spec. Shared files where both add lines: `library/generate.py` (one entry each in its block list), the committed `.stlib` (rebuilt by whichever lands second), the README and `docs/plc-sdo.md` block lists. No merge order is needed.

## Risks / Trade-offs

- [Program and command byte fight over a node] -> last command wins, logged with its source each time; docs recommend one of the two per node.
- [A program stops the network and forgets to start it] -> the log names the program as the reason the network is held; `CO_GET_STATE.STARTED` and the master state byte show it; a PLC restart clears it.
- [NMT broadcast reaches devices the config does not know] -> intended (CiA 301 node 0); documented, and the online view's confirmation for broadcasts stays a configurator matter.
- [Commands to unconfigured nodes collide with another master] -> same as the diagnostics channel's foreign SDO: the program owns that choice; the log names each command.
- [Lely behaviour differs from what decisions 3 and 4 assume (broadcast, mandatory boot-up, received NMT)] -> task 1 tests each in simulation before the plugin side is built, and design.md is updated with the result.

## Open Questions

1. Should `CO_GET_STATE` take `ENABLE` (level, outputs refreshed every call while TRUE, a `VALID` output) instead of `EXECUTE`, as PLCopen read blocks do? `EXECUTE` keeps one handshake across the library; `ENABLE` is easier for a continuous display. Proposed: `EXECUTE` now, revisit after the bench check.
2. How to send the NMT broadcast without changing the master's own state: Lely's `Command(cs, 0)` may also apply the command to the master. If it does, send the broadcast frame through the bus's raw send path and do the per-node bookkeeping by hand. Task 1.2 decides.
3. Does Lely treat the boot-up of a mandatory node after the program's RESET NODE as a loss (triggering `reset_all_nodes`/`stop_all_nodes`)? If it does, the plugin must mark the reset as expected and suppress that reaction.
4. May `CO_NETWORK_START` lift a master STOPPED by `stop_all_nodes`? Proposed no (error 9), since that is the config's safety reaction; a use case for allowing it would need its own option.
5. Should the plugin track the NMT state of unlisted nodes from their heartbeat or boot-up frames (the bus monitor already sees every frame), so `CO_GET_STATE` reports them? Proposed: not in this change; `CONFIGURED` FALSE and `STATE` 0.
6. Should `CO_NMT` offer an optional wait until the node reports the commanded state (a `CONFIRM` input with `TIMEOUT`)? Proposed: no; `CO_GET_STATE` covers it.
