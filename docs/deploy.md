# Deploying a program with CANopen: `canworks-deploy`

A stock OpenPLC Runtime v4 enables a plugin when a program upload carries the plugin's config as `conf/<name>.json`, and disables it when an upload does not. That is how the editor ships EtherCAT. `canworks-deploy` uses the same rule for CANopen: it takes the program the editor built, adds `conf/canworks.json` and the EDS files, checks everything, and uploads it through the runtime's REST API. The runtime then switches the CANopen plugin on by its own rules. No runtime or editor file changes. A config with [J1939 networks](j1939.md) deploys the same way.

The runtime needs the plugin installed once: see [install-stock.md](install-stock.md).

> **Without the editor hook, the editor's own "Build and upload" switches CANopen off.** It sends no `conf/canworks.json`, so the runtime disables the plugin until you deploy with this tool again. The PLC program itself still runs. With the [editor hook](install-stock.md#the-editors-build-and-upload) installed on the runtime, put the config into the project once with `--into-project` and the editor's upload keeps CANopen on. After every deploy the tool prints which of the two applies, from the runtime's build log.

## Install (on the engineering PC)

No Python needed: install uv, then the release wheel with `uv tool install --python 3.12 <wheel>`. Steps for Windows, macOS and Linux, updating, and the pip route: [install-pc.md](install-pc.md).

## Deploy

1. In the OpenPLC editor, select the **OpenPLC Runtime v4** target and use **Build only**. The bundle lands in `<project>/build/OpenPLC Runtime v4/src/`.
2. Deploy it with your CANopen config:

```sh
export OPENPLC_USER=openplc
export OPENPLC_PASSWORD=...        # or leave it unset to be prompted
canworks-deploy \
    --bundle "<project>/build/OpenPLC Runtime v4/src" \
    --config canopen_config.json \
    --runtime 192.168.1.20 \
    --fingerprint 3A:5F:...:C2
```

Instead of `--bundle`, `--project <project>` runs `openplc-cli compile <project> --target "OpenPLC Runtime v4"` first and uses the same output directory (`--target` picks another runtime v4 board; `$OPENPLC_CLI` names the `openplc-cli` program).

The tool:

1. reads the config and checks it the way the plugin does at PLC start: the JSON Schema for its `schema_version`, the checks the schema cannot express, and the EDS checks (object exists, PDO-mappable, `DataType`, `AccessType`, startup SDO value range). A problem stops the deploy, naming the file and JSON path, with the plugin's own wording for EDS problems;
2. copies the bundle, adds `conf/canworks.json` and each EDS file as `conf/canworks/eds/<file>`, and rewrites each node's `eds` to `canworks/eds/<file>`, plus the simulation file and its files when there is one ([Simulated devices](#simulated-devices)). Every other file, including other plugins' configs such as `conf/ethercat.json`, stays byte for byte as the editor wrote it;
3. checks IEC addresses across every plugin config in `conf/*.json` (below);
4. logs in (`POST /api/login`), uploads (`POST /api/upload-file`), follows `/api/compilation-status` and prints the runtime's build log;
5. starts the PLC (`/api/start-plc`), which the runtime leaves stopped after an upload, and waits until `/api/status` reports it running. `--no-start` leaves it stopped.

It exits 0 only when the runtime reports a successful build, its log shows the `canworks` plugin enabled and the PLC runs (or `--no-start` was given). When the device's run/stop switch is at STOP the start is refused and the tool says so.

Nothing is uploaded when a check fails.

## Simulated devices

A config can simulate the network or some of its nodes (`adapter.simulate` and node `simulate`, see [simulator.md](simulator.md)), and a simulation file sets how the simulated devices behave.

**The simulation file.** `simulation.json` next to the config is used when it exists; `--sim FILE` names another. Every mode except the DCF, DBC and HTML exports checks it after the config: the [simulation file schema](../schema/canworks-sim.v1.schema.json) and its `schema_version` (a newer one is refused, naming both versions), node keys that are neither configured nodes nor extra devices, objects that are not in the device's EDS (in sources, faults, scenario steps and conditions), value sources on objects the master writes (naming the RPDO, "startup SDO" or the SDO variable), extra devices (the EDS or DCF file exists, node 0 has a name, names are unique, node IDs are free), CSV files that do not exist, and every expression with the grammar of [Expressions](simulator.md#expressions), including reference cycles. A problem stops the deploy like a config problem, naming the file, the JSON path and, for an expression, the position in its text. The bundle gets:

| File | In the bundle | Path in `simulation.json` |
|---|---|---|
| the simulation file | `conf/canworks/simulation.json` | |
| an extra device's EDS or DCF | `conf/canworks/eds/<file>`, next to the node EDS files (converted to UTF-8 like them) | `eds/<file>` |
| a CSV file of a value source | `conf/canworks/sim/<file>` | `sim/<file>` |

Paths in the simulation file are relative to it, so the rewritten paths point into `conf/canworks/`. Two different files with the same name are refused; rename one. `--into-project` and `--new-project` write the simulation file as `canworks/simulation.json` and its EDS, DCF and CSV files next to it in the project's `canworks/` folder, each path in the file rewritten to the bare file name, as for node EDS files.

**The question before uploading.** When the config simulates the network or any node, the tool says what is simulated before it uploads ("the network is simulated; no CAN interface is used", or "nodes 5, 7 are simulated devices on the real network can0") and asks whether to upload it. `--simulated` (or `--yes`) uploads without asking. Without a terminal to ask on and without either option, the tool stops before building the bundle and names the option that uploads it anyway. `--check-only`, `--into-project` and `--new-project` print the same as a warning. Outputs to a simulated device go nowhere, so never leave a machine's config simulated.

## Into an editor project

To build the config in a browser instead of by hand, use [`canworks-config`](configurator.md); it writes the same folder.

On a runtime with the [editor hook](install-stock.md#the-editors-build-and-upload), the config can live in the editor project instead, so the editor's own **Build and upload** carries it:

```sh
canworks-deploy --config config/rtd-sensor/canopen_config.json --into-project ~/Documents/workspace/rtd-monitor
```

It runs the same checks as a deploy, then writes `canworks/canworks.json` (each node's `eds` relative to `canworks/`) and the EDS files into the project. EDS files are written as UTF-8 and one in CP1252/Latin-1 is converted, because the editor sends project files as UTF-8 text. An existing `canworks/` folder is replaced only with `--force`. Nothing is uploaded. A simulation file `canworks/simulation.json` in the project travels with the editor's upload too, and the editor hook checks it as this tool does.

## A new editor project from the config

Starting without an editor project, `--new-project` creates one around the config:

```sh
canworks-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/Documents/workspace/rtd-monitor [--task-interval T#10ms]
```

It runs the same checks as `--into-project`, then runs the editor's own `openplc-cli create` (so the project is in the editor's recent projects), sets the target to OpenPLC Runtime v4, writes the config into `canworks/` as `--into-project` does, and replaces `pous/programs/main.st` with a program `main` that declares every CANopen location the config uses, in the editor's own form:

```
PROGRAM main
  VAR
    rtd_ok           : BOOL AT %IX10.0; (* node rtd (5): operational *)
    rtd_AI0_Input_PV : INT AT %IW100; (* node rtd (5) TPDO1 0x7130:1 AI0_Input_PV *)
    ...
  END_VAR
```

Master diagnostics come first, then each node in config order: diagnostics, inputs, outputs and the NMT command byte. With [several networks](config.md#several-networks-schema_version-2) the networks follow each other in config order, every name starts with its network's name (`io_door_ok`, `drives_door_ok`) and every comment names the network. A [slave network](slave.md) comes last, and its names always start with the network's name: one variable per binding, named after its `name` or the object's EDS name (`line_speed_setpoint`), with the object's IEC type, and the status and EMCY locations (`line_state`, `line_comm_ok`, `line_sync_count`, `line_emcy`, `line_errreg`), inputs before outputs. A [J1939 network](j1939.md)'s names also start with the network's name: the ECU's state and address, each received PGN's status bit, and one variable per signal, plus its valid bit when it has one (`machine_Pressure`, `machine_Pressure_valid`). Everything is in `main` because Editor 4.3.2 accepts located variables only in a program's VAR block; put your own logic in function blocks called from `main` if you want to split it. The task interval defaults to `T#20ms`.

With `--blocks` the project also enables the `canworks` library (the SDO function blocks, [plc-sdo.md](plc-sdo.md)), and the library is installed into the editor on this PC if it is missing or older than the tools; if that cannot be done (the editor has never run here), the output says how to install it.

The project is written once: later config changes do not touch `main`. Declare new locations from the configurator's "not yet declared" block. An existing folder (even an empty one) is refused, and a failure after `openplc-cli create` removes the new folder. The command needs `openplc-cli` (the editor installs it on first run, or run `openplc-cli install-cli`; `$OPENPLC_CLI` names another program). Nothing is uploaded.

## The SDO block library

```sh
canworks-deploy library --install              # into OpenPLC Editor on this PC
canworks-deploy library --out DIR              # writes DIR/canworks.stlib
canworks-deploy library --project <project>    # enables it in an editor project
canworks-deploy library --list                 # the block names
```

The library's version is the tools' version. `--install` does what the editor's Library Manager does for "install from file" (restart the editor if it is open); `$OPENPLC_EDITOR_USER_DATA` names another editor settings folder. See [plc-sdo.md](plc-sdo.md).

## Checking without a runtime

```sh
canworks-deploy --bundle <dir> --config canopen_config.json --check-only --output program.zip
```

runs every check and writes the zip that would be uploaded.

## Export the nodes as DCF files

```sh
canworks-deploy --config canopen_config.json --export-dcf dcf/
```

writes one CiA 306 Device Configuration File per node, `dcf/node_<id>.dcf`, for inspection, comparing two configs, or another CANopen tool. Each file is the node's EDS with:

- `ParameterValue=` on every object the master writes to the node at boot (PDO communication and mapping, heartbeat, node guarding, heartbeat consumer, TIME COB-ID, RPDO deadlines, configuration check stamp, startup SDOs), holding the value the node has after the whole download. Objects the master does not write are unchanged.
- `[DeviceComissioning]`: `NodeID`, `NodeName` (the node's `name`), `Baudrate` (kbit/s), `NetNumber=1`, `NetworkName=OpenPLC CANopen`, `CANopenManager=0`, and `LSS_SerialNumber` when the node has a `serial_number`.
- `[FileInfo]`: `FileName`, `LastEDS` (the EDS it came from), `ModifiedBy` and the modification date and time.
- A leading `;` comment naming the boot steps that are not settings: restoring defaults (`restore_configuration`), the firmware download (`software_file`) and the "save" after a configuration check (`store_configuration`).

With several networks each network's files go into a folder of their own, `dcf/<network>/node_<id>.dcf`, each with its own network's bit rate. `--network drives` exports only that network, into `dcf/node_<id>.dcf`. [Slave networks](slave.md) and [J1939 networks](j1939.md) have no CANopen nodes and are left out; `--network` naming one is refused.

The tool runs the deploy checks first, then checks each finished DCF with Lely's CiA 306 lint and reader (the same code the plugin uses), that every value sits on a writable object or equals the EDS value, that `NodeID` is the node's ID and that the node's EDS supports the bit rate. If any check fails it prints every problem and writes no file. Nothing is built or uploaded; `--runtime`, `--output` and `--check-only` are refused with it.

The values come from the same steps the plugin runs on the PLC (Lely's dcfgen, then the plugin's own additions); CI compares them with `canopen_check --dump-writes` ([config.md](config.md)) for every test config. The configurator exports the same files ([configurator.md](configurator.md#export-dcf-files)).

## Export the network as a DBC file

```sh
canworks-deploy --config canopen_config.json --export-dbc bus.dbc [--dbc-sdo none|config|all]
```

writes the configured network as a DBC file, so CAN bus tools that do not read EDS files (SavvyCAN, Wireshark, python-can with cantools, PCAN-Explorer, BusMaster, CANalyzer) can decode the bus. It holds:

- one message per configured PDO, at the COB-ID the plugin uses (`cob_id`, `"auto"` or the CiA 301 default), sent by the node (TPDO) or by `Master` (RPDO); one signal per mapped object at its bit offset, little-endian, with its type, sign and range (REAL32/REAL64 as IEEE floats). A PDO that keeps the device's mapping is laid out from the EDS default mapping, including objects the PLC does not use; dummy entries are gaps;
- each node's heartbeat (`NMT_State` with named states) and EMCY (`Error_Code`, `Error_Register`, `Manufacturer_Data`), the NMT command (`Command` with named commands, `Node_ID`) and, when the config has a SYNC period, SYNC;
- comments naming each signal's object, type and PLC address, each PDO's transmission type, and a `GenMsgCycleTime` for synchronous PDOs (SYNC period times the transmission type);
- from the object's [device notes](configurator.md#device-notes) (the notes file next to the EDS over the built-in CiA notes): the unit, the scale (factor) and value names (`VAL_`, not on float signals) of each signal, and the note text after the signal's comment.

Signals are named after the object in the EDS: a plain object by its `ParameterName`, a sub-object by its parent's name and its own (`AI_Sensor_Type_Output_1`), without repeating the parent when the sub-object's name already starts with it. When `--config` is the `canworks/canworks.json` of an editor project, a signal whose PLC address has exactly one located variable in the project is named after that variable.

With several networks the tool writes one DBC per network next to the given file, `bus_io.dbc` and `bus_drives.dbc` for `--export-dbc bus.dbc`, each with only its own network's nodes, NMT and SYNC. `--network drives` writes only that network, to `bus.dbc`. Slave networks are left out, as for DCF files. A [J1939 network](j1939.md)'s DBC holds its `rx` and `tx` parameter groups with 29-bit identifiers.

`--dbc-sdo` adds each node's SDO request (0x600 + node ID) and response (0x580 + node ID) frames: `none` (the default) adds none, `config` decodes the config's SDO variables and startup SDOs, `all` every EDS object of a numeric type up to 32 bits. The messages are multiplexed on `Object` (index + subindex * 65536, named `0x6110:1 AI_Sensor_Type_AI0_Sensor_Type` in the tool), so a frame shows as command, object and value. Only expedited transfers (up to 4 bytes) decode; on an abort the abort code shows as the object's raw data.

The tool runs the deploy checks first and writes nothing if they fail. A startup SDO that rewrites a configured PDO's settings gets a warning: the DBC follows the config's PDO settings. Nothing is built or uploaded; `--runtime`, `--output` and `--check-only` are refused with it. The configurator exports the same file ([configurator.md](configurator.md#export-a-dbc-file)).

## The slave EDS

```sh
canworks-deploy slave-eds slave_eds.json -o canworks/openplc-slave.eds
canworks-deploy slave-eds gateway_eds.json -o canworks/openplc-gateway.eds --gateway canworks/canworks.json --update-config
```

writes the EDS of a [slave network](slave.md) from a short JSON description (identity, heartbeat, layout and objects; every field in [slave.md](slave.md#the-eds)). It prints each object with its index, type and access, the number of RPDOs and TPDOs and the revision number. The file passes the plugin's EDS lint with `eds_lint: "all"`, and the same description always gives the same bytes. Put it next to the config and name it in `slave.eds`; the deploy tool bundles it like any EDS, and the other master's tool imports the same file.

With `--gateway <config>` the generator also adds the objects of that config's [gateway](gateway.md): one slave object per route (named after the route, with the field entry's type, from the master for a route down and to the master for a route up), the field node status ARRAYs and the SDO bridge record. The routes' `slave` ends must match: `--update-config` writes them into the config; without it the tool notes routes that name another object than the EDS gives.

An invalid description or gateway section stops it with the reason (the object and the field) and exit status 1; nothing is written. The configurator builds the same file ([configurator.md](configurator.md#slave-networks)).

## Export documentation of the network

```sh
canworks-deploy --config canopen_config.json --export-html network.html [--network NAME] [--doc-title TEXT] [--doc-od used|all] [--doc-embed-eds] [--doc-cycle-ms MS]
```

writes one self-contained HTML document of the configured networks for people: topology, master and bus settings, the COB-ID map with a bus load estimate, and per node its identity, settings, PDO layouts down to the PLC variables, every SDO write of its boot configuration and an object dictionary extract, plus a PLC I/O cross-reference. With several networks the one document has a section per network; `--network` limits it to one. When `--config` is the `canworks/canworks.json` of an editor project, PLC addresses show their located variables and the project's task interval is the PLC cycle. The tool runs the deploy checks first and writes nothing if they fail; nothing is built or uploaded. What the document holds, the bus load method and the options: [network-docs.md](network-docs.md). The configurator exports the same document ([configurator.md](configurator.md#export-documentation)).

## Address clashes with other plugins

Every string under a key named `iec_location` or `status_location` in any `conf/*.json` is a PLC address (a sibling integer `len`, as in the Modbus master's config, makes it a run of addresses). Each size letter is its own table in the OpenPLC image, so only addresses of the same area and size can clash: `%IW100` and `%ID100` are different variables, `%ID100` and `%ID100` are the same one.

| Overlap between two plugins | Result |
|---|---|
| inputs (`%I`) | error: both would write the same input. `--allow-clash` turns it into a warning. |
| outputs (`%Q`) | warning: both only read it |
| memory (`%M`) | warning |

Overlaps inside `canworks.json` are errors, as in the plugin.

An empty config, such as the zero-byte `conf/ethercat.json` the editor writes into every build, has no addresses and is skipped quietly. A config that is not valid JSON gets a warning that its addresses are not checked.

## A Modbus bridge

A config with a top-level `bridge` object runs on [canworks-bridge](modbus-bridge.md), not in OpenPLC: the tool refuses to upload it to a runtime and says so. `--bridge HOST[:PORT]` uploads it to a running bridge over its diagnostics channel (`--token` or `--token-file`), and `--export-modbus-map FILE.csv|.json|.st` writes its register map for the Modbus client ([modbus-bridge.md](modbus-bridge.md#deploying-and-checking-a-config)).

## The local simulator runtime

`--runtime local` deploys to the [local simulator runtime](local-runtime.md) on this PC (`canworks-sim-runtime start`): the tool takes its address, user, password and certificate fingerprint from the saved `local-runtime.json`, so no `--fingerprint` or password is needed (`--user`, `$OPENPLC_PASSWORD` and the certificate options still win when given). Every network runs simulated there, so the tool says so and does not ask the [simulated-config question](#simulated-devices). Without a local runtime it stops with `no local runtime: run canworks-sim-runtime start first`.

`--runtime NAME` with the name of a remembered runtime deploys directly when it answers and over the [remote link](remote-access.md) otherwise; `--runtime link:NAME` uses only the link. The certificate checks below are the same on both paths.

## The runtime's certificate

The runtime serves HTTPS on port 8443 with a self-signed certificate. The tool checks it before it sends the password:

- `--fingerprint SHA256` pins the certificate's SHA-256 fingerprint. On the device: `openssl x509 -in <runtime>/cert.pem -noout -fingerprint -sha256`. When the check fails, the tool prints the fingerprint the runtime presented, for comparison.
- `--ca FILE` verifies against a CA or the runtime's own `cert.pem` (copied from the device); the host name or IP you connect to must be in the certificate.
- `--insecure` skips the check. Use it only on a network you trust.

Without any of these, the system's trust store is used, which a self-signed certificate does not pass.

The password is read from `$OPENPLC_PASSWORD` or an interactive prompt, never from the command line or the config.

## Exit status

0: deployed, the runtime built the program and enabled CANopen. 1: a check failed (nothing uploaded), an upload with simulated devices was not confirmed, the runtime rejected the login or the upload, its build failed (the log is printed), or it did not enable the `canworks` plugin (it is not installed, see [install-stock.md](install-stock.md)). 2: usage error.
