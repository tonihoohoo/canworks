# NMT from the PLC program: start, stop and command the network

The `canworks` library (the same one as the [SDO blocks](plc-sdo.md)) gives the PLC program four function blocks for the NMT side of CANopen: command any node or every node, start and stop the network, and read the NMT state the master sees. With [several networks](config.md#several-networks-schema_version-2) the `NETWORK` input picks the network; only CANopen master networks can be used.

| Block | Inputs (besides `EXECUTE`, `NETWORK`) | Outputs (besides `BUSY`, `DONE`, `ERROR`, `ERROR_ID`) | For |
|---|---|---|---|
| `CO_NMT` | `NODE : USINT` (0 every node, 1..127), `COMMAND : USINT` | | stop, pre-operational, start or reset a node, chosen at run time, configured or not |
| `CO_NETWORK_START` | `TIMEOUT : TIME` (`T#0s` no limit) | | start the master and so the PDO exchange (`master.start: false`) |
| `CO_NETWORK_STOP` | `NODE_COMMAND : USINT` | | stop the PDO exchange: master pre-operational, nodes as `NODE_COMMAND` says |
| `CO_GET_STATE` | `NODE : USINT` (0 the master only) | `STATE`, `MASTER_STATE`, `HELD`, `BOOT_ERROR : USINT`, `CONFIGURED`, `STARTED : BOOL` | the NMT state of a node and of the master |

Install and enable the library as [plc-sdo.md](plc-sdo.md#install-the-library-once) describes. The blocks need a canworks plugin from the same release or later; an older plugin has no NMT entry point, so the NMT blocks end with `ERROR_ID` 4 while the SDO blocks keep working.

The node's `nmt_command_location` byte ([config.md](config.md#nmt-commands-from-the-program)) stays: it needs no code, but it is fixed in the config, one byte per configured node. The blocks pick the node at run time, reach nodes the config does not list and every node at once, and start and stop the master itself.

## Handshake

The blocks follow the SDO blocks' handshake: a rising edge on `EXECUTE` starts one request with the inputs of that call; `BUSY` is TRUE until it ends; then `DONE` or `ERROR` is TRUE for as long as `EXECUTE` stays TRUE, or for one call if it is already FALSE. Input changes and further edges while `BUSY` are ignored. Call the instance every scan while it is busy; the scan never waits, the request runs on the bus thread within 10 ms.

`CO_GET_STATE` answers in the call with the rising edge and is never `BUSY`. To refresh it continuously, call it with `EXECUTE := NOT gs.DONE` (a new reading every second call), or read the configured `state_location` bytes, which change every scan.

## CO_NMT

`COMMAND` takes the CiA 301 command codes, the same as the command byte:

| `COMMAND` | Configured node | Node the config does not list |
|---|---|---|
| 1 START | Releases the node's hold and starts it (a node that has not booted yet is started when its boot ends) | NMT START is sent |
| 2 STOP | Holds the node STOPPED: NMT STOP now, and again after every boot of the node | NMT STOP is sent |
| 128 ENTER PRE-OPERATIONAL | Holds the node PRE-OPERATIONAL, likewise | sent |
| 129 RESET NODE | Clears the hold; the node reboots and the master configures and starts it again | sent |
| 130 RESET COMMUNICATION | The same with a communication reset | sent |

`DONE` means the command was sent (NMT commands are not confirmed) and the hold recorded; read the state the node reports afterwards with `CO_GET_STATE`. For a node the config does not list nothing is kept: the master does not boot, supervise or hold it, so the program owns that node's NMT state.

A held node is not rebooted by the master when it leaves OPERATIONAL, a node that starts by itself is sent the hold again, and a held node that is lost (heartbeat timeout) is still booted again by the retry loop, configured, and then held again. A held node's status bit is FALSE and it exchanges no PDOs; SDO access works in PRE-OPERATIONAL.

`NODE := 0` sends one NMT command to node ID 0, which every device on the bus acts on, also those the config does not list, and applies the bookkeeping above to every configured node. The master's own state does not change. A broadcast START is refused (`ERROR_ID` 9) while the gateway holds a node (below).

`NODE` above 127, `NODE` equal to the master's node ID, or a `COMMAND` not in the table ends with `ERROR_ID` 6 in the same call, and nothing is sent. Every command is logged with its node and "from the program (CO_NMT)".

One instance per command, each on its own edge:

```
VAR
  stop5, start5 : CO_NMT;
  reset_all : CO_NMT;
  valve_off, reset_request : BOOL;
END_VAR

stop5(EXECUTE := valve_off, NODE := 5, COMMAND := 2);        (* STOP, held *)
start5(EXECUTE := NOT valve_off, NODE := 5, COMMAND := 1);   (* START, hold released *)
reset_all(EXECUTE := reset_request, NODE := 0, COMMAND := 129);  (* RESET NODE to every node *)
```

## One hold per node

The command byte, `CO_NMT`, the online view's and `canworks-diag nmt` commands, and the Modbus control block's NMT commands all set the same hold of a configured node, and the command that acted last decides. The command byte acts only when its value changes: a program that holds node 5 with `CO_NMT` while its byte stays at 0 keeps the hold until a START releases it or the byte changes. Use one of the two per node.

Two holds the program cannot lift:

- The gateway's `on_upper_loss: "stop_nodes"` holds field nodes STOPPED while the upper master is lost; a START from `CO_NMT` to such a node ends with `ERROR_ID` 9 and sends nothing. The gateway starts the node when the upper master is back. STOP and ENTER PRE-OPERATIONAL replace the gateway's hold with the program's.
- A master STOPPED by `master.stop_all_nodes` after a mandatory node was lost (below).

## Mandatory nodes

A hold or a reset from the program is not a loss: a mandatory node held STOPPED keeps the master OPERATIONAL, and a mandatory node the program resets reboots alone, while the master stays OPERATIONAL and the other nodes keep running; `reset_all_nodes` and `stop_all_nodes` do not react. A mandatory node that is lost while it is held (no heartbeat) is a loss as always.

## Start the network from the program: CO_NETWORK_START

`CO_NETWORK_START` makes the master go OPERATIONAL as `master.start: true` does: at once when every mandatory node has booted, else as soon as the last one has. It is `BUSY` until the master is OPERATIONAL, then `DONE`. With a `TIMEOUT` other than `T#0s` it ends with `ERROR_ID` 2 when the master is not OPERATIONAL by then; the start stays requested, so the master still starts when the last mandatory node boots. With the master already OPERATIONAL it ends with `DONE` at once. The start lasts for the rest of the PLC run, also after the master resets itself with `reset_all_nodes`.

This makes `master.start: false` an autostart-off pattern: every PLC start begins with the master PRE-OPERATIONAL and the nodes booted and configured (and started, with `start_nodes`), but no PDO moves and every status bit stays FALSE until the program says so:

```
VAR
  net_start : CO_NETWORK_START;
  machine_ready : BOOL;
END_VAR

net_start(EXECUTE := machine_ready, TIMEOUT := T#5s);
IF net_start.ERROR THEN
  (* ERROR_ID 2: a mandatory node is still missing; the master starts when it boots *)
END_IF;
```

In the configurator: **Advanced master settings**, **Master goes operational** off, and **Copy as ST call** next to it copies this call.

A master STOPPED by `stop_all_nodes` after a mandatory node's loss is the configuration's safety reaction: `CO_NETWORK_START` ends with `ERROR_ID` 9, and the log says that the plugin must restart (stop and start the PLC).

## Stop the network from the program: CO_NETWORK_STOP

`CO_NETWORK_STOP` stops the PDO exchange: from the request on no output PDO is sent, the master goes PRE-OPERATIONAL, and every configured node that is up gets `NODE_COMMAND`:

| `NODE_COMMAND` | The nodes |
|---|---|
| 0 | what `master.on_plc_stop` says (`"preop"`, the default: ENTER PRE-OPERATIONAL; `"stop"`: STOP; `"keep"`: nothing) |
| 2 | STOP |
| 128 | ENTER PRE-OPERATIONAL |
| 255 | nothing: the nodes stay as they are, with their last outputs |

Any other value ends with `ERROR_ID` 6. The block ends with `DONE` once the master is PRE-OPERATIONAL and the commands are sent. Until `CO_NETWORK_START`, the master does not go OPERATIONAL by itself, also not with `master.start: true` or after it reset itself; it keeps supervising and booting nodes, and a node that boots meanwhile is configured and then sent the same command. SDO transfers (blocks, SDO variables, the online view) keep working to nodes that are not STOPPED. Nodes with a hold of their own keep it.

`CO_NETWORK_START` afterwards starts the master again and sends START to every booted node that the network stop held (not with `start_nodes: false`, and not to nodes with a hold of their own); their status bits come back as their PDOs flow.

The plugin holds the master PRE-OPERATIONAL itself: the master state byte, `CO_GET_STATE` and the status bits say PRE-OPERATIONAL, no PDO goes out and received PDOs no longer reach the inputs (they keep their last values). It does not put the CANopen stack's master into PRE-OPERATIONAL, because that would restart the network's whole start-up, with a communication reset of every node. So the master's own heartbeat, when it produces one, keeps saying OPERATIONAL.

A master STOPPED by `stop_all_nodes` is not changed: `CO_NETWORK_STOP` ends with `ERROR_ID` 9.

## CO_GET_STATE

Reads what the master last saw, from a snapshot the bus thread keeps; no `state_location` is needed:

| Output | Value |
|---|---|
| `STATE` | the node's NMT state with the state byte's codes: 5 OPERATIONAL, 127 PRE-OPERATIONAL, 4 STOPPED, 0 no contact. It follows heartbeats and node guarding, not the commands the master sent. |
| `MASTER_STATE` | the master's own state, with the same codes (the master state byte) |
| `HELD` | 0, or the command (2 STOP, 128 ENTER PRE-OPERATIONAL) the master keeps applying to the node, whoever set it; a network stop shows as its node command |
| `BOOT_ERROR` | the boot error byte's code (0, or the CiA 302 error status letter) |
| `CONFIGURED` | TRUE when the config lists the node; for a node it does not list `STATE`, `HELD` and `BOOT_ERROR` are 0 |
| `STARTED` | TRUE while the master may run: `master.start` true or `CO_NETWORK_START` in this run, and no `CO_NETWORK_STOP` since |

`NODE := 0` fills only `MASTER_STATE` and `STARTED`. `NODE` above 127 ends with `ERROR_ID` 6.

```
VAR
  gs : CO_GET_STATE;
END_VAR

gs(EXECUTE := NOT gs.DONE, NODE := 5);
IF gs.DONE AND gs.STATE <> 5 AND gs.HELD = 0 THEN
  (* node 5 is not running and nobody holds it *)
END_IF;
```

## PLC stop and restart

When the PLC stops, NMT requests waiting or in progress are dropped (their blocks end with `ERROR_ID` 8 on their next call), and `master.on_plc_stop` applies to every configured node that is up, whatever the program held. Holds, a program start and a program stop belong to the run: after the next PLC start the master starts by itself only with `master.start: true`, and every node is booted and started as the config says.

## Error IDs

The SDO blocks' numbering ([plc-sdo.md](plc-sdo.md#error-ids)), so one table covers both families:

| `ERROR_ID` | Meaning |
|---|---|
| 2 | `CO_NETWORK_START`: the master was not OPERATIONAL within `TIMEOUT` (the start stays requested) |
| 4 | CANopen is not running: no plugin, its configuration rejected, the PLC stopping, a plugin without the NMT entry point or with another NMT API version (the log names both), or the network's bus not up |
| 5 | More than 16 NMT requests in progress or waiting (they have their own slots: SDO transfers never delay them) |
| 6 | An input is invalid: `NODE` above 127 or the master's own node ID, an unknown `COMMAND` or `NODE_COMMAND`, a `NETWORK` that is not a CANopen master network |
| 8 | Cancelled: the PLC stopped or CANopen restarted during the request |
| 9 | Refused by a state the program does not own: a START to a node the gateway holds after the upper master was lost, or a master STOPPED by `stop_all_nodes` |

1, 3 and 7 are not used by these blocks.
