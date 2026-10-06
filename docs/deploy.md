# Deploying a program with CANopen: `openplc-canopen-deploy`

A stock OpenPLC Runtime v4 enables a plugin when a program upload carries the plugin's config as `conf/<name>.json`, and disables it when an upload does not. That is how the editor ships EtherCAT. `openplc-canopen-deploy` uses the same rule for CANopen: it takes the program the editor built, adds `conf/canopen.json` and the EDS files, checks everything, and uploads it through the runtime's REST API. The runtime then switches the CANopen plugin on by its own rules. No runtime or editor file changes.

The runtime needs the plugin installed once: see [install-stock.md](install-stock.md).

> **Without the editor hook, the editor's own "Build and upload" switches CANopen off.** It sends no `conf/canopen.json`, so the runtime disables the plugin until you deploy with this tool again. The PLC program itself still runs. With the [editor hook](install-stock.md#the-editors-build-and-upload) installed on the runtime, put the config into the project once with `--into-project` and the editor's upload keeps CANopen on. After every deploy the tool prints which of the two applies, from the runtime's build log.

## Install (on the engineering PC)

No Python needed: install uv, then the release wheel with `uv tool install --python 3.12 <wheel>`. Steps for Windows and macOS, updating, and the pip route: [install-pc.md](install-pc.md).

## Deploy

1. In the OpenPLC editor, select the **OpenPLC Runtime v4** target and use **Build only**. The bundle lands in `<project>/build/OpenPLC Runtime v4/src/`.
2. Deploy it with your CANopen config:

```sh
export OPENPLC_USER=openplc
export OPENPLC_PASSWORD=...        # or leave it unset to be prompted
openplc-canopen-deploy \
    --bundle "<project>/build/OpenPLC Runtime v4/src" \
    --config canopen_config.json \
    --runtime 192.168.1.20 \
    --fingerprint 3A:5F:...:C2
```

Instead of `--bundle`, `--project <project>` runs `openplc-cli compile <project> --target "OpenPLC Runtime v4"` first and uses the same output directory (`--target` picks another runtime v4 board; `$OPENPLC_CLI` names the `openplc-cli` program).

The tool:

1. reads the config and checks it the way the plugin does at PLC start: the JSON Schema for its `schema_version`, the checks the schema cannot express, and the EDS checks (object exists, PDO-mappable, `DataType`, `AccessType`, startup SDO value range). A problem stops the deploy, naming the file and JSON path, with the plugin's own wording for EDS problems;
2. copies the bundle, adds `conf/canopen.json` and each EDS file as `conf/canopen/eds/<file>`, and rewrites each node's `eds` to `canopen/eds/<file>`. Every other file, including other plugins' configs such as `conf/ethercat.json`, stays byte for byte as the editor wrote it;
3. checks IEC addresses across every plugin config in `conf/*.json` (below);
4. logs in (`POST /api/login`), uploads (`POST /api/upload-file`), follows `/api/compilation-status` and prints the runtime's build log;
5. starts the PLC (`/api/start-plc`), which the runtime leaves stopped after an upload, and waits until `/api/status` reports it running. `--no-start` leaves it stopped.

It exits 0 only when the runtime reports a successful build, its log shows the `canopen` plugin enabled and the PLC runs (or `--no-start` was given). When the device's run/stop switch is at STOP the start is refused and the tool says so.

Nothing is uploaded when a check fails.

## Into an editor project

To build the config in a browser instead of by hand, use [`openplc-canopen-config`](configurator.md); it writes the same folder.

On a runtime with the [editor hook](install-stock.md#the-editors-build-and-upload), the config can live in the editor project instead, so the editor's own **Build and upload** carries it:

```sh
openplc-canopen-deploy --config config/rtd-sensor/canopen_config.json --into-project ~/Documents/workspace/rtd-monitor
```

It runs the same checks as a deploy, then writes `canopen/canopen.json` (each node's `eds` relative to `canopen/`) and the EDS files into the project. EDS files are written as UTF-8 and one in CP1252/Latin-1 is converted, because the editor sends project files as UTF-8 text. An existing `canopen/` folder is replaced only with `--force`. Nothing is uploaded.

## A new editor project from the config

Starting without an editor project, `--new-project` creates one around the config:

```sh
openplc-canopen-deploy --config config/rtd-sensor/canopen_config.json --new-project ~/Documents/workspace/rtd-monitor [--task-interval T#10ms]
```

It runs the same checks as `--into-project`, then runs the editor's own `openplc-cli create` (so the project is in the editor's recent projects), sets the target to OpenPLC Runtime v4, writes the config into `canopen/` as `--into-project` does, and replaces `pous/programs/main.st` with a program `main` that declares every CANopen location the config uses, in the editor's own form:

```
PROGRAM main
  VAR
    rtd_ok           : BOOL AT %IX10.0; (* node rtd (5): operational *)
    rtd_AI0_Input_PV : INT AT %IW100; (* node rtd (5) TPDO1 0x7130:1 AI0_Input_PV *)
    ...
  END_VAR
```

Master diagnostics come first, then each node in config order: diagnostics, inputs, outputs and the NMT command byte. With [several networks](config.md#several-networks-schema_version-2) the networks follow each other in config order, every name starts with its network's name (`io_door_ok`, `drives_door_ok`) and every comment names the network. Everything is in `main` because Editor 4.3.2 accepts located variables only in a program's VAR block; put your own logic in function blocks called from `main` if you want to split it. The task interval defaults to `T#20ms`.

The project is written once: later config changes do not touch `main`. Declare new locations from the configurator's "not yet declared" block. An existing folder (even an empty one) is refused, and a failure after `openplc-cli create` removes the new folder. The command needs `openplc-cli` (the editor installs it on first run, or run `openplc-cli install-cli`; `$OPENPLC_CLI` names another program). Nothing is uploaded.

## Checking without a runtime

```sh
openplc-canopen-deploy --bundle <dir> --config canopen_config.json --check-only --output program.zip
```

runs every check and writes the zip that would be uploaded.

## Export the nodes as DCF files

```sh
openplc-canopen-deploy --config canopen_config.json --export-dcf dcf/
```

writes one CiA 306 Device Configuration File per node, `dcf/node_<id>.dcf`, for inspection, comparing two configs, or another CANopen tool. Each file is the node's EDS with:

- `ParameterValue=` on every object the master writes to the node at boot (PDO communication and mapping, heartbeat, node guarding, heartbeat consumer, TIME COB-ID, RPDO deadlines, configuration check stamp, startup SDOs), holding the value the node has after the whole download. Objects the master does not write are unchanged.
- `[DeviceComissioning]`: `NodeID`, `NodeName` (the node's `name`), `Baudrate` (kbit/s), `NetNumber=1`, `NetworkName=OpenPLC CANopen`, `CANopenManager=0`, and `LSS_SerialNumber` when the node has a `serial_number`.
- `[FileInfo]`: `FileName`, `LastEDS` (the EDS it came from), `ModifiedBy` and the modification date and time.
- A leading `;` comment naming the boot steps that are not settings: restoring defaults (`restore_configuration`), the firmware download (`software_file`) and the "save" after a configuration check (`store_configuration`).

With several networks each network's files go into a folder of their own, `dcf/<network>/node_<id>.dcf`, each with its own network's bit rate. `--network drives` exports only that network, into `dcf/node_<id>.dcf`.

The tool runs the deploy checks first, then checks each finished DCF with Lely's CiA 306 lint and reader (the same code the plugin uses), that every value sits on a writable object or equals the EDS value, that `NodeID` is the node's ID and that the node's EDS supports the bit rate. If any check fails it prints every problem and writes no file. Nothing is built or uploaded; `--runtime`, `--output` and `--check-only` are refused with it.

The values come from the same steps the plugin runs on the PLC (Lely's dcfgen, then the plugin's own additions); CI compares them with `canopen_check --dump-writes` ([config.md](config.md)) for every test config. The configurator exports the same files ([configurator.md](configurator.md#export-dcf-files)).

## Export the network as a DBC file

```sh
openplc-canopen-deploy --config canopen_config.json --export-dbc bus.dbc [--dbc-sdo none|config|all]
```

writes the configured network as a DBC file, so CAN bus tools that do not read EDS files (SavvyCAN, Wireshark, python-can with cantools, PCAN-Explorer, BusMaster, CANalyzer) can decode the bus. It holds:

- one message per configured PDO, at the COB-ID the plugin uses (`cob_id`, `"auto"` or the CiA 301 default), sent by the node (TPDO) or by `Master` (RPDO); one signal per mapped object at its bit offset, little-endian, with its type, sign and range (REAL32/REAL64 as IEEE floats). A PDO that keeps the device's mapping is laid out from the EDS default mapping, including objects the PLC does not use; dummy entries are gaps;
- each node's heartbeat (`NMT_State` with named states) and EMCY (`Error_Code`, `Error_Register`, `Manufacturer_Data`), the NMT command (`Command` with named commands, `Node_ID`) and, when the config has a SYNC period, SYNC;
- comments naming each signal's object, type and PLC address, each PDO's transmission type, and a `GenMsgCycleTime` for synchronous PDOs (SYNC period times the transmission type).

Signals are named after the object in the EDS: a plain object by its `ParameterName`, a sub-object by its parent's name and its own (`AI_Sensor_Type_Output_1`), without repeating the parent when the sub-object's name already starts with it. When `--config` is the `canopen/canopen.json` of an editor project, a signal whose PLC address has exactly one located variable in the project is named after that variable.

With several networks the tool writes one DBC per network next to the given file, `bus_io.dbc` and `bus_drives.dbc` for `--export-dbc bus.dbc`, each with only its own network's nodes, NMT and SYNC. `--network drives` writes only that network, to `bus.dbc`.

`--dbc-sdo` adds each node's SDO request (0x600 + node ID) and response (0x580 + node ID) frames: `none` (the default) adds none, `config` decodes the config's SDO variables and startup SDOs, `all` every EDS object of a numeric type up to 32 bits. The messages are multiplexed on `Object` (index + subindex * 65536, named `0x6110:1 AI_Sensor_Type_AI0_Sensor_Type` in the tool), so a frame shows as command, object and value. Only expedited transfers (up to 4 bytes) decode; on an abort the abort code shows as the object's raw data.

The tool runs the deploy checks first and writes nothing if they fail. A startup SDO that rewrites a configured PDO's settings gets a warning: the DBC follows the config's PDO settings. Nothing is built or uploaded; `--runtime`, `--output` and `--check-only` are refused with it. The configurator exports the same file ([configurator.md](configurator.md#export-a-dbc-file)).

## Address clashes with other plugins

Every string under a key named `iec_location` or `status_location` in any `conf/*.json` is a PLC address (a sibling integer `len`, as in the Modbus master's config, makes it a run of addresses). Each size letter is its own table in the OpenPLC image, so only addresses of the same area and size can clash: `%IW100` and `%ID100` are different variables, `%ID100` and `%ID100` are the same one.

| Overlap between two plugins | Result |
|---|---|
| inputs (`%I`) | error: both would write the same input. `--allow-clash` turns it into a warning. |
| outputs (`%Q`) | warning: both only read it |
| memory (`%M`) | warning |

Overlaps inside `canopen.json` are errors, as in the plugin.

## The runtime's certificate

The runtime serves HTTPS on port 8443 with a self-signed certificate. The tool checks it before it sends the password:

- `--fingerprint SHA256` pins the certificate's SHA-256 fingerprint. On the device: `openssl x509 -in <runtime>/cert.pem -noout -fingerprint -sha256`. When the check fails, the tool prints the fingerprint the runtime presented, for comparison.
- `--ca FILE` verifies against a CA or the runtime's own `cert.pem` (copied from the device); the host name or IP you connect to must be in the certificate.
- `--insecure` skips the check. Use it only on a network you trust.

Without any of these, the system's trust store is used, which a self-signed certificate does not pass.

The password is read from `$OPENPLC_PASSWORD` or an interactive prompt, never from the command line or the config.

## Exit status

0: deployed, the runtime built the program and enabled CANopen. 1: a check failed (nothing uploaded), the runtime rejected the login or the upload, its build failed (the log is printed), or it did not enable the `canopen` plugin (it is not installed, see [install-stock.md](install-stock.md)). 2: usage error.
