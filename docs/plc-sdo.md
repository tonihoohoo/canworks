# SDO from the PLC program: the `openplc_canopen` library

The `openplc_canopen` library gives the PLC program eight function blocks that read or write any object of any node over SDO while the network runs. They are for transfers the program decides on at run time: a recipe parameter, a device name to log, a calibration table. For an object the program reads or writes all the time, an [SDO variable](config.md#sdo-variables) in the config is simpler, since it needs no code. With [several networks](config.md#several-networks-schema_version-2) the blocks reach the first network in the config's list.

| Block | Data | For |
|---|---|---|
| `CO_SDO_READ` / `CO_SDO_WRITE` | `DATA : LWORD`, `SIZE` | integers and bit strings up to 8 bytes (BOOLEAN, INTEGERx, UNSIGNEDx) |
| `CO_SDO_READ_REAL` / `CO_SDO_WRITE_REAL` | `VALUE : LREAL` | REAL32 and REAL64 |
| `CO_SDO_READ_STRING` / `CO_SDO_WRITE_STRING` | `VALUE : STRING` | VISIBLE_STRING, up to 254 characters |
| `CO_SDO_READ_BYTES` / `CO_SDO_WRITE_BYTES` | `BUFFER : ARRAY[0..1023] OF BYTE`, `SIZE` | any object up to 1024 bytes (OCTET_STRING, DOMAIN, records) |

## Install the library once

The PC tools carry the library in the version that matches them. On the PC with OpenPLC Editor:

```sh
openplc-canopen-deploy library --install
```

installs it into the editor as its Library Manager does; restart the editor if it is open. Or write the file and add it in the editor's Library Manager with "install from file":

```sh
openplc-canopen-deploy library --out .      # writes openplc_canopen.stlib
```

Each `deploy-v` release also carries `openplc_canopen.stlib`. Then enable the library in the project (the editor's Library Manager, or `openplc-canopen-deploy library --project <project folder>`). A project made with `--new-project ... --sdo-blocks`, or with **Enable CANopen SDO blocks** in the configurator's New editor project dialog, has it enabled already, and the library is installed into the editor if it is missing or older.

The blocks need the CANopen plugin on the runtime from the same release or later. Without it, or while CANopen is off, they end with `ERROR_ID` 4.

## Using a block

Every block has the same handshake:

- Inputs: `EXECUTE : BOOL`, `NODE : USINT` (1..127), `INDEX : UINT`, `SUBINDEX : USINT`, `TIMEOUT : TIME` (`T#0s` means 1 s).
- Outputs: `BUSY`, `DONE`, `ERROR : BOOL`, `ERROR_ID : UINT`, `ABORT_CODE : UDINT`.
- A rising edge on `EXECUTE` starts one transfer. `BUSY` is TRUE until it ends; then `DONE` or `ERROR` is TRUE (and the data outputs are set) for as long as `EXECUTE` stays TRUE, or for one scan if it is already FALSE. Setting `EXECUTE` FALSE clears `DONE` and `ERROR`. A new rising edge while `BUSY` is ignored.
- Call the instance on every scan while it is busy. The scan never waits: the transfer runs on the bus thread.

The configurator writes the call for you: in the Online view's object dictionary tab, the **ST** button on an entry (or **Copy as ST call** under "Read or write any entry") copies a declaration and call of the matching block with the node, index and subindex filled in.

### Integers

```
VAR
  rd_vendor : CO_SDO_READ;
  wr_limit : CO_SDO_WRITE;
  vendor_id : UDINT;
  limit : INT := -200;
  go : BOOL;
END_VAR

rd_vendor(EXECUTE := go, NODE := 5, INDEX := 16#1018, SUBINDEX := 1);
IF rd_vendor.DONE THEN
  vendor_id := LWORD_TO_UDINT(rd_vendor.DATA);
END_IF;

wr_limit(EXECUTE := go, NODE := 5, INDEX := 16#6424, SUBINDEX := 1, DATA := INT_TO_LWORD(limit), SIZE := 0);
```

`CO_SDO_READ` puts the reply in the low bytes of `DATA` (the high bytes are 0) and its byte count in `SIZE`. The conversion to the object's own type gives a signed value back: an INTEGER16 of -200 arrives as `16#FF38`, and `LWORD_TO_INT` makes it -200 again. `CO_SDO_WRITE` sends the low `SIZE` bytes of `DATA`. `SIZE := 0` takes the size from the object's type in the node's EDS; for a node without an EDS in the config give the size (1, 2, 4 or 8).

### REAL

`CO_SDO_READ_REAL` reads a REAL32 or REAL64 object into `VALUE : LREAL` (by the reply's size). `CO_SDO_WRITE_REAL` writes `VALUE` as REAL32 (`SIZE := 4`) or REAL64 (`SIZE := 8`); `SIZE := 0` takes it from the EDS.

### Strings

```
rd_name(EXECUTE := go, NODE := 5, INDEX := 16#1008, SUBINDEX := 0);
IF rd_name.DONE THEN
  device_name := rd_name.VALUE;
END_IF;
```

A reply longer than 254 characters ends with `ERROR_ID` 7; read it with `CO_SDO_READ_BYTES`. `CO_SDO_WRITE_STRING` sends `VALUE` without a terminating zero.

### Bytes

`CO_SDO_READ_BYTES` copies the reply into `BUFFER` (an in-out `ARRAY[0..1023] OF BYTE`) and its length into `SIZE`. `CO_SDO_WRITE_BYTES` sends the first `SIZE` bytes of `BUFFER`. Use these for anything else: OCTET_STRING, DOMAIN, or a whole record read as bytes.

## Error IDs

| `ERROR_ID` | Meaning |
|---|---|
| 1 | The node aborted the transfer; `ABORT_CODE` holds its CiA 301 abort code (e.g. `16#06020000` object does not exist, `16#06010002` read-only) |
| 2 | Timeout: no answer within `TIMEOUT`, counted from when the node can be asked (`ABORT_CODE` = `16#05040000`) |
| 3 | The node is not available: configured, but lost or failed to boot |
| 4 | CANopen is not running (no plugin, no config, or CANopen switched off) |
| 5 | Too many transfers at once (64 across all blocks) |
| 6 | Invalid input: node outside 1..127, a `SIZE` the block cannot send, `SIZE := 0` without an EDS type |
| 7 | The data does not fit the block's output (a reply longer than 8 bytes for `CO_SDO_READ`, 254 characters for a string, 1024 bytes for bytes) |
| 8 | Cancelled: the PLC stopped or CANopen restarted during the transfer (the runtime log says how many transfers a stop cancelled), or the block did not collect its result within 10 s |

## How it shares the bus

- Transfers to one node run one at a time, in the order the blocks started them, taking turns with the node's [SDO variables](config.md#sdo-variables) so neither starves the other. Transfers to different nodes run at the same time.
- A transfer waits while its node boots, including the first boot after a PLC start, so a program can read at startup with the default `TIMEOUT`: the timeout starts once the node can be asked. If the node does not come up (about 3 s after a start, when the log says it is not answering), the transfer ends with error 3. A transfer to a node that is lost or failed to boot is refused at once (error 3). A node ID the config does not list is reached through the default SDO channel (0x600 + node / 0x580 + node).
- Writing an object the plugin configures at boot (PDO mapping and communication, heartbeat, startup SDOs) is allowed, but the next boot writes it back; the runtime log warns once per object.
- An abort is logged once per node, object and abort code. Nothing is ever saved to the device's non-volatile memory unless the program writes 0x1010 itself.
