# CANopen networks in CODESYS

A canworks config can be built into a CODESYS project, so a CODESYS controller or display with a CAN interface runs the same bus with CODESYS's own CANopen Manager: the nodes, their PDOs, COB-IDs, transmission types and timers, heartbeat, startup SDOs and a variable name on every mapped I/O channel. It works the other way too: [Import from CODESYS](#import-from-codesys) makes a canworks config from the CANopen networks of a CODESYS project, and a later build changes only what was edited, so a config moves back and forth between the two. canworks keeps doing what it does around the bus: the configurator, checks, bus trace and commissioning.

CODESYS is not a Modbus client of canworks-bridge: when the CAN interface is on a Linux device, or for J1939 and raw CAN, which only the bridge runs, pick the Modbus bridge target with a PLC that is one of its [connections](modbus-bridge.md#connections) instead.

## CODESYS as the project target

CODESYS is one of the two project targets, next to the Modbus bridge ([configurator.md](configurator.md#project-target)). A config whose target is CODESYS has a top-level `codesys` object ([config.md](config.md#codesys-target)):

```json
{
  "schema_version": 2,
  "codesys": {"project": "C:\\Projects\\cell.project", "device": "PLC"},
  "networks": [{"name": "field", "adapter": {"bitrate": 250000}, "codesys": {"net_id": 1},
                "master": {"node_id": 1, "heartbeat_ms": 100}, "nodes": ["..."]}]
}
```

- The PDO entries need no `iec_location`: CODESYS assigns the I/O addresses. An entry's optional `name` names its channel (`<node>_<name>`); without one the channel gets the generated name from the EDS (`dio_Read_input_8_bit_1`).
- The adapter needs only the bit rate. The network's `codesys` object gives the CODESYS network number and CAN interface object.
- Everything canworks-bridge does on its own, and CODESYS does not take, is not used: status and diagnostic locations, SDO variables, EDS lint, simulated devices, raw CAN messages, the gateway and Online access. The configurator hides them; a value the config still has is a warning in Problems, with Remove ([What carries over](#what-carries-over)).
- Slave, J1939 and plain CAN networks stay with canworks; the configurator offers only CANopen master networks.
- `canworks-bridge` refuses a CODESYS config, and `canworks-deploy --bridge` stops before uploading it.

In the configurator, switch the **Project target** on the Project page to CODESYS. Every PDO entry gets its current generated name written in, so the channel names stay what they were, and the settings CODESYS does not use are removed, with the bridge's connections. Switching back to the Modbus bridge gives every entry a location again. The **CODESYS** page in the tree has the project file, the device that gets the bus, the PLC device for a new project (picked from the PLCs installed in CODESYS; **Browse…** picks or names the project file) and whether the channels are named; each network's Bus page has its network number and CAN interface object.

**Build into CODESYS project…** in the header saves nothing by itself: it builds the saved config into the project with CODESYS on this PC, headless, and shows CODESYS's report. Close the project in the CODESYS window first; a build into a project that is open there fails, and the report says so. On a PC without CODESYS, **Download for CODESYS** gives the export folder below as a zip to run in CODESYS elsewhere.

## Import from CODESYS

**Import from CODESYS…** on the configurator's start page makes a new CODESYS config from a CODESYS project; on the CODESYS page of a CODESYS config it adds the project's networks to that config. It reads either file:

- a CODESYS `.project`, on a PC with CODESYS: canworks runs CODESYS headless to export it (a minute or two) and does not change the project. Close the project in the CODESYS window first.
- a PLCopenXML `.xml`, on any PC (a Mac too): in CODESYS, select the device with the CANopen Manager and use **Project > Export PLCopenXML**.

A file with several devices that have a CANopen Manager (a display project with one device per variant) shows them with their CANbuses and node counts; the device of the project's active application is selected. The preview then lists each network (named after its variables' prefix, else its CANbus) and node with where its EDS comes from:

| EDS state | Where from |
|---|---|
| EDS in this config | an EDS file in the open config's folder with the node's vendor ID, product code and revision |
| EDS from the library | the configurator's EDS library; without an exact revision, the same product with a note naming both revisions |
| EDS from CODESYS on this PC | the device description CODESYS installed for the device, when the import runs on that PC |
| EDS missing | none of these: **Add EDS…** gives the EDS to every node of that CODESYS device type. Create config waits until each node has one |

and what was not carried over, with where it was. **Create config…** asks for a name and location and writes the config with its EDS files; `codesys.project` names the imported project and `codesys.device` the device, so **Build into CODESYS project** goes straight back into it and reports every node up to date. **Add to this config** adds the networks to the draft (Save writes them); a network whose name or CODESYS network number the config uses already asks **Add it as a new network** or **Replace** the config's network. Nothing is written before either.

The command line does the same into a new folder:

```sh
canworks-deploy --from-codesys "C:\Projects\line2.project" --out line2
canworks-deploy --from-codesys line2.xml --out line2 --eds-dir eds/
```

`--codesys-plc NAME` picks the device when the file has several, `--eds-dir DIR` (repeatable) takes the EDS files from DIR instead of the configurator's EDS library, and `--force` replaces a config in the folder. The report lists each node with its EDS and every setting not carried; with a node without an EDS nothing is written.

What an import gives:

- **Networks:** the CANbus's network number as `codesys.net_id`, interface `canN` and bit rate; the manager's node ID, SYNC, heartbeat, TIME, start options, NMT inhibit time and SDO timeout.
- **Nodes:** node ID, name (the CODESYS name made a valid identifier), optional, no initialization, reset before configuring, heartbeat producer and consumers, node guarding, TIME consumer, every enabled PDO with COB-ID, transmission type, inhibit time, event timer and mapping, and the startup SDOs added for objects from 0x2000. A PDO that is off is left out, which switches it off in canworks. Values equal to the EDS default are left out (unset means the EDS's value), and so is a COB-ID equal to the CiA default for the node.
- **Entry names:** each channel's variable becomes the entry's `name`, left out when it equals the generated name; bit variables become the entry's [bits](config.md#bit-channels).
- **CODESYS-only settings** travel in `codesys` objects ([config.md](config.md#codesys-target)) so a build writes them back: the device's CODESYS name and identity-check ticks, a PDO not processed by the manager, a fixed I/O address, a variable name that is no valid entry name, and a startup SDO's abort-on-error and jump-to-line.
- **Not carried,** each with a report line: CODESYS as a CANopen slave (make a slave network in canworks), CANbuses without a CANopen Manager (J1939), other device types, manager and device settings canworks has no field for when they differ from their default (such as the slave heartbeat watch ratio), and SDO flags on rows CODESYS generates.

## How it works

The export is a folder:

| File | What it is |
|---|---|
| `<network>/node_<id>.dcf` | Each node as a CiA 306 DCF, the same files `--export-dcf` writes ([deploy.md](deploy.md#export-the-nodes-as-dcf-files)). CODESYS's device repository takes a DCF like an EDS and reads its `ParameterValue` entries, so the device arrives with the configured PDO communication and mapping parameters and startup SDOs. A value equal to the EDS default is not a `ParameterValue`, and CODESYS then leaves its own setting empty, so the script also sets each node's heartbeat producer time itself. |
| `canworks-codesys.json` | The plan: every network's CODESYS network number, bit rate and CANopen Manager settings, every node's settings and I/O channel names, and the settings that have no CODESYS counterpart. |
| `import_canworks.py` | The script CODESYS runs. It is the same file for every config. |
| `README.txt` | How to run it. |

The script uses the project's active device (the one whose application is the active application), finds or adds a CANbus with the network's number and a CANopen Manager under it (a new object gets a name nothing else in the device uses, such as `CANopen_Manager_2` for the second network, because CODESYS wants names unique in the whole device), installs each node's DCF into the device repository and adds the node straight away, sets the settings, names each I/O channel and builds the project. It writes `import_report.txt` next to itself and prints the same report in CODESYS's message view.

Numbers in the config are read as the checks read them, so a node ID or PDO number written as a string (`"node_id": "0x02"`, `"number": "1"`) gives the same export as the plain number. When the I/O channels cannot be named, the export stops with an error (naming the field of the node and PDO when the config is at fault) rather than leaving the channels out.

Get the folder from the configurator (**Download for CODESYS** in the Export menu or on the CODESYS page of a CODESYS project, a zip) or from the command line, for a config of any target:

```sh
canworks-deploy --config canworks.json --export-codesys codesys/
```

## Run it in CODESYS

1. Open your project in CODESYS. It needs the PLC or display device that has the CAN interface; the script adds nothing else to the project tree. With several devices in the project, make the one that gets the bus active first (**Set Active Application** on its application, the same choice Build and Login use).
2. **Tools > Scripting > Execute Script File...** and pick `import_canworks.py` in the export folder.
3. Read the report, check the project and save it. The script does not save a project you have open.

## Run it from the command line

```sh
canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"
```

writes the export into a temporary folder, runs CODESYS headless on the project, prints the report and saves the project when nothing failed. The exit status is 1 when the report has an error. In a CODESYS config, `--codesys-import` with no project takes `codesys.project`, and `codesys.create` gives the PLC device of a project that does not exist yet; the options below override the config's settings. `--codesys-dir DIR` keeps the export in DIR. `--codesys-new TYPE:ID:VERSION` creates the project with that PLC device from CODESYS's device repository (for example `"4096:0000 0004:3.5.22.40"`, CODESYS Control Win V3 x64), where `--codesys-import` names a project that does not exist yet. A project path without an extension gets `.project`.

The tool uses the newest CODESYS in the program folders and its newest profile; `--codesys-exe` and `--codesys-profile` pick another one, for example a device vendor's own CODESYS installation. Without the deploy tool, set `"project"` in `canworks-codesys.json` to the project's path and run:

```sh
CODESYS.exe --profile="CODESYS V3.5 SP22 Patch 4" --noUI --runscript="C:\path\to\codesys\import_canworks.py"
```

## Which device gets the bus

The bus goes to one device of the project, chosen in this order:

1. The device named with `--codesys-plc NAME`, else the config's `codesys.device` (`"plc"` in `canworks-codesys.json`).
2. The device that holds the project's active application, at any depth in the device tree.
3. The only device of the project.

The report's `device` line names the device and the reason. A project with several devices and no active application stops with the list of devices and changes nothing. When the named device is not the active one, the report warns that the build checked the active application on the other device. If you switch the active device and run the script again, the bus goes to the new device; the old one keeps its manager and nodes, and the report warns when it has a manager on the same network number, since two controllers would then drive the same bus. A project that keeps one device per hardware variant gets one such warning per network, naming the first five devices and how many more.

## Network numbers and the device's CAN interfaces

CODESYS picks a CAN interface by the CANbus object's **Network** number. The export takes it from the network's `codesys.net_id`, else from the interface's number (`can1` gives 1); `--codesys-net NAME=N` sets it for network NAME. Devices count their CAN interfaces in their own way, some from 0 and some from 1, so look at your device's CANbus objects or its manual first. When the device already has a CANbus with that number (many device descriptions bring theirs), the script uses it and its CANopen Manager; otherwise it adds both. Device descriptions often allow only their vendor's own CANbus under their CAN interface, so the script tries CANbus devices in this order and keeps the first one CODESYS accepts: the CANbus that other devices in the project have under the same kind of CAN interface, the project's other CANbus devices, then those installed in CODESYS (newest version of each, CODESYS's standard CANbus first). A refused try leaves nothing in the project. The report's `created` line names the CANbus used and where it came from (`as on device TemplateDevice`, `installed`), and the CANopen Manager is the one the project already has under that kind of CANbus, else the newest installed.

Many controllers and displays bring their CAN ports as objects of their own, for example **Communication > CAN**, and refuse a CANbus directly under the device. When the device has no CANbus with the network's number, the script adds the new one under the device's CAN interface object: the one `--codesys-can NETWORK=OBJECT` or the network's `codesys.interface` names (`"interface"` on the network in the plan), else the device's only object whose name is CAN or has CAN as a word (`CAN`, `CAN1`, `Port CAN 2`), else the one of those whose name ends in the network number, else the device itself. If the interface does not take a CANbus, the CANopen Manager goes directly under it, the interface gets the network number and bit rate where it has those settings, and a later run reuses that manager. With several CAN interfaces and none matching the number, or when nothing takes the bus, that network stops with an error that lists the CANbus devices tried, CODESYS's answer to each, and the device's objects.

## What carries over

| canworks | CODESYS |
|---|---|
| bit rate, interface number | CANbus bit rate and network number |
| master `node_id`, `heartbeat_ms`, `sync_period_us`, `sync_window_us`, `start`, `start_nodes`, `start_all_nodes`, `nmt_inhibit_time_us`, `sdo_timeout_ms`, `time_cob_id`/`time_period_ms` | CANopen Manager settings |
| node ID, `mandatory` (CODESYS: optional device when not mandatory), `boot: false` (do not initialize), `restore_configuration` where the device offers it | device General settings |
| PDO communication and mapping, `heartbeat_ms`, node guarding, `heartbeat_consumer`, `heartbeat_watch`, `time_cob_id`, `error_behavior`, PDO links, startup SDOs | from the DCF: the device's PDOs and SDO list |
| each mapped entry's `name`, else the editor's declaration name (`dio_Read_input_8_bit_1`) | variable names on the I/O channels; CODESYS assigns the `%I`/`%Q` addresses itself |
| an entry's [bit channels](config.md#bit-channels) | variable names on the channel's bit sub-channels (bit n of the channel); an output entry with bits maps only its bits, as CODESYS refuses overlapping output mappings, and its channel is left without a variable. Where a channel has no bit sub-channels, the report lists each bit to map by hand |

A node's `codesys` object gives back what only CODESYS has: its CODESYS name (`device`), the identity checks at boot (`checks`, default vendor ID only), a PDO's "processed by the CANopen Manager" (`by_manager`), an entry's fixed I/O address and variable (`address`, `variable`) and a startup SDO's abort-on-error and jump-to-line ([config.md](config.md#codesys-target)). The identity checks and the manager's TIME producer are set through an internal CODESYS interface; when a CODESYS version does not offer it, the report says which ticks to set by hand.

Every other setting is listed in the report under `not set` with the reason, the same words as the configurator's warnings in a CODESYS project, for example the bridge's status and diagnostic locations (use the CANopen Manager's diagnostics or the CiA 405 blocks in CODESYS), SDO variables, LSS settings, the configuration check, and the TPDO receive timeouts. SYNC tied to the PLC cycle is a bus cycle task setting in CODESYS. Slave, J1939 and plain CAN networks, raw messages, the Modbus bridge and the gateway stay with canworks. A canworks slave works under a CODESYS master through its EDS ([slave.md](slave.md)).

## Running it again

Running the script again on the same project updates each device under that CANopen Manager that has a node ID from the config in place: it compares the device with the plan and changes only what differs, through CODESYS's scripting API, and leaves everything else on the device as it is, including settings canworks does not manage. The report says `current` for a device that was up to date and `updated` with the number of settings changed. PDO COB-IDs are written as `$NODEID+16#…` when they equal the EDS's node-based default, so a node ID changed later in CODESYS moves them too.

A device whose PDO mapping or startup SDO list changed in structure (an entry or row added, removed or of another length, a PDO switched on or off) cannot be changed in place: it is removed and added again from its DCF, and its carried CODESYS settings are written back. The report says `replaced` and why, for example `PDO mapping changed (TPDO1)`. Settings made by hand in CODESYS on a replaced device that canworks does not carry are gone; import the project first to keep them in the config.

Devices with other node IDs stay (the report lists them as kept). A node canworks built earlier and that is no longer in the config is removed only when asked: the configurator's Build lists such nodes and asks **Remove N nodes** or **Keep them**, and `canworks-deploy --codesys-import` removes them only with `--codesys-remove-nodes`. Each network's `codesys.managed` lists the node IDs canworks manages; the configurator updates it after each build, so kept nodes are not asked about again.

A DCF installs in the device repository under the product's vendor ID, product code and revision, so after a build the repository holds the last node's DCF of each product, and two nodes of one EDS share that entry. The project's devices keep their own settings; only CODESYS's **Update Device** would bring the repository's version back, and the import never takes per-node values from the repository's DCF. CODESYS maps every mapping sub-entry that has a value, whatever the count says, so the DCFs for CODESYS give the sub-entries beyond the count the value 0.

## canworks next to a CODESYS master

- **Bus trace and commissioning:** the PC tools join a CODESYS-run bus through a USB adapter, read-only until changes are allowed ([pc-adapter.md](pc-adapter.md)). SDO, NMT and LSS from canworks talk to the same nodes as CODESYS's manager, so keep them to commissioning.
- **Simulated devices:** `canworks-canopen-sim` runs simulated nodes on a SocketCAN interface for any master, so a CODESYS controller on Linux can run against them ([simulator.md](simulator.md#canworks-canopen-sim)).

## Requirements and limits

- CODESYS V3.5 with CANopen support on Windows for the build and for importing a `.project`; tested with V3.5 SP22. Importing a PLCopenXML file needs no CODESYS. Older service packs are expected to work but are not tested. Settings an older or vendor build lacks are reported and skipped; the nodes and their PDOs still come from the DCFs.
- The script runs CODESYS's IronPython 2.7, uses only CODESYS's scripting API and needs no add-ons.
- The CODESYS runtime's CANopen licence is not part of this: the CODESYS Store lists which runtimes include the CANopen Manager.
