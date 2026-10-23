# PLCopen XML for other PLCs

`canworks-bridge` runs the CAN networks and serves their values as Modbus TCP registers. OpenPLC gets its program side written by Save in the configurator. For other PLCs that import PLCopen XML (TC6 2.01), `canworks-deploy --export-plcopen` writes the same program side as one file, plus a small part per PLC that connects it to the bridge:

| PLC | `--for` | What connects the program to the bridge |
| --- | --- | --- |
| CODESYS-based tools | `codesys` | A script for CODESYS's script engine adds the Modbus TCP client devices and orders the task |
| truST | `trust` | `canworks_io.st` and an `io.toml` part for truST's `modbus-tcp` driver |
| Any other tool with PLCopen XML import | `generic` | The register map as CSV and the channels to set up by hand |

CODESYS here is a Modbus client of the bridge, and the bridge still runs the CAN networks. To let CODESYS run the CANopen master itself, use [the CODESYS target](codesys.md) instead.

## What the file holds

`canworks.xml` holds:

- **`canworks`**: one typed variable per value of the config (`canworks.dio_door_open`, `canworks.rtd_AI0_Input_PV`, named as in an OpenPLC project, each with its network, node, PDO and object, unit and scale as documentation), `canworks.ok`, `canworks.link` for the function blocks, and the channel arrays `canworks.in_w` and `canworks.out_w`.
- **`canworks_in` and `canworks_out`**: the copy programs. `canworks_in` turns the input registers into the typed values and sets `canworks.ok`. `canworks_out` turns the typed outputs into holding registers and writes the PLC link header last. They are the programs `--export-modbus-map OUT.st` writes.
- **The canworks library**: every block and function of [the library](plc-library.md), the mailbox blocks included. `--no-library` leaves it out, for a project that already has it. `canworks-deploy library --format plcopen --out DIR` writes the library alone as `canworks-library.xml`.

Your program uses `canworks.ok` and `canworks.<value>`, and gives the blocks `LINK := canworks.link`. It runs between `canworks_in` and `canworks_out` in the same task.

### Channel arrays

The file ends at one rule: **input register k is `canworks.in_w[k]`, holding register k is `canworks.out_w[k]`**. Each PLC's Modbus client fills `in_w` with function 4 (read input registers) and sends `out_w` with function 16 (write multiple registers), at the task's cycle or faster. The arrays run from register 0 to the highest register the map uses.

### The PLC link

The export needs the bridge's PLC link: `"plc_link": true` in the `bridge` object (an OpenPLC config has it already), then **Pack for Modbus**. The bridge then puts its map hash at input registers 0-1 and takes a header at holding registers 0-2. `canworks.ok` is TRUE only while the hash matches the one the programs were generated for and the bridge's counter moves, and the bridge applies outputs only while the header carries that hash. A program built for another map therefore leaves the outputs off. Export again after every config change. ([modbus-bridge.md](modbus-bridge.md#openplc-through-modbus) describes the header and the hash.)

## Export

```sh
canworks-deploy --config canworks.json --export-plcopen out --for codesys --bridge-host 192.168.10.5
canworks-deploy --config canworks.json --export-plcopen out --for trust --with-main
canworks-deploy --config canworks.json --export-plcopen out --for generic
```

- `--bridge-host` is the bridge's address as the PLC sees it. Without it, the export uses `listen` when that is a real address. For truST on the bridge's own Linux device a wildcard `listen` gives 127.0.0.1. CODESYS needs a real address.
- `--with-main` (truST, generic) adds an empty program `main` to the task between `canworks_in` and `canworks_out`.
- `--codesys-plc NAME` and `--codesys-ethernet NAME` (CODESYS) name the PLC device and the Ethernet adapter when the project has several.

Every folder has a `README.txt` with the next steps for that PLC. The bridge takes writes only from the addresses in `writers`, so the PLC's address must be one of them.

## CODESYS

The folder holds `canworks.xml`, `canworks-codesys-modbus.json` (the bridge's address, port and unit ID, the channels and the cycle), `import_canworks_modbus.py` and `import_canworks.py`.

1. Open the PLC project in CODESYS.
2. **Tools > Scripting > Execute Script File...**, pick `import_canworks_modbus.py`.
3. The script finds the PLC as [the CODESYS export](codesys.md) does, imports `canworks.xml` into its application (replacing what an earlier run imported), adds or reuses an Ethernet adapter, a Modbus TCP Master and under it a Modbus TCP Slave `canworks_bridge` with the bridge's address, port and unit ID, and puts `canworks_in` first and `canworks_out` last in the task that runs your program. It builds the project and writes `import_report.txt` next to itself. It does not save.
4. Do what the report lists as **by hand**: the slave's channels (one read and one write channel each, with function, cycle, offset, length and the `canworks.in_w`/`canworks.out_w` range to map), the Ethernet adapter's network interface, and the task calls when the application has several tasks.

Run the script again after a new export; it reuses the devices it added.

## truST

truST's PLCopen import drops AT addresses, so the located I/O image comes as its own file. Its `modbus-tcp` driver reads the whole `%I` image with one request and writes the whole `%Q` image with one request every cycle, at most 125 input and 123 holding registers. A map that needs more is refused for truST, with the way to trim it.

What works on truST:

| Works | How |
| --- | --- |
| The typed values, `canworks.ok`, the status block, live lists and the control word | Always, as on every PLC |
| `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE` | Through the bridge's SDO and control registers, without mailboxes |
| `CO_SDO_READ_BYTES`, `_STRING`, `_REAL` and their write blocks, `CAN_SEND`, `J1939_SEND`, `J1939_REQUEST` | With one request mailbox and nothing else of the mailboxes: `"mailboxes": {"requests": 1, "receive": false, "network_info": false, "cyclic_jobs": 0}`, then Pack for Modbus. The example config then needs 105 input and 88 holding registers. |
| `CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY`, `CAN_SEND_CYCLIC`, `CAN_BUS_INFO`, `J1939_ECU_INFO` | Not on truST: the receive mailbox alone is 120 registers, and the network info and cyclic job blocks don't fit next to the rest. They build, and end with `ERROR_ID` 22 (the config has no part of the mailboxes this block needs). |

1. Import the file into the project:
   ```sh
   trust-runtime plcopen import --input canworks.xml --project <project folder>
   ```
   (or in VS Code: **truST: Import PLCopen XML**).
2. Copy `canworks_io.st` into the project's `src` folder.
3. Replace the `[io]` tables of the project's `io.toml` with `io.toml.part`, and set `[resource] name` in `runtime.toml` to `canworks_res`, the imported resource.
4. Write your program into `main` (with `--with-main`), or add it to `canworks_task` in the imported configuration.
5. `trust-runtime build --project <project folder>`, then run it.

The task runs every fifth of the bridge's watchdog time (at least 10 ms). The driver writes the outputs every cycle, which keeps the bridge's watchdog fed. When the bridge stops answering, `canworks.ok` goes FALSE and the PLC keeps running (`on_error = "warn"`).

CI imports and builds the truST export, with the whole library, against a pinned truST release (`test/plcopen/fetch-trust.sh`).

## Other PLCs

`--for generic` writes standard TC6 without vendor parts: the values as a structure `canworks_values` with one global `canworks`, and a configuration with the task `canworks_task`. `canworks-modbus-map.csv` has every register, and `README.txt` lists the client channels to set up. Run `canworks_in` first and `canworks_out` last in the task that uses the values.

## Limits

- Each channel is one Modbus request, and a value never spans two channels, so a value is consistent; values in different channels may come from different bridge polls.
- The library's blocks are plain IEC 61131-3 ST with strict typing, so they build on truST, CODESYS and STruC++ alike.
- TwinCAT, importing PLCopen XML into canworks, and graphical languages are not supported.
