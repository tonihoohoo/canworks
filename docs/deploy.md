# Putting a config on the bridge: `canworks-deploy`

`canworks-deploy` checks a canworks config and puts it on [canworks-bridge](modbus-bridge.md), which runs the CAN networks on a Linux device and serves their values over Modbus TCP. It also copies a config into an OpenPLC Editor project, makes a new editor project around it, and exports it as DCF, DBC, HTML, Modbus map, Node-RED flow or CODESYS files. A config with [J1939 networks](j1939.md) works the same way.

For an OpenPLC config ([OpenPLC](modbus-bridge.md#openplc)) the program and the config travel separately: the editor's own **Build and upload** carries the program with the remote device and the `canworks_in` and `canworks_out` programs the configurator or `--into-project` wrote, and the config goes to the bridge with this tool or the configurator's **Devices** page. Nothing of canworks runs inside the OpenPLC Runtime.

## Install (on the engineering PC)

No Python needed: one line installs uv and the newest release (`curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.sh | sh`, or `install-pc.ps1` on Windows, [install-pc.md](install-pc.md#one-line-install-or-update)), or install the release wheel by hand with `uv tool install --compile-bytecode --python 3.12 <wheel>`. Steps for Windows, macOS and Linux, updating, and the pip route: [install-pc.md](install-pc.md).

## Deploy

```sh
canworks-deploy --config canworks.json --bridge 192.168.1.20 --token-file token.txt
```

`--config` takes the config file or the folder that holds it (`canworks/` of an editor project means its `canworks.json`). The tool:

1. reads the config and checks it the way the bridge does at load: the JSON Schema for its `schema_version`, the checks the schema cannot express (the byte image, locations, links, the target), and the EDS checks (object exists, PDO-mappable, `DataType`, `AccessType`, startup SDO value range). A problem stops the deploy, naming the file and JSON path, with the bridge's own wording for EDS problems;
2. collects the config with each EDS file as `canworks/eds/<file>` (each node's `eds` rewritten to that path), plus the simulation file and its files when there is one ([Simulated devices](#simulated-devices));
3. logs in to the bridge's [diagnostics channel](diagnostics.md) with the token (`--token`, `--token-file`, `$CANWORKS_TOKEN` or a prompt), uploads the files there, and waits until the bridge reports that it runs the new config.

The bridge accepts uploads only when its running config has `"allow_changes": true` and `"allow_config_upload": true` in `diagnostics`; otherwise the tool says so and uploads nothing. A config that brings no diagnostics channel of its own is uploaded, but whether it started cannot be read back. `--check-only` runs every check and collects the files without uploading them; `--check` runs the checks alone, with no bridge.

`HOST` may also be a remembered device's name (directly when it answers, over the [remote link](remote-access.md) otherwise; `link:NAME` over the link only) or `local` for the [local runtime](#the-local-runtime)'s bridge.

Nothing is uploaded when a check fails.

## Simulated devices

A config can simulate the network or some of its nodes (`adapter.simulate` and node `simulate`, see [simulator.md](simulator.md)), and a simulation file sets how the simulated devices behave.

**The simulation file.** `simulation.json` next to the config is used when it exists; `--sim FILE` names another. Every mode except the DCF, DBC and HTML exports checks it after the config: the [simulation file schema](../schema/canworks-sim.v1.schema.json) and its `schema_version` (a newer one is refused, naming both versions), node keys that are neither configured nodes nor extra devices, objects that are not in the device's EDS (in sources, faults, scenario steps and conditions), value sources on objects the master writes (naming the RPDO, "startup SDO" or the SDO variable), extra devices (the EDS or DCF file exists, node 0 has a name, names are unique, node IDs are free), CSV files that do not exist, and every expression with the grammar of [Expressions](simulator.md#expressions), including reference cycles. A problem stops the deploy like a config problem, naming the file, the JSON path and, for an expression, the position in its text. The bundle gets:

| File | On the bridge | Path in `simulation.json` |
|---|---|---|
| the simulation file | `canworks/simulation.json` | |
| an extra device's EDS or DCF | `canworks/eds/<file>`, next to the node EDS files (converted to UTF-8 like them) | `eds/<file>` |
| a CSV file of a value source | `canworks/sim/<file>` | `sim/<file>` |

Paths in the simulation file are relative to it, so the rewritten paths point into `canworks/`. Two different files with the same name are refused; rename one. `--into-project` and `--new-project` write the simulation file as `canworks/simulation.json` and its EDS, DCF and CSV files next to it in the project's `canworks/` folder, each path in the file rewritten to the bare file name, as for node EDS files.

**The question before uploading.** When the config simulates the network or any node, the tool says what is simulated before it uploads ("the network is simulated; no CAN interface is used", or "nodes 5, 7 are simulated devices on the real network can0") and asks whether to upload it. `--simulated` (or `--yes`) uploads without asking. Without a terminal to ask on and without either option, the tool stops before building the bundle and names the option that uploads it anyway. `--check-only`, `--into-project` and `--new-project` print the same as a warning. Outputs to a simulated device go nowhere, so never leave a machine's config simulated.

## Into an editor project

To build the config in a browser instead of by hand, use [`canworks-config`](configurator.md); it writes the same folder.

The config can live in its OpenPLC Editor project, next to the program that uses it:

```sh
canworks-deploy --config config/rtd-sensor/canopen_config.json --into-project ~/Documents/workspace/rtd-monitor
```

It runs the same checks as a deploy, then writes `canworks/canworks.json` (each node's `eds` and each network's `dbc` relative to `canworks/`), the EDS files with their device notes (`<eds>.notes.json`) and the DBC files into the project. EDS and DBC files are written as UTF-8 and one in CP1252/Latin-1 is converted, because the editor sends project files as UTF-8 text. An existing `canworks/` folder is replaced only with `--force`, and is then kept as `canworks.bak-<time>` next to it (delete it once you no longer need it). For an OpenPLC config it also writes the editor's remote device, `canworks_in`, `canworks_out` and the `canworks` variable list, as the configurator does ([What the configurator writes](modbus-bridge.md#openplc)); a file canworks owns that was changed in the editor is replaced only with `--force`. Nothing is uploaded: the config still goes to the bridge with `--bridge`.

## A new editor project from the config

Starting without an editor project, `--new-project` creates one around the config:

```sh
canworks-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/Documents/workspace/rtd-monitor [--task-interval T#10ms]
```

It runs the same checks as `--into-project`, then runs the editor's own `openplc-cli create` (so the project is in the editor's recent projects), sets the target to OpenPLC Runtime v4, writes the config into `canworks/` and, for an OpenPLC config, the editor files as `--into-project` does, and leaves `pous/programs/main.st` an empty program `main` for your own code, which reads and writes the networks' values through the `canworks` variable list (`canworks.rtd_AI0_Input_PV`). The task interval defaults to `T#20ms`.

With `--blocks` the project also enables the `canworks` function block library (the CANopen blocks over the bridge and the CAN and J1939 helpers, [plc-library.md](plc-library.md)); an OpenPLC config enables it anyway, since `canworks_in` and `canworks_out` use its helpers. The library is installed into the editor on this PC if it is missing or older than the tools; if that cannot be done (the editor has never run here), the output says how to install it.

An existing folder becomes the project when it has none of the editor's files (`project.json`, `devices/configuration.json`, `devices/pin-mapping.json`, `pous/programs/main.st`) and no `canworks.json` or `canworks/`; otherwise it is refused, naming the file. A failure after `openplc-cli create` removes the new folder, or in an existing folder only what was added. The command needs `openplc-cli` (the editor installs it on first run, or run `openplc-cli install-cli`; `$OPENPLC_CLI` names another program). On Windows `openplc-cli` is a `.cmd` file, which reads `&`, `|`, `^`, `%`, `<`, `>` and `"` as commands, so a project or editor path with one of them is refused before anything runs; move or rename the folder. Nothing is uploaded.

## The function block library

```sh
canworks-deploy library --install              # into OpenPLC Editor on this PC
canworks-deploy library --out DIR              # writes DIR/canworks.stlib
canworks-deploy library --format st --out DIR  # its ST sources, for another Modbus PLC
canworks-deploy library --format plcopen --out DIR  # as PLCopen XML (canworks-library.xml)
canworks-deploy library --project <project>    # enables it in an editor project
canworks-deploy library --list                 # its blocks and functions
```

The library's version is the tools' version. `--install` does what the editor's Library Manager does for "install from file" (restart the editor if it is open); `$OPENPLC_EDITOR_USER_DATA` names another editor settings folder. See [plc-library.md](plc-library.md).

## Checking without a bridge

```sh
canworks-deploy --config canworks.json --check
```

runs every check and uploads nothing.

The checks include the [PDO link](config.md#pdo-links) and `heartbeat_watch` rules the bridge runs at load, with its messages: the producer TPDO is configured, the consumer RPDO is free and in its EDS, both layouts match against both EDS files, the COB-ID rules, SYNC for synchronous consumers, the room in 0x1016 and the watch timeouts. An error stops the deploy and uploads nothing; warnings (types that differ at one size, kept links that stop with SYNC or whose nodes watch the master) are printed and the deploy goes on. The DCF export carries each consumer's link RPDO and heartbeat watch writes too.

## Export the nodes as DCF files

```sh
canworks-deploy --config canopen_config.json --export-dcf dcf/
```

writes one CiA 306 Device Configuration File per node, `dcf/node_<id>.dcf`, for inspection, comparing two configs, or another CANopen tool. Each file is the node's EDS with:

- `ParameterValue=` on every object the master writes to the node at boot (PDO communication and mapping, heartbeat, node guarding, heartbeat consumer, TIME COB-ID, RPDO deadlines, configuration check stamp, startup SDOs), holding the value the node has after the whole download. Objects the master does not write are unchanged.
- `[DeviceComissioning]`: `NodeID`, `NodeName` (the node's `name`), `Baudrate` (kbit/s), `NetNumber=1`, `NetworkName=OpenPLC CANopen`, `CANopenManager=0`, and `LSS_SerialNumber` when the node has a `serial_number`.
- `[FileInfo]`: `FileName`, `LastEDS` (the EDS it came from), `ModifiedBy` and the modification date and time.
- REAL values (`DefaultValue`, `ParameterValue`, `LowLimit`, `HighLimit`) as CiA 306 decimal numbers, so other tools read them, whatever form the EDS used.
- A leading `;` comment naming the boot steps that are not settings: restoring defaults (`restore_configuration`) and the "save" after a configuration check (`store_configuration`).

With several networks each network's files go into a folder of their own, `dcf/<network>/node_<id>.dcf`, each with its own network's bit rate. `--network drives` exports only that network, into `dcf/node_<id>.dcf`. [Slave networks](slave.md) and [J1939 networks](j1939.md) have no CANopen nodes and are left out; `--network` naming one is refused.

The tool runs the deploy checks first, then checks each finished DCF with Lely's CiA 306 lint and reader (the same code the bridge uses), that every value sits on a writable object or equals the EDS value, that `NodeID` is the node's ID and that the node's EDS supports the bit rate, and checks the lines the export wrote against CiA 306 ([standards.md](standards.md#how-conformance-is-checked)), not the lines it copied unchanged from the vendor's EDS; `NodeName` must be printable ASCII of at most 246 characters. If any check fails it prints every problem and writes no file. Nothing is uploaded; `--bridge` and `--check-only` are refused with it.

The values come from the same steps the bridge runs at load (Lely's dcfgen, then canworks' own additions); CI compares them with `canopen_check --dump-writes` ([config.md](config.md)) for every test config. The configurator exports the same files ([configurator.md](configurator.md#export-dcf-files)).

## Export for CODESYS

```sh
canworks-deploy --config canworks.json --export-codesys codesys/ [--codesys-net NAME=N] [--network NAME]
canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"
canworks-deploy --from-codesys "C:\Projects\Line 2\cell.project" --out cell/
```

`--export-codesys` writes the CANopen master networks for a CODESYS project: each node's DCF in a folder per network, the plan `canworks-codesys.json` and the script `import_canworks.py` to run in CODESYS on the open project. `--codesys-import` writes the same folder (temporary, or `--codesys-dir DIR`), runs CODESYS headless on the project, prints the script's report and exits 1 when it has an error; `--codesys-new TYPE:ID:VERSION` creates the project with that PLC device, `--codesys-exe` and `--codesys-profile` pick the CODESYS installation. `--codesys-net NAME=N` sets a network's CODESYS network number (default: the number its interface ends in), `--codesys-plc NAME` the device that gets the bus (default: the device of the project's active application, or its only device), `--codesys-can NETWORK=OBJECT` the CAN interface object in that device for a network's bus,, `--codesys-no-variables` leaves the I/O channels unnamed and `--codesys-remove-nodes` removes nodes an earlier build made that are no longer in the config (otherwise they are kept and listed). `--from-codesys FILE --out DIR` goes the other way: it makes a new config in DIR from a CODESYS `.project` (CODESYS on this PC exports it headless) or a PLCopenXML `.xml`, with `--codesys-plc NAME` for the device, `--eds-dir DIR` for the EDS files and `--force` to replace a config ([codesys.md](codesys.md#import-from-codesys)). The deploy checks and the DCF checks run first; on a failure nothing is written. Nothing is built or uploaded. What the script does and what carries over: [codesys.md](codesys.md).

## Export the network as a DBC file

```sh
canworks-deploy --config canopen_config.json --export-dbc bus.dbc [--dbc-sdo none|config|all]
```

writes the configured network as a DBC file, so CAN bus tools that do not read EDS files (SavvyCAN, Wireshark, python-can with cantools, PCAN-Explorer, BusMaster, CANalyzer) can decode the bus. It holds:

- one message per configured PDO, at the COB-ID the bridge uses (`cob_id`, `"auto"` or the CiA 301 default), sent by the node (TPDO) or by `Master` (RPDO); one signal per mapped object at its bit offset, little-endian, with its type, sign and range (REAL32/REAL64 as IEEE floats). A PDO that keeps the device's mapping is laid out from the EDS default mapping, including objects the config does not use; dummy entries are gaps;
- each node's heartbeat (`NMT_State` with named states) and EMCY (`Error_Code`, `Error_Register`, `Manufacturer_Data`; on the COB-ID the master listens on: `emcy_cob_id` or a startup SDO to 0x1014, else the EDS default of 0x1014, else 0x80 + node ID), the NMT command (`Command` with named commands, `Node_ID`) and, when the config has a SYNC period, SYNC;
- comments naming each signal's object, type and bridge address, each PDO's transmission type, and a `GenMsgCycleTime` for synchronous PDOs (SYNC period times the transmission type);
- from the object's [device notes](configurator.md#device-notes) (the notes file next to the EDS over the built-in CiA notes): the unit, the scale (factor) and value names (`VAL_`, not on float signals) of each signal, and the note text after the signal's comment.

Signals are named after the object in the EDS: a plain object by its `ParameterName`, a sub-object by its parent's name and its own (`AI_Sensor_Type_Output_1`), without repeating the parent when the sub-object's name already starts with it. When `--config` is the `canworks/canworks.json` of an editor project, a signal whose PLC address has exactly one located variable in the project is named after that variable.

With several networks the tool writes one DBC per network next to the given file, `bus_io.dbc` and `bus_drives.dbc` for `--export-dbc bus.dbc`, each with only its own network's nodes, NMT and SYNC. `--network drives` writes only that network, to `bus.dbc`. Slave networks are left out, as for DCF files. A [J1939 network](j1939.md)'s DBC holds its `rx` and `tx` parameter groups with 29-bit identifiers.

`--dbc-sdo` adds each node's SDO request (0x600 + node ID) and response (0x580 + node ID) frames: `none` (the default) adds none, `config` decodes the config's SDO variables and startup SDOs, `all` every EDS object of a numeric type up to 32 bits. The messages are multiplexed on `Object` (index + subindex * 65536, named `0x6110:1 AI_Sensor_Type_AI0_Sensor_Type` in the tool), so a frame shows as command, object and value. Only expedited transfers (up to 4 bytes) decode; on an abort the abort code shows as the object's raw data.

The tool runs the deploy checks first and writes nothing if they fail. A startup SDO that rewrites a configured PDO's settings gets a warning: the DBC follows the config's PDO settings. Nothing is uploaded; `--bridge` and `--check-only` are refused with it. The configurator exports the same file ([configurator.md](configurator.md#export-a-dbc-file)).

## The slave EDS

```sh
canworks-deploy slave-eds slave_eds.json -o canworks/openplc-slave.eds
canworks-deploy slave-eds gateway_eds.json -o canworks/openplc-gateway.eds --gateway canworks/canworks.json --update-config
```

writes the EDS of a [slave network](slave.md) from a short JSON description (identity, heartbeat, layout and objects; every field in [slave.md](slave.md#the-eds)). It prints each object with its index, type and access, the number of RPDOs and TPDOs and the revision number. The file passes the bridge's EDS lint with `eds_lint: "all"`, and the same description always gives the same bytes. Put it next to the config and name it in `slave.eds`; the deploy tool bundles it like any EDS, and the other master's tool imports the same file.

With `--gateway <config>` the generator also adds the objects of that config's [gateway](gateway.md): one slave object per route (named after the route, with the field entry's type, from the master for a route down and to the master for a route up), the field node status ARRAYs and the SDO bridge record. The routes' `slave` ends must match: `--update-config` writes them into the config; without it the tool notes routes that name another object than the EDS gives.

An invalid description or gateway section stops it with the reason (the object and the field) and exit status 1; nothing is written. The configurator builds the same file ([configurator.md](configurator.md#slave-networks)).

## Device notes

```sh
canworks-deploy notes skeleton [--all] [--index LOW-HIGH] canworks/valve.eds [-o FILE [--force]]
canworks-deploy notes builtin canworks/valve.eds [-o FILE [--force]]
canworks-deploy notes check canworks/valve.eds canworks/valve.eds.notes.json
```

work with the [device notes](configurator.md#device-notes) of an EDS without the configurator. `skeleton` prints a `canworks-notes.v1` document with the EDS identity and an entry for each manufacturer object and sub-object (0x2000-0x5FFF): its EDS name, data type (`x-type`) and access (`x-access`), to fill in. With `--all` it has every object of the EDS, standard ones included, an entry with the name of each ARRAY and RECORD object, and on each sub-object also the EDS default (`x-default`), limits (`x-low`, `x-high`) as the EDS writes them and PDO mapping (`x-pdo`); `--index 0x3000-0x30FF` keeps only the objects of that range. When the EDS lacks the vendor ID, product code or revision, the identity leaves it out and stderr says so. `builtin` prints the built-in notes that apply to the EDS (CiA 301, and CiA 401 or 402 by its device type); stderr names the sets used and says when the device's profile has none. `-o FILE` writes the document to FILE instead and refuses a FILE that exists (it may be filled-in notes) unless `--force` is given. `check` prints the warnings the configurator shows for a notes file, one per line, and exits with status 1 when there is any and 0 when there is none. An EDS or notes file that cannot be read stops with the reason and exit status 1; for an EDS the reason names the line and its section (a line that is not `key=value`) or the section (a missing entry or section). The [datasheet notes skill](configurator.md#notes-from-a-datasheet) uses all three.

## Export documentation of the network

```sh
canworks-deploy --config canopen_config.json --export-html network.html [--network NAME] [--doc-title TEXT] [--doc-od used|all] [--doc-embed-eds]
```

writes one self-contained HTML document of the configured networks for people: topology, master and bus settings, the COB-ID map with a bus load estimate, and per node its identity, settings, PDO layouts down to the PLC variables, every SDO write of its boot configuration and an object dictionary extract, plus a PLC I/O cross-reference. With several networks the one document has a section per network; `--network` limits it to one. When `--config` is the `canworks/canworks.json` of an editor project, PLC addresses show their located variables. The tool runs the deploy checks first and writes nothing if they fail; nothing is built or uploaded. What the document holds, the bus load method and the options: [network-docs.md](network-docs.md). The configurator exports the same document ([configurator.md](configurator.md#export-documentation)).

## Modbus clients

`--export-modbus-map FILE.csv|.json|.st` writes a bridge config's register map for the Modbus client ([modbus-bridge.md](modbus-bridge.md#deploying-and-checking-a-config); for a config with the PLC link (`bridge.plc_link`) the `.st` file is the PLC link for another Modbus PLC, [plc-library.md](plc-library.md#on-another-modbus-plc)), and `--export-nodered FILE.json` (with `--nodered-host HOST[:PORT]` and `--nodered-poll-ms N`) writes a Node-RED flow for it; `--export-nodered-package OUT` (no `--config`) writes the Node-RED node package `node-red-canworks-<version>.tgz` that flow needs ([node-red.md](node-red.md)). `--export-plcopen DIR --for trust|generic` (with `--bridge-host HOST`, `--no-library`, `--with-main`) writes PLCopen XML with the PLC link and the library for truST or another PLC, and the files that connect it to the bridge ([plcopen.md](plcopen.md)); `--for codesys` is refused, since CODESYS runs the CANopen master itself as the CODESYS target. In the configurator these files are the Downloads of the bridge's [connections](configurator.md#connections).

## The local runtime

`--bridge local` puts the config on the bridge of the [local runtime](local-runtime.md) on this PC (`canworks-local-runtime start`): the files go into its bridge container through the container engine, so no token is needed. Every network runs simulated there, so the tool says so and does not ask the [simulated-config question](#simulated-devices). Without a local runtime it stops with `no local runtime: run canworks-local-runtime start first`.

## The bridge's certificate

The diagnostics channel is TLS with a certificate the bridge makes at every start; the login is SCRAM-SHA-256 bound to that certificate, so the token never crosses the network and a machine in the middle cannot log in ([diagnostics.md](diagnostics.md#security)). No fingerprint or CA file is needed.

## Exit status

0: the checks passed and, with `--bridge`, the bridge runs the new config (or, for a config without a diagnostics channel, took it). 1: a check failed (nothing uploaded), an upload with simulated devices was not confirmed, the bridge refused the login or the upload, config upload is off on it, or it did not start the new config (its reason is printed). 2: usage error.
