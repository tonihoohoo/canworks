# The `canworks` function block library

`canworks` is one OpenPLC Editor library with the function blocks and functions a PLC program uses to work with the networks canworks-bridge runs for it ([OpenPLC through Modbus](modbus-bridge.md#openplc-through-modbus)). The blocks talk to the bridge through the registers the generated `canworks_in` and `canworks_out` programs copy every scan, so they need nothing inside the runtime and never make the scan wait. The library's version is the PC tools' version.

## What it holds

| Family | Blocks | Functions | Reference |
|---|---|---|---|
| CANopen over the bridge | `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` | | [below](#blocks-over-the-bridge), [plc-sdo.md](plc-sdo.md), [plc-nmt.md](plc-nmt.md) |
| Bit-exact REAL conversions | | `CW_DWORD_TO_REAL`, `CW_REAL_TO_DWORD`, `CW_LWORD_TO_LREAL`, `CW_LREAL_TO_LWORD` | [below](#real-conversions) |
| CiA 402 cyclic modes | `CO402_CyclicPosition`, `CO402_CyclicVelocity`, `CO402_CyclicTorque`, `CO402_CyclicMoveAbsolute` | | [cia402.md](cia402.md#cyclic-synchronous-modes) (only with the plugin; leaving with it) |
| CAN frame helpers | | `CAN_GET_BITS`, `CAN_SET_BITS`, `CAN_GET_UINT16`, `CAN_SET_UINT16`, `CAN_GET_UINT32`, `CAN_SET_UINT32`, `CAN_J1939_ID`, `CAN_J1939_PGN`, `CAN_J1939_SOURCE` | [raw-can.md](raw-can.md#frame-blocks) |
| J1939 helpers | `J1939_NAME_SPLIT`, `J1939_DTC_SPLIT` | `J1939_GET_BITS`, `J1939_SET_BITS`, `J1939_NAME_MAKE`, `J1939_DTC_MAKE` | [j1939.md](j1939.md#program-blocks) |

`canworks-deploy library --list` prints every block and function of the installed tools' library.

The blocks that called into the OpenPLC plugin (the SDO `_REAL`, `_STRING` and `_BYTES` variants, `CO_RECV_EMCY`, `CO_NETWORK_START`, `CO_NETWORK_STOP`, `CO_GET_STATE`, the CAN frame and J1939 message and trouble code blocks) are no longer in the library: OpenPLC reaches canworks only through Modbus. SDOs of up to 4 bytes and NMT commands work over the bridge now; longer SDOs, raw CAN, J1939 and EMCY blocks need mailboxes in the bridge that are still to come.

## Install and enable

The PC tools carry the library in the version that matches them. On the PC with OpenPLC Editor:

```sh
canworks-deploy library --install
```

installs it into the editor as its Library Manager does; restart the editor if it is open. Or write the file and add it in the editor's Library Manager with "install from file":

```sh
canworks-deploy library --out .      # writes canworks.stlib
```

Each `deploy-v` release also carries `canworks.stlib`. Then enable the library in the project (the editor's Library Manager, or `canworks-deploy library --project <project folder>`). A project made with **Enable the canworks function blocks** in the configurator's New editor project dialog has it enabled already, and the library is installed into the editor if it is missing or older.

## Blocks over the bridge

Every block takes `LINK`, the generated `canworks.link`, as its in-out, and `NETWORK : USINT`, the network's place in the config's `networks` list counting from 0:

```iecst
read_vendor(EXECUTE := start, NETWORK := 0, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := canworks.link);
IF read_vendor.DONE THEN vendor := read_vendor.DATA; END_IF;
```

| Block | Inputs | Outputs |
|---|---|---|
| `CO_SDO_READ` | `EXECUTE`, `NETWORK`, `NODE`, `INDEX : UINT`, `SUBINDEX : USINT`, `TIMEOUT : TIME` | `BUSY`, `DONE`, `ERROR`, `ERROR_ID : UINT`, `ABORT_CODE : UDINT`, `DATA : UDINT` |
| `CO_SDO_WRITE` | the same and `DATA : UDINT`, `SIZE : USINT` (1-4 bytes) | `BUSY`, `DONE`, `ERROR`, `ERROR_ID`, `ABORT_CODE` |
| `CO_NMT` | `EXECUTE`, `NETWORK`, `NODE` (0: every node), `COMMAND : USINT` (1 start, 2 stop, 128 pre-operational, 129 reset node, 130 reset communication), `TIMEOUT` | `BUSY`, `DONE`, `ERROR`, `ERROR_ID` |
| `CO_NODE_LIVE` | `NETWORK`, `NODE` | `LIVE : BOOL` (the node is OPERATIONAL) |

A rising edge of `EXECUTE` starts one job with the inputs of that call. `BUSY` is TRUE until it ends; then `DONE` or `ERROR` is TRUE for as long as `EXECUTE` stays TRUE, or for one call if it is already FALSE. Call the instance every scan while it is busy. `TIMEOUT` T#0s means 5 s.

The bridge has one SDO request block and one control block, so instances take turns: an instance that finds them in use stays `BUSY` until the one before it ends, in the order they started. The config needs the bridge's SDO registers (with `sdo_bridge_write` for writes), control block and a live list per network the blocks use; the configurator sets them up when a config switches to OpenPLC.

| `ERROR_ID` | Meaning |
|---|---|
| 1 | The node aborted the SDO transfer; `ABORT_CODE` says why. |
| 2 | No answer within `TIMEOUT`. |
| 5 | NMT refused: the network's bus is down, or 16 of its commands still wait. |
| 6 | An input is out of range (node, size, command). |
| 20 | The bridge is not reachable: `canworks.ok` is FALSE at the start or during the job. |
| 21 | SDO writes are not allowed by the config (`ABORT_CODE` 16#08000020). |
| 22 | The config has no SDO registers or no control block for this block. |

## REAL conversions

`canworks_in` and `canworks_out` move REAL and LREAL values as their bit patterns. `CW_DWORD_TO_REAL(16#3FC00000)` is 1.5 and `CW_REAL_TO_DWORD(1.5)` is 16#3FC00000; the LWORD pair does the same for LREAL. Unlike `DWORD_TO_REAL`, which converts the number, they keep every bit, including infinities, NaN and subnormal values, and are written in ST, so they work on any IEC 61131-3 runtime.

## Building it

The sources are in `library/modbus/` (the blocks over the bridge and the REAL conversions) and `library/canworks/` (the ST helpers); `library/build.sh` builds `canworks.stlib` into the deploy package with STruC++, and `test/plc_modbus/run.sh` runs the blocks and the generated programs against a model of the bridge's registers ([development.md](development.md)).
