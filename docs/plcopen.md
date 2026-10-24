# PLCopen XML for other PLCs

`canworks-bridge` runs the CAN networks and serves their values as Modbus TCP registers. OpenPLC gets its program side written by Save in the configurator. For other PLCs that import PLCopen XML (TC6 2.01), `canworks-deploy --export-plcopen --for generic` writes the same program side as one file, plus the register map as CSV and the Modbus client channels to set up in the PLC. In the configurator it is the **Download** of an Other PLC [connection](configurator.md#connections) with format PLCopen XML on the Modbus bridge page, as a zip named `<config>-<connection>.zip`.

CODESYS is not a Modbus client of the bridge: `--for codesys` is refused. To build the networks into CODESYS, CODESYS runs the CANopen master itself as [the CODESYS target](codesys.md) (`canworks-deploy --codesys-import`).

## What the file holds

`canworks.xml` holds:

- **`canworks`**: one typed variable per value of the config (`canworks.dio_door_open`, `canworks.rtd_AI0_Input_PV`, named as in an OpenPLC project, each with its network, node, PDO and object, unit and scale as documentation), `canworks.ok`, `canworks.link` for the function blocks, and the channel arrays `canworks.in_w` and `canworks.out_w`.
- **`canworks_in` and `canworks_out`**: the copy programs. `canworks_in` turns the input registers into the typed values and sets `canworks.ok`. `canworks_out` turns the typed outputs into holding registers and writes the PLC link header last. They are the programs `--export-modbus-map OUT.st` writes.
- **The canworks library**: every block and function of [the library](plc-library.md), the mailbox blocks included. `--no-library` leaves it out, for a project that already has it. `canworks-deploy library --format plcopen --out DIR` writes the library alone as `canworks-library.xml`.

Your program uses `canworks.ok` and `canworks.<value>`, and gives the blocks `LINK := canworks.link`. It runs between `canworks_in` and `canworks_out` in the same task.

### Channel arrays

The file ends at one rule: **input register k is `canworks.in_w[k]`, holding register k is `canworks.out_w[k]`**. Each PLC's Modbus client fills `in_w` with function 4 (read input registers) and sends `out_w` with function 16 (write multiple registers), at the task's cycle or faster. The arrays run from register 0 to the highest register the map uses.

### The PLC link

The export needs the bridge's PLC link: `"plc_link": true` in the `bridge` object (an OpenPLC config has it already), then **Pack for Modbus**. The bridge then puts its map hash at input registers 0-1 and takes a header at holding registers 0-2. `canworks.ok` is TRUE only while the hash matches the one the programs were generated for and the bridge's counter moves, and the bridge applies outputs only while the header carries that hash. A program built for another map therefore leaves the outputs off. Export again after every config change. ([modbus-bridge.md](modbus-bridge.md#openplc) describes the header and the hash.)

## Export

```sh
canworks-deploy --config canworks.json --export-plcopen out --for generic --bridge-host 192.168.10.5 --with-main
```

- `--bridge-host` is the bridge's address as the PLC sees it. Without it, the export uses `listen` when that is a real address. A connection's **Bridge address the PLC uses** setting is this value.
- `--with-main` adds an empty program `main` to the task between `canworks_in` and `canworks_out`.

The folder's `README.txt` has the next steps. The bridge takes writes only from the addresses in `writers`, so the PLC's address must be one of them.

## The file's form

`--for generic` writes standard TC6 2.01 (namespace `tc6_0201`) without vendor parts: the values as a structure `canworks_values` with one resource global `canworks`, which `canworks_in`, `canworks_out` and `main` declare as `VAR_EXTERNAL`, as strict IEC importers want, and a configuration with the task `canworks_task`, which runs every fifth of the bridge's watchdog time (at least 10 ms). `canworks-modbus-map.csv` has every register, and `README.txt` lists the client channels to set up. Run `canworks_in` first and `canworks_out` last in the task that uses the values.

## Limits

- Each channel is one Modbus request, and a value never spans two channels, so a value is consistent; values in different channels may come from different bridge polls.
- The library's blocks are plain IEC 61131-3 ST with strict typing, so they build on CODESYS, STruC++ and other strict compilers alike.
- TwinCAT, importing PLCopen XML into canworks, and graphical languages are not supported.
